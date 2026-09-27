"""Account administration (SECURITY.md §7.1, §7.4).

Admins manage accounts, invites and settings; they never get access to other users' project
data. Every admin action requires a recent second factor and is audited. The last active
admin can't be removed or disabled, and admins can't disable themselves.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from app.core import security_log
from app.db import admin as store
from app.db import auth as auth_store
from app.db.database import Database
from app.services.auth import AuthError, CurrentSession, require_recent


class NotAdminError(AuthError):
    """Not an admin (reported as 404 so the admin area isn't discoverable)."""


@dataclass(frozen=True, slots=True)
class AdminContext:
    session: CurrentSession
    ip: str | None


def require_admin(session: CurrentSession) -> None:
    if not session.user.is_admin:
        raise NotAdminError("Not found.")
    require_recent(session)


async def list_users(db: Database, ctx: AdminContext) -> list[store.UserSummary]:
    require_admin(ctx.session)
    async with db.system_transaction() as conn:
        return await store.list_users(conn)


@dataclass(frozen=True, slots=True)
class InviteInfo:
    id: uuid.UUID
    email: str | None
    created_at: datetime
    expires_at: datetime
    status: str  # pending | used | revoked | expired


async def list_invites(db: Database, ctx: AdminContext) -> list[InviteInfo]:
    require_admin(ctx.session)
    async with db.system_transaction() as conn:
        rows = await store.list_invites(conn)
    now = datetime.now(UTC)

    def status(r: store.InviteRow) -> str:
        if r.used_at:
            return "used"
        if r.revoked_at:
            return "revoked"
        return "expired" if r.expires_at <= now else "pending"

    return [InviteInfo(r.id, r.email, r.created_at, r.expires_at, status(r)) for r in rows]


async def revoke_invite(db: Database, ctx: AdminContext, invite_id: uuid.UUID) -> bool:
    require_admin(ctx.session)
    async with db.system_transaction() as conn:
        revoked = await store.revoke_invite(conn, invite_id)
        if revoked:
            await auth_store.record_audit(
                conn, action="invite.revoked", actor_user_id=ctx.session.user.id, ip=ctx.ip
            )
    return revoked


async def _target(conn: AsyncConnection, user_id: uuid.UUID) -> auth_store.UserRow:
    row = await auth_store.user_by_id(conn, user_id)
    if row is None:
        raise LookupError
    return row


async def set_disabled(db: Database, ctx: AdminContext, user_id: uuid.UUID, disabled: bool) -> None:
    require_admin(ctx.session)
    if disabled and user_id == ctx.session.user.id:
        raise AuthError("You can't disable your own account.")
    async with db.system_transaction() as conn:
        target = await _target(conn, user_id)
        if disabled and target.is_admin and await store.admin_count(conn) <= 1:
            raise AuthError("You can't disable the last admin.")
        await store.set_disabled(conn, user_id, disabled)
        if disabled:
            await store.revoke_all_sessions(conn, user_id)
        await auth_store.record_audit(
            conn,
            action="user.disabled" if disabled else "user.enabled",
            actor_user_id=ctx.session.user.id,
            ip=ctx.ip,
        )
    security_log.event(
        "user_disabled" if disabled else "user_enabled",
        ip=ctx.ip,
        user_id=ctx.session.user.id,
        target_user_id=str(user_id),
    )


async def set_admin(db: Database, ctx: AdminContext, user_id: uuid.UUID, is_admin: bool) -> None:
    require_admin(ctx.session)
    async with db.system_transaction() as conn:
        target = await _target(conn, user_id)
        if not is_admin and target.is_admin and await store.admin_count(conn) <= 1:
            raise AuthError("You can't remove the last admin.")
        await store.set_admin(conn, user_id, is_admin)
        await store.notify(
            conn,
            user_id,
            "security_change",
            {"change": "admin_granted" if is_admin else "admin_revoked", "ip": ctx.ip},
        )
        await auth_store.record_audit(
            conn,
            action="user.admin_granted" if is_admin else "user.admin_revoked",
            actor_user_id=ctx.session.user.id,
            ip=ctx.ip,
        )
    security_log.event(
        "admin_granted" if is_admin else "admin_revoked",
        ip=ctx.ip,
        user_id=ctx.session.user.id,
        target_user_id=str(user_id),
    )


async def reset_second_factor(db: Database, ctx: AdminContext, user_id: uuid.UUID) -> None:
    """For a user who lost their phone and recovery codes. Removes all their second factors and
    signs them out; at the next password sign-in they must enroll a new one."""
    require_admin(ctx.session)
    if user_id == ctx.session.user.id:
        raise AuthError("Use your own security settings to change your second factor.")
    async with db.system_transaction() as conn:
        await _target(conn, user_id)
        await store.reset_second_factors(conn, user_id)
        await store.revoke_all_sessions(conn, user_id)
        await store.notify(
            conn, user_id, "security_change", {"change": "second_factor_reset", "ip": ctx.ip}
        )
        await auth_store.record_audit(
            conn, action="user.mfa_reset", actor_user_id=ctx.session.user.id, ip=ctx.ip
        )
    security_log.event(
        "mfa_reset", ip=ctx.ip, user_id=ctx.session.user.id, target_user_id=str(user_id)
    )
