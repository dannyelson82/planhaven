"""Sign-in, sessions and first-boot setup (SECURITY.md §7.1, §7.2).

Responses never reveal whether an account exists: unknown email and wrong password give the
same result and take the same time.
"""

import json
import re
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncConnection

from app.auth import passwords, tokens
from app.auth.passwords import PasswordPolicyError
from app.db import auth as store
from app.db.database import Database

IDLE_TIMEOUT = timedelta(days=7)
ABSOLUTE_TIMEOUT = timedelta(days=30)
TOUCH_INTERVAL = timedelta(minutes=5)
SETUP_TOKEN_TTL = timedelta(hours=24)

_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s.]{2,}$")


class AuthError(Exception):
    """Generic failure. The message is safe to show and reveals nothing about accounts."""


@dataclass(frozen=True, slots=True)
class User:
    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool


@dataclass(frozen=True, slots=True)
class NewSession:
    token: str
    user: User


@dataclass(frozen=True, slots=True)
class CurrentSession:
    id: uuid.UUID
    token: str
    user: User
    mfa_verified: bool


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise AuthError("Enter a valid email address.")
    return email


def _user(row: store.UserRow) -> User:
    return User(row.id, row.email, row.display_name, row.is_admin)


async def _start_session(
    conn: AsyncConnection, user_id: uuid.UUID, ip: str | None, user_agent: str | None
) -> str:
    token = tokens.new_token()
    await store.create_session(
        conn,
        user_id=user_id,
        token_hash=tokens.token_hash(token),
        idle=IDLE_TIMEOUT,
        absolute=ABSOLUTE_TIMEOUT,
        ip=ip,
        user_agent=user_agent,
    )
    return token


# ---------------------------------------------------------------- first boot


async def setup_required(db: Database) -> bool:
    async with db.system_transaction() as conn:
        return not await store.any_admin(conn)


async def issue_setup_token(db: Database) -> str | None:
    """A new one-time setup token if no admin exists yet, else None. Called at every boot."""
    async with db.system_transaction() as conn:
        if await store.any_admin(conn):
            return None
        token = tokens.new_token(tokens.SETUP_PREFIX)
        await store.replace_setup_token(conn, tokens.token_hash(token), SETUP_TOKEN_TTL)
        return token


async def complete_setup(
    db: Database,
    *,
    setup_token: str,
    email: str,
    display_name: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
) -> NewSession:
    email = normalize_email(email)
    display_name = display_name.strip()
    passwords.check_policy(password, email=email, display_name=display_name)
    password_hash = passwords.hash_password(password)
    async with db.system_transaction() as conn:
        if await store.any_admin(conn) or not await store.consume_setup_token(
            conn, tokens.token_hash(setup_token)
        ):
            raise AuthError("The setup token is invalid or has expired.")
        user_id = await store.create_user(
            conn,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            is_admin=True,
        )
        await store.record_audit(conn, action="setup.completed", actor_user_id=user_id, ip=ip)
        await store.record_audit(conn, action="login.succeeded", actor_user_id=user_id, ip=ip)
        token = await _start_session(conn, user_id, ip, user_agent)
    return NewSession(token, User(user_id, email, display_name, True))


# ---------------------------------------------------------------- sign-in


async def login(
    db: Database, *, email: str, password: str, ip: str | None, user_agent: str | None
) -> NewSession:
    try:
        email = normalize_email(email)
    except AuthError:
        email = ""
    async with db.system_transaction() as conn:
        row = await store.user_by_email(conn, email) if email else None
        # Always verify (against a dummy hash if there's no account) so timing is identical.
        ok = passwords.verify_password(row.password_hash if row else None, password)
        if row is None or not ok or row.disabled:
            await store.record_audit(
                conn,
                action="login.failed",
                actor_user_id=None,
                ip=ip,
                details=json.dumps({"reason": "invalid_credentials"}),
            )
            failed = True
        else:
            failed = False
            if passwords.needs_rehash(row.password_hash):
                await store.set_password_hash(conn, row.id, passwords.hash_password(password))
            await store.record_audit(conn, action="login.succeeded", actor_user_id=row.id, ip=ip)
            token = await _start_session(conn, row.id, ip, user_agent)
    if failed or row is None:
        raise AuthError("Incorrect email or password.")
    return NewSession(token, _user(row))


async def authenticate(db: Database, token: str) -> CurrentSession | None:
    if not token or len(token) > 200:
        return None
    async with db.system_transaction() as conn:
        session = await store.active_session(conn, tokens.token_hash(token))
        if session is None:
            return None
        user = await store.user_by_id(conn, session.user_id)
        if user is None:
            return None
        if (session.idle_expires_at - session.last_seen_at) < IDLE_TIMEOUT - TOUCH_INTERVAL:
            await store.touch_session(conn, session.id, IDLE_TIMEOUT)
    return CurrentSession(session.id, token, _user(user), session.mfa_verified)


async def logout(db: Database, session: CurrentSession, ip: str | None) -> None:
    async with db.user_transaction(session.user.id) as conn:
        await store.revoke_session(conn, session.id)
        await store.record_audit(conn, action="logout", actor_user_id=session.user.id, ip=ip)


async def change_password(
    db: Database,
    session: CurrentSession,
    *,
    current_password: str,
    new_password: str,
    ip: str | None,
) -> None:
    """Requires the current password; signs out every other session (SECURITY.md §7.2)."""
    user = session.user
    passwords.check_policy(new_password, email=user.email, display_name=user.display_name)
    async with db.user_transaction(user.id) as conn:
        row = await store.user_by_id(conn, user.id)
        if row is None or not passwords.verify_password(row.password_hash, current_password):
            raise AuthError("Your current password is incorrect.")
        await store.set_password_hash(conn, user.id, passwords.hash_password(new_password))
        await store.revoke_other_sessions(conn, user.id, keep=session.id)
        await store.record_audit(conn, action="password.changed", actor_user_id=user.id, ip=ip)


__all__ = ["AuthError", "PasswordPolicyError"]
