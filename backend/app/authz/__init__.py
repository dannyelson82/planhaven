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
from typing import Literal

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
    CHANGE_SIGN_IN = "account.change_sign_in"  # changing the password
    MANAGE_SECOND_FACTORS = "account.manage_second_factors"
    MANAGE_OWN_SESSIONS = "account.manage_sessions"
    READ_NOTIFICATIONS = "account.read_notifications"
    # Administration (users, invites, settings; never project data)
    ADMIN = "admin.manage"
    # Projects (need a project role, see PROJECT_ROLES)
    PROJECT_VIEW = "project.view"
    PROJECT_EDIT = "project.edit"
    PROJECT_MANAGE = "project.manage"
    PROJECT_SHARE = "project.share"  # add/remove members, change roles
    PROJECT_SHARE_LINK = "project.share_link"  # make a link for someone without an account
    # Assets (vehicle, boat, house, ...): shared like projects, same roles (ADR 0005)
    ASSET_VIEW = "asset.view"
    ASSET_EDIT = "asset.edit"
    ASSET_MANAGE = "asset.manage"
    ASSET_SHARE = "asset.share"
    # Contacts (contractors, suppliers): shared one by one, same roles
    CONTACT_VIEW = "contact.view"
    CONTACT_EDIT = "contact.edit"
    CONTACT_MANAGE = "contact.manage"
    CONTACT_SHARE = "contact.share"
    # Templates (lists and task sets for later projects): shared one by one, same roles
    TEMPLATE_VIEW = "template.view"
    TEMPLATE_EDIT = "template.edit"
    TEMPLATE_MANAGE = "template.manage"
    TEMPLATE_SHARE = "template.share"


@dataclass(frozen=True, slots=True)
class Rule:
    verified: bool = True  # second factor completed in this session
    recent: bool = False  # second factor within STEP_UP_WINDOW (step-up)
    admin: bool = False  # instance admin


RULES: dict[Action, Rule] = {
    Action.USE_APP: Rule(),
    Action.VIEW_OWN_ACCOUNT: Rule(),
    Action.CHANGE_SIGN_IN: Rule(recent=True),
    Action.MANAGE_SECOND_FACTORS: Rule(recent=True),
    Action.MANAGE_OWN_SESSIONS: Rule(),
    Action.READ_NOTIFICATIONS: Rule(),
    Action.ADMIN: Rule(recent=True, admin=True),
    Action.PROJECT_VIEW: Rule(),
    Action.PROJECT_EDIT: Rule(),
    Action.PROJECT_MANAGE: Rule(),
    # Changing who can see a project needs a fresh second factor (SECURITY.md §7.1).
    Action.PROJECT_SHARE: Rule(recent=True),
    # A share link lets someone in without an account: a fresh second factor (ADR 0015).
    Action.PROJECT_SHARE_LINK: Rule(recent=True),
    Action.ASSET_VIEW: Rule(),
    Action.ASSET_EDIT: Rule(),
    Action.ASSET_MANAGE: Rule(),
    Action.ASSET_SHARE: Rule(recent=True),
    Action.CONTACT_VIEW: Rule(),
    Action.CONTACT_EDIT: Rule(),
    Action.CONTACT_MANAGE: Rule(),
    Action.CONTACT_SHARE: Rule(recent=True),
    Action.TEMPLATE_VIEW: Rule(),
    Action.TEMPLATE_EDIT: Rule(),
    Action.TEMPLATE_MANAGE: Rule(),
    Action.TEMPLATE_SHARE: Rule(recent=True),
}

