"""Passkeys (WebAuthn): register, use as the second factor or for step-up, or sign in with a
passkey alone (SECURITY.md §7.1).

Passkeys are required to be discoverable and user-verified (biometric or device PIN), so a
passkey is itself two factors. Challenges are single use, expire after 5 minutes, and are
bound to the session they were issued for.
"""

import json
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    AuthenticatorTransport,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core import security_log
from app.core.config import Settings
from app.db import admin as admin_store
from app.db import auth as auth_store
from app.db import mfa as mfa_store
from app.db import passkeys as store
from app.db.database import Database
from app.services import limits
from app.services import mfa as mfa_service
from app.services.auth import (
    AuthError,
    CurrentSession,
    NewSession,
    require_recent,
    start_session,
    user_from_row,
)

RP_NAME = "Planhaven"
CHALLENGE_TTL = timedelta(minutes=5)
MAX_PASSKEYS = 20


@dataclass(frozen=True, slots=True)
class Options:
    challenge_id: uuid.UUID
    options: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PasskeyInfo:
    id: uuid.UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


def _rp(settings: Settings) -> tuple[str, str]:
    host = urlsplit(settings.base_url).hostname
    if not host:
        raise AuthError("Passkeys need BASE_URL to have a host name.")
    return host, settings.base_origin


def _descriptors(rows: list[store.PasskeyRow]) -> list[PublicKeyCredentialDescriptor]:
    out = []
    for r in rows:
        transports = []
        for t in r.transports:
            try:
                transports.append(AuthenticatorTransport(t))
            except ValueError:
                continue
        out.append(PublicKeyCredentialDescriptor(id=r.credential_id, transports=transports))
    return out


def _credential_parts(credential: dict[str, Any]) -> tuple[bytes, bytes | None]:
    try:
        raw_id = base64url_to_bytes(str(credential["rawId"]))
        handle = credential.get("response", {}).get("userHandle")
        return raw_id, base64url_to_bytes(handle) if handle else None
    except KeyError, TypeError, ValueError, AttributeError:
        raise AuthError("Passkey response is malformed.") from None


# ---------------------------------------------------------------- registration


async def registration_options(
    db: Database, settings: Settings, session: CurrentSession
) -> Options:
    """A partial session may register only while the account has no second factor."""
    rp_id, _ = _rp(settings)
    user = session.user
    async with db.user_transaction(user.id) as conn:
        if await mfa_store.has_second_factor(conn, user.id):
            require_recent(session)
        existing = await store.for_user(conn, user.id)
    if len(existing) >= MAX_PASSKEYS:
        raise AuthError("You have too many passkeys. Remove one first.")
    challenge = secrets.token_bytes(32)
    options = generate_registration_options(
        rp_id=rp_id,
        rp_name=RP_NAME,
        user_id=user.id.bytes,
        user_name=user.email,
        user_display_name=user.display_name,
        challenge=challenge,
        timeout=int(CHALLENGE_TTL.total_seconds() * 1000),
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=_descriptors(existing),
    )
    async with db.system_transaction() as conn:
        challenge_id = await store.new_challenge(
            conn,
            challenge=challenge,
            purpose="register",
            user_id=user.id,
            session_id=session.id,
            ttl=CHALLENGE_TTL,
        )
    return Options(challenge_id, json.loads(options_to_json(options)))


