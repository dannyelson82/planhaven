"""Invites: the only way to create an account after setup (SECURITY.md §7.1, §7.3).

An invite link is `BASE_URL/invite#<token>`: the token is in the URL fragment, which browsers
never send to servers, so it doesn't reach proxy or server logs. Tokens are 256-bit, stored
hashed, single use, and expire after 72 hours. An invite may be bound to one email address.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.auth import passwords, tokens
from app.core import security_log
from app.db import admin as store
from app.db import auth as auth_store
from app.db.database import Database
from app.services import limits
from app.services.auth import AuthError, NewSession, User, normalize_email, start_session

INVITE_PREFIX = "phv_inv_"
INVITE_TTL = timedelta(hours=72)
INVITE_IP = limits.Limit("invite-ip", capacity=10, per_second=1 / 60)


@dataclass(frozen=True, slots=True)
class CreatedInvite:
    id: uuid.UUID
    token: str
    url: str
    expires_at: datetime


async def create(
    db: Database, *, base_url: str, created_by: uuid.UUID, email: str | None, ip: str | None
) -> CreatedInvite:
    bound = normalize_email(email) if email else None
    token = tokens.new_token(INVITE_PREFIX)
    async with db.system_transaction() as conn:
        invite_id = await store.create_invite(
            conn,
            token_hash=tokens.token_hash(token),
            email=bound,
            created_by=created_by,
            ttl=INVITE_TTL,
        )
        row = next(i for i in await store.list_invites(conn) if i.id == invite_id)
        await auth_store.record_audit(
            conn, action="invite.created", actor_user_id=created_by, ip=ip
        )
    security_log.event("invite_created", ip=ip, user_id=created_by)
    return CreatedInvite(invite_id, token, f"{base_url}/invite#{token}", row.expires_at)


async def check(db: Database, token: str, ip: str | None) -> str | None:
    """Whether a token is usable; returns the bound email (or "" if unbound), else None."""
    await limits.check(db, [(INVITE_IP, limits.key(INVITE_IP, ip))], ip=ip)
    if not token.startswith(INVITE_PREFIX) or len(token) > 200:
        return None
    async with db.system_transaction() as conn:
        invite = await store.valid_invite(conn, tokens.token_hash(token))
    if invite is None:
        return None
    return invite.email or ""


async def accept(
    db: Database,
    *,
    token: str,
    email: str,
    display_name: str,
    password: str,
    ip: str | None,
    user_agent: str | None,
) -> NewSession:
    """Create the account and a password-only session (the user enrolls a second factor
    next)."""
    await limits.check(db, [(INVITE_IP, limits.key(INVITE_IP, ip))], ip=ip)
    email = normalize_email(email)
    display_name = display_name.strip()
    passwords.check_policy(password, email=email, display_name=display_name)
    password_hash = passwords.hash_password(password)
    invalid = AuthError("This invite is invalid or has expired.")
    async with db.system_transaction() as conn:
        invite = await store.valid_invite(conn, tokens.token_hash(token))
        if invite is None or (invite.email and invite.email != email):
            raise invalid
        if await auth_store.user_by_email(conn, email) is not None:
            raise AuthError("An account with this email already exists. Sign in instead.")
        user_id = await auth_store.create_user(
            conn,
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            is_admin=False,
        )
        if not await store.consume_invite(conn, invite.id, user_id):
            raise invalid
        await auth_store.record_audit(conn, action="invite.accepted", actor_user_id=user_id, ip=ip)
        session_token = await start_session(conn, user_id, ip, user_agent)
    security_log.event("invite_accepted", ip=ip, user_id=user_id)
    return NewSession(session_token, User(user_id, email, display_name, False))