# Which project roles allow each project action (ARCHITECTURE.md §7.5). Mirrored by the
# RLS policies in migration 0008.
PROJECT_ROLES: dict[Action, frozenset[str]] = {
    Action.PROJECT_VIEW: frozenset({"owner", "editor", "viewer"}),
    Action.PROJECT_EDIT: frozenset({"owner", "editor"}),
    Action.PROJECT_MANAGE: frozenset({"owner"}),
    Action.PROJECT_SHARE: frozenset({"owner"}),
    Action.PROJECT_SHARE_LINK: frozenset({"owner", "editor"}),
    Action.ASSET_VIEW: frozenset({"owner", "editor", "viewer"}),
    Action.ASSET_EDIT: frozenset({"owner", "editor"}),
    Action.ASSET_MANAGE: frozenset({"owner"}),
    Action.ASSET_SHARE: frozenset({"owner"}),
    Action.CONTACT_VIEW: frozenset({"owner", "editor", "viewer"}),
    Action.CONTACT_EDIT: frozenset({"owner", "editor"}),
    Action.CONTACT_MANAGE: frozenset({"owner"}),
    Action.CONTACT_SHARE: frozenset({"owner"}),
    Action.TEMPLATE_VIEW: frozenset({"owner", "editor", "viewer"}),
    Action.TEMPLATE_EDIT: frozenset({"owner", "editor"}),
    Action.TEMPLATE_MANAGE: frozenset({"owner"}),
    Action.TEMPLATE_SHARE: frozenset({"owner"}),
}


@dataclass(frozen=True, slots=True)
class ProjectAccess:
    """The principal's role on one project or asset, as read from the database (None = not a
    member)."""

    role: str | None


def require(principal: Principal, action: Action, resource: ProjectAccess | None = None) -> None:
    rule = RULES[action]
    if rule.admin and not principal.is_admin:
        raise NotFoundError("Not found.")
    if rule.verified and not principal.mfa_verified:
        raise ForbiddenError("Second factor required.")
    if rule.recent and not principal.recently_verified():
        raise StepUpRequiredError("Confirm it's you with your second factor to continue.")
    if action in PROJECT_ROLES:
        if resource is None or resource.role is None:
            # Not a member: the project doesn't exist as far as this principal knows.
            raise NotFoundError("Not found.")
        if resource.role not in PROJECT_ROLES[action]:
            raise ForbiddenError("Your role doesn't allow that.")


def allowed(principal: Principal, action: Action, resource: ProjectAccess | None = None) -> bool:
    try:
        require(principal, action, resource)
    except AuthzError:
        return False
    return True


# ------------------------------------------------------------------ share links (ADR 0015)

LinkWhat = Literal[
    "task.read",
    "task.tick",
    "note.read",
    "note.append",
    "list.read",
    "list.tick",
    "file.read",
    "file.add",
]


@dataclass(frozen=True, slots=True)
class LinkGrant:
    """What one share link was given: its boxes and chosen items. A guest has no account;
    these are their only permissions (checked here, and again by the database)."""

    link_id: uuid.UUID
    project_id: uuid.UUID
    tasks_view: str  # none | all | chosen
    tasks_tick: bool
    files_view: bool
    files_add: bool
    lists_tick: bool
    append_note_id: uuid.UUID | None
    task_ids: frozenset[uuid.UUID]
    note_ids: frozenset[uuid.UUID]
    list_ids: frozenset[uuid.UUID]


def link_allows(grant: LinkGrant, what: LinkWhat, item: uuid.UUID | None = None) -> bool:
    """Mirrors app.link_allows (migration 0026)."""
    task_ok = grant.tasks_view == "all" or (grant.tasks_view == "chosen" and item in grant.task_ids)
    rules: dict[str, bool] = {
        "task.read": task_ok,
        "task.tick": grant.tasks_tick and task_ok,
        "note.read": item is not None and (item == grant.append_note_id or item in grant.note_ids),
        "note.append": item is not None and item == grant.append_note_id,
        "list.read": item in grant.list_ids,
        "list.tick": grant.lists_tick and item in grant.list_ids,
        "file.read": grant.files_view,
        "file.add": grant.files_add,
    }
    return rules[what]


def require_link(grant: LinkGrant, what: LinkWhat, item: uuid.UUID | None = None) -> None:
    """Not-found, like anything else the caller can't see."""
    if not link_allows(grant, what, item):
        raise NotFoundError("Not found.")