async def register(
    db: Database,
    settings: Settings,
    session: CurrentSession,
    *,
    challenge_id: uuid.UUID,
    credential: dict[str, Any],
    name: str,
    ip: str | None,
) -> list[str]:
    """Store a new passkey. Returns new recovery codes if this is the account's first second
    factor (shown once), else an empty list. A partial session becomes verified."""
    rp_id, origin = _rp(settings)
    user = session.user
    async with db.system_transaction() as conn:
        challenge = await store.take_challenge(
            conn, challenge_id, purpose="register", session_id=session.id
        )
    if challenge is None:
        raise AuthError("The passkey request expired. Try again.")
    try:
        verified = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp_id,
            expected_origin=origin,
            require_user_verification=True,
        )
    except Exception:
        raise AuthError("The passkey could not be verified.") from None

    transports = credential.get("response", {}).get("transports") or []
    async with db.user_transaction(user.id) as conn:
        first_factor = not await mfa_store.has_second_factor(conn, user.id)
        if not first_factor:
            require_recent(session)
        await store.add(
            conn,
            user_id=user.id,
            credential_id=verified.credential_id,
            public_key=verified.credential_public_key,
            sign_count=verified.sign_count,
            transports=[str(t)[:20] for t in transports][:10],
            name=name.strip()[:100] or "Passkey",
        )
        codes: list[str] = []
        if await mfa_store.remaining_recovery_codes(conn, user.id) == 0:
            codes = await mfa_service.issue_recovery_codes(conn, user.id)
        await mfa_store.mark_session_verified(conn, session.id)
        await auth_store.record_audit(
            conn, action="mfa.passkey.added", actor_user_id=user.id, ip=ip
        )
        await admin_store.notify(
            conn, user.id, "security_change", {"change": "passkey_added", "ip": ip}
        )
    security_log.event("passkey_added", ip=ip, user_id=user.id)
    return codes


# ---------------------------------------------------------------- second factor / step-up


async def verification_options(
    db: Database, settings: Settings, session: CurrentSession
) -> Options:
    rp_id, _ = _rp(settings)
    async with db.user_transaction(session.user.id) as conn:
        rows = await store.for_user(conn, session.user.id)
    if not rows:
        raise AuthError("You have no passkeys.")
    challenge = secrets.token_bytes(32)
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        timeout=int(CHALLENGE_TTL.total_seconds() * 1000),
        allow_credentials=_descriptors(rows),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    async with db.system_transaction() as conn:
        challenge_id = await store.new_challenge(
            conn,
            challenge=challenge,
            purpose="verify",
            user_id=session.user.id,
            session_id=session.id,
            ttl=CHALLENGE_TTL,
        )
    return Options(challenge_id, json.loads(options_to_json(options)))


async def verify(
    db: Database,
    settings: Settings,
    session: CurrentSession,
    *,
    challenge_id: uuid.UUID,
    credential: dict[str, Any],
    ip: str | None,
) -> None:
    rp_id, origin = _rp(settings)
    await mfa_service.check_mfa_limit(db, session, ip)
    async with db.system_transaction() as conn:
        challenge = await store.take_challenge(
            conn, challenge_id, purpose="verify", session_id=session.id
        )
    ok = False
    if challenge is not None:
        try:
            raw_id, _ = _credential_parts(credential)
            async with db.user_transaction(session.user.id) as conn:
                row = await store.by_credential_id(conn, raw_id)
                if row is not None and row.user_id == session.user.id:
                    result = verify_authentication_response(
                        credential=credential,
                        expected_challenge=challenge,
                        expected_rp_id=rp_id,
                        expected_origin=origin,
                        credential_public_key=row.public_key,
                        credential_current_sign_count=row.sign_count,
                        require_user_verification=True,
                    )
                    await store.record_use(conn, row.id, result.new_sign_count)
                    await mfa_store.mark_session_verified(conn, session.id)
                    await auth_store.record_audit(
                        conn, action="mfa.verified", actor_user_id=session.user.id, ip=ip
                    )
                    ok = True
        except Exception:
            ok = False
    if not ok:
        await mfa_service.record_failure(db, session, ip)


# ---------------------------------------------------------------- passkey-only sign-in


