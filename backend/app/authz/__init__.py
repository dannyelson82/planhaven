"""The single source of access rules (SECURITY.md §7.4, ADR 0004).

Services call `require(principal, action)` (or, for project data from step 9 on,
`require(principal, action, resource)`); there is no other permission code path. PostgreSQL
Row-Level Security enforces the same membership rules independently.

Outcomes:
- `NotFoundError`: the principal may not know the thing exists (reported as 404, never 403).
- `StepUpRequiredError`: allowed, but only after a fresh second factor (403 with a prompt).
- `ForbiddenError`: the principal can see the thing but may not do this (403).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

STEP_UP_WINDOW = timedelta(minutes=5)


class AuthzError(Exception):
    """Base for authorization failures. Messages are safe to show."""


class NotFoundError(AuthzError):
    pass


class ForbiddenError(AuthzError):
    pass


class StepUpRequiredError(ForbiddenError):
    pass


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is asking. Token and OAuth principals are added with those features."""

    user_id: uuid.UUID
    is_admin: bool
    mfa_verified: bool
    reauth_at: datetime | None
    kind: str = "session"

    def recently_verified(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        return (
            self.mfa_verified
            and self.reauth_at is not None
            and now - self.reauth_at <= STEP_UP_WINDOW
        )


class Action(StrEnum):
    # Baseline for every signed-in feature: a fully verified session.
    USE_APP = "app.use"
    # Own account
    VIEW_OWN_ACCOUNT = "account.view"
    CHANGE_PASSWORD = "account.change_password"  # noqa: S105  # an action name, not a secret
    MANAGE_SECOND_FACTORS = "account.manage_second_factors"
    MANAGE_OWN_SESSIONS = "account.manage_sessions"
    READ_NOTIFICATIONS = "account.read_notifications"
    # Administration (users, invites, settings; never project data)
    ADMIN = "admin.manage"


@dataclass(frozen=True, slots=True)
class Rule:
    verified: bool = True  # second factor completed in this session
    recent: bool = False  # second factor within STEP_UP_WINDOW (step-up)
    admin: bool = False  # instance admin


RULES: dict[Action, Rule] = {
    Action.USE_APP: Rule(),
    Action.VIEW_OWN_ACCOUNT: Rule(),
    Action.CHANGE_PASSWORD: Rule(recent=True),
    Action.MANAGE_SECOND_FACTORS: Rule(recent=True),
    Action.MANAGE_OWN_SESSIONS: Rule(),
    Action.READ_NOTIFICATIONS: Rule(),
    Action.ADMIN: Rule(recent=True, admin=True),
}


def require(principal: Principal, action: Action) -> None:
    rule = RULES[action]
    if rule.admin and not principal.is_admin:
        raise NotFoundError("Not found.")
    if rule.verified and not principal.mfa_verified:
        raise ForbiddenError("Second factor required.")
    if rule.recent and not principal.recently_verified():
        raise StepUpRequiredError("Confirm it's you with your second factor to continue.")


def allowed(principal: Principal, action: Action) -> bool:
    try:
        require(principal, action)
    except AuthzError:
        return False
    return True
