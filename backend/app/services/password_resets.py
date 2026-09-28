"""Password reset links (SECURITY.md §7.1).

There is no email in PlanHaven, so a forgotten password is reset by an admin: they make a
one-time link and hand it over (text message, in person). `BASE_URL/reset#<token>`: the token
is in the URL fragment, so it never reaches proxy or server logs; it's 256-bit, stored as a
hash, single use, valid 24 hours, and a new link cancels older ones. Using it sets the new
password and signs out every device. The second factor is unchanged: the person still needs
their authenticator or passkey to sign in (an admin can reset that separately).
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
from app.services.admin import AdminContext, require_admin
from app.services.auth import AuthError

RESET_PREFIX = "phv_rst_"
RESET_TTL = timedelta(hours=24)
RESET_IP = limits.Limit("reset-ip", capacity=10, per_second=1 / 60)
INVALID = "This reset link is invalid, used or expired. Ask an admin for a new one."


@dataclass(frozen=True, slots=True)
class CreatedReset:
    url: str
    expires_at: datetime


async def create(
    db: Database, ctx: AdminContext, user_id: uuid.UUID, *, base_url: str
) -> CreatedReset:
    require_admin(ctx.session)
    if user_id == ctx.session.user.id:
        raise AuthError("Change your own password from your Account page.")
    token = tokens.new_token(RESET_PREFIX)
    async with db.system_transaction() as conn:
        target = await auth_store.user_by_id(conn, user_id)
        if target is None:
            raise LookupError(user_id)
        if target.disabled:
            raise AuthError("This account is disabled. Enable it first.")
        row = await store.create_password_reset(
            conn,
            user_id=user_id,
            token_hash=tokens.token_hash(token),
            created_by=ctx.session.user.id,
            ttl=RESET_TTL,
        )
        await auth_store.record_audit(
            conn, action="user.password_reset_link", actor_user_id=ctx.session.user.id, ip=ctx.ip
        )
    security_log.event(
        "password_reset_created",
        ip=ctx.ip,
        user_id=ctx.session.user.id,
        target_user_id=str(user_id),
    )
    return CreatedReset(f"{base_url}/reset#{token}", row.expires_at)


async def check(db: Database, token: str, ip: str | None) -> bool:
    await limits.check(db, [(RESET_IP, limits.key(RESET_IP, ip))], ip=ip)
    if not token.startswith(RESET_PREFIX) or len(token) > 200:
        return False
    async with db.system_transaction() as conn:
        return await store.valid_password_reset(conn, tokens.token_hash(token)) is not None


async def accept(db: Database, *, token: str, password: str, ip: str | None) -> None:
    await limits.check(db, [(RESET_IP, limits.key(RESET_IP, ip))], ip=ip)
    if not token.startswith(RESET_PREFIX) or len(token) > 200:
        raise AuthError(INVALID)
    async with db.system_transaction() as conn:
        reset = await store.valid_password_reset(conn, tokens.token_hash(token))
        user = await auth_store.user_by_id(conn, reset.user_id) if reset else None
        if reset is None or user is None:
            raise AuthError(INVALID)
        # Policy first, so a weak password doesn't use up the link.
        passwords.check_policy(password, email=user.email, display_name=user.display_name)
        if not await store.consume_password_reset(conn, reset.id):
            raise AuthError(INVALID)
        await auth_store.set_password_hash(conn, user.id, passwords.hash_password(password))
        await store.revoke_all_sessions(conn, user.id)
        await store.notify(conn, user.id, "security_change", {"change": "password_reset", "ip": ip})
        await auth_store.record_audit(conn, action="password.reset", actor_user_id=user.id, ip=ip)
    security_log.event("password_reset_used", ip=ip, user_id=user.id)