async def login_options(db: Database, settings: Settings) -> Options:
    rp_id, _ = _rp(settings)
    challenge = secrets.token_bytes(32)
    options = generate_authentication_options(
        rp_id=rp_id,
        challenge=challenge,
        timeout=int(CHALLENGE_TTL.total_seconds() * 1000),
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    async with db.system_transaction() as conn:
        challenge_id = await store.new_challenge(
            conn,
            challenge=challenge,
            purpose="login",
            user_id=None,
            session_id=None,
            ttl=CHALLENGE_TTL,
        )
    return Options(challenge_id, json.loads(options_to_json(options)))


async def login(
    db: Database,
    settings: Settings,
    *,
    challenge_id: uuid.UUID,
    credential: dict[str, Any],
    ip: str | None,
    user_agent: str | None,
) -> NewSession:
    """Sign in with a passkey alone. The resulting session is fully verified."""
    rp_id, origin = _rp(settings)
    await limits.check(
        db, [(limits.PASSKEY_LOGIN_IP, limits.key(limits.PASSKEY_LOGIN_IP, ip))], ip=ip
    )
    new: NewSession | None = None
    async with db.system_transaction() as conn:
        challenge = await store.take_challenge(conn, challenge_id, purpose="login", session_id=None)
        try:
            raw_id, handle = _credential_parts(credential)
            row = await store.by_credential_id(conn, raw_id) if challenge else None
            user = await auth_store.user_by_id(conn, row.user_id) if row else None
            if (
                challenge is not None
                and row is not None
                and user is not None
                and not user.disabled
                and (handle is None or handle == user.id.bytes)
            ):
                result = verify_authentication_response(
                    credential=credential,
                    expected_challenge=challenge,
                    expected_rp_id=rp_id,
                    expected_origin=origin,
                    credential_public_key=row.public_key,
                    credential_current_sign_count=row.sign_count,
                    require_user_verification=True,
                )
                await store.record_use(conn, row.id, result.new_sign_count)
                if not await admin_store.seen_ip_recently(conn, user.id, ip, None):
                    await admin_store.notify(
                        conn,
                        user.id,
                        "new_sign_in",
                        {"ip": ip, "user_agent": (user_agent or "")[:120], "method": "passkey"},
                    )
                token = await start_session(conn, user.id, ip, user_agent, mfa_verified=True)
                await auth_store.record_audit(
                    conn,
                    action="login.succeeded",
                    actor_user_id=user.id,
                    ip=ip,
                    details=json.dumps({"method": "passkey"}),
                )
                new = NewSession(token, user_from_row(user))
        except Exception:
            new = None
        if new is None:
            await auth_store.record_audit(
                conn,
                action="login.failed",
                actor_user_id=None,
                ip=ip,
                details=json.dumps({"method": "passkey"}),
            )
    if new is None:
        security_log.event("login_failed", ip=ip, user_id=None, method="passkey")
        raise AuthError("Passkey sign-in failed.")
    security_log.event("login_succeeded", ip=ip, user_id=new.user.id, method="passkey")
    return new


# ---------------------------------------------------------------- management


async def list_passkeys(db: Database, session: CurrentSession) -> list[PasskeyInfo]:
    async with db.user_transaction(session.user.id) as conn:
        rows = await store.for_user(conn, session.user.id)
    return [PasskeyInfo(r.id, r.name, r.created_at, r.last_used_at) for r in rows]


async def remove(
    db: Database, session: CurrentSession, passkey_id: uuid.UUID, ip: str | None
) -> bool:
    """Needs a recent second factor, and never removes the account's last second factor
    (otherwise the password alone could enroll a new one)."""
    require_recent(session)
    user = session.user
    async with db.user_transaction(user.id) as conn:
        remaining_passkeys = await store.count_for_user(conn, user.id)
        has_totp = await mfa_store.totp_for(conn, user.id, confirmed=True) is not None
        if remaining_passkeys <= 1 and not has_totp:
            raise AuthError("Add another passkey or an authenticator app before removing this one.")
        removed = await store.delete(conn, user.id, passkey_id)
        if removed:
            await auth_store.record_audit(
                conn, action="mfa.passkey.removed", actor_user_id=user.id, ip=ip
            )
    if removed:
        security_log.event("passkey_removed", ip=ip, user_id=user.id)
    return removed
