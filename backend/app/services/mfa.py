"""Mandatory second factor: TOTP, recovery codes and step-up (SECURITY.md §7.1).

- A password alone gives a *partial* session: it can only complete the second factor (or
  enroll one, if the account has none yet) and sign out.
- TOTP codes are checked with ±1 time step of tolerance and can never be reused.
- Five wrong second-factor attempts end the session.
- Sensitive actions need a fresh second factor (within 5 minutes): "step-up".
"""

import base64
import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass

import pyotp
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.crypto import Keyring
from app.db import auth as auth_store
from app.db import mfa as store
from app.db.database import Database
from app.services.auth import AuthError, CurrentSession, recently_verified, require_recent

ISSUER = "Planhaven"
STEP_SECONDS = 30
RECOVERY_CODE_COUNT = 10
MAX_FAILURES = 5
_PURPOSE = "totp-secret"


@dataclass(frozen=True, slots=True)
class TotpEnrollment:
    secret: str
    otpauth_uri: str


@dataclass(frozen=True, slots=True)
class MfaStatus:
    has_totp: bool
    recovery_codes_remaining: int
    mfa_verified: bool
    recently_verified: bool


def _context(user_id: uuid.UUID) -> str:
    return f"user:{user_id}"


# ---------------------------------------------------------------- recovery codes


def _new_recovery_code() -> str:
    raw = base64.b32encode(secrets.token_bytes(10)).decode()  # 80 bits, 16 characters
    return "-".join(raw[i : i + 4] for i in range(0, 16, 4))


def _normalize_recovery(code: str) -> str:
    return "".join(c for c in code.upper() if c.isalnum())


def _recovery_hash(code: str) -> bytes:
    return hashlib.sha256(b"planhaven recovery\x00" + _normalize_recovery(code).encode()).digest()


# ---------------------------------------------------------------- TOTP


def _matching_step(secret: str, code: str, now: float | None = None) -> int | None:
    code = "".join(c for c in code if c.isdigit())
    if len(code) != 6:
        return None
    totp = pyotp.TOTP(secret, digits=6, interval=STEP_SECONDS)
    current = int(time.time() if now is None else now) // STEP_SECONDS
    for step in (current, current - 1, current + 1):
        if hmac.compare_digest(totp.at(step * STEP_SECONDS), code):
            return step
    return None


async def status(db: Database, session: CurrentSession) -> MfaStatus:
    async with db.user_transaction(session.user.id) as conn:
        totp = await store.totp_for(conn, session.user.id, confirmed=True)
        remaining = await store.remaining_recovery_codes(conn, session.user.id)
    return MfaStatus(
        has_totp=totp is not None,
        recovery_codes_remaining=remaining,
        mfa_verified=session.mfa_verified,
        recently_verified=recently_verified(session),
    )


async def start_totp_enrollment(
    db: Database, keyring: Keyring, session: CurrentSession
) -> TotpEnrollment:
    """A partial session may enroll only while the account has no second factor at all;
    replacing an existing one needs a recent second factor."""
    user = session.user
    async with db.user_transaction(user.id) as conn:
        if await store.has_second_factor(conn, user.id):
            require_recent(session)
        secret = pyotp.random_base32(length=32)  # 160 bits
        encrypted = keyring.encrypt(_PURPOSE, secret.encode(), _context(user.id))
        await store.save_pending_totp(conn, user.id, encrypted)
    uri = pyotp.TOTP(secret, interval=STEP_SECONDS).provisioning_uri(
        name=user.email, issuer_name=ISSUER
    )
    return TotpEnrollment(secret, uri)


async def confirm_totp_enrollment(
    db: Database, keyring: Keyring, session: CurrentSession, code: str, ip: str | None
) -> list[str]:
    """Confirm the pending secret with a current code. Returns new recovery codes (shown
    once). The session becomes fully verified."""
    user = session.user
    async with db.user_transaction(user.id) as conn:
        pending = await store.totp_for(conn, user.id, confirmed=False)
        if pending is None:
            raise AuthError("Start authenticator setup first.")
        secret = keyring.decrypt(_PURPOSE, pending.secret_encrypted, _context(user.id))
        step = _matching_step(secret.decode(), code)
        if step is None:
            raise AuthError("That code didn't match. Check your authenticator app's clock.")
        await store.confirm_totp(conn, user.id, step)
        codes = await issue_recovery_codes(conn, user.id)
        await store.mark_session_verified(conn, session.id)
        await auth_store.record_audit(
            conn, action="mfa.totp.enrolled", actor_user_id=user.id, ip=ip
        )
    return codes


async def verify_totp(
    db: Database, keyring: Keyring, session: CurrentSession, code: str, ip: str | None
) -> None:
    """Second step of sign-in, or step-up. Wrong codes count toward ending the session."""
    user = session.user
    async with db.user_transaction(user.id) as conn:
        totp = await store.totp_for(conn, user.id, confirmed=True)
        step = None
        if totp is not None:
            secret = keyring.decrypt(_PURPOSE, totp.secret_encrypted, _context(user.id))
            step = _matching_step(secret.decode(), code)
        if step is not None and await store.use_totp_step(conn, user.id, step):
            await store.mark_session_verified(conn, session.id)
            await auth_store.record_audit(conn, action="mfa.verified", actor_user_id=user.id, ip=ip)
            return
    await record_failure(db, session, ip)


async def verify_recovery_code(
    db: Database, session: CurrentSession, code: str, ip: str | None
) -> int:
    """Use a recovery code instead of TOTP. Returns how many unused codes remain."""
    user = session.user
    if len(code) <= 40:
        async with db.user_transaction(user.id) as conn:
            if await store.use_recovery_code(conn, user.id, _recovery_hash(code)):
                await store.mark_session_verified(conn, session.id)
                await auth_store.record_audit(
                    conn, action="mfa.recovery_code_used", actor_user_id=user.id, ip=ip
                )
                return await store.remaining_recovery_codes(conn, user.id)
    await record_failure(db, session, ip)
    raise AssertionError("unreachable")


async def issue_recovery_codes(conn: AsyncConnection, user_id: uuid.UUID) -> list[str]:
    """Replace the user's recovery codes; returns the new ones (shown once)."""
    codes = [_new_recovery_code() for _ in range(RECOVERY_CODE_COUNT)]
    await store.replace_recovery_codes(conn, user_id, [_recovery_hash(c) for c in codes])
    return codes


async def regenerate_recovery_codes(
    db: Database, session: CurrentSession, ip: str | None
) -> list[str]:
    require_recent(session)
    async with db.user_transaction(session.user.id) as conn:
        codes = await issue_recovery_codes(conn, session.user.id)
        await auth_store.record_audit(
            conn, action="mfa.recovery_codes_regenerated", actor_user_id=session.user.id, ip=ip
        )
    return codes


async def record_failure(db: Database, session: CurrentSession, ip: str | None) -> None:
    # Commit first, then raise: raising inside the transaction would roll back the counter
    # and the revocation.
    async with db.user_transaction(session.user.id) as conn:
        failures = await store.record_mfa_failure(conn, session.id)
        await auth_store.record_audit(
            conn, action="mfa.failed", actor_user_id=session.user.id, ip=ip
        )
        if failures >= MAX_FAILURES:
            await auth_store.revoke_session(conn, session.id)
    if failures >= MAX_FAILURES:
        raise AuthError("Too many wrong codes. Sign in again.")
    raise AuthError("That code is not valid.")
