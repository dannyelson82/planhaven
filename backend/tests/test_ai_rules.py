"""AI apps' sharing rules without a database (ADR 0020): household members only, without a
fresh second factor only for an AI grant, never owners or the person's own access."""

import uuid

import pytest

from app import authz

ME = uuid.uuid4()
OTHER = uuid.uuid4()
OWNER = authz.ProjectAccess("owner")


def _principal(*, ai_grant: bool) -> authz.Principal:
    return authz.Principal(ME, False, True, None, ai_grant=ai_grant)  # no recent second factor


def test_only_an_ai_grant_skips_step_up_and_only_for_members() -> None:
    with pytest.raises(authz.StepUpRequiredError):
        authz.require(_principal(ai_grant=False), authz.Action.PROJECT_SHARE, OWNER)
    ai = _principal(ai_grant=True)
    authz.require(ai, authz.Action.PROJECT_SHARE, OWNER)
    authz.require(ai, authz.Action.ASSET_SHARE, OWNER)
    for action in (
        authz.Action.PROJECT_SHARE_LINK,
        authz.Action.CONTACT_SHARE,
        authz.Action.TEMPLATE_SHARE,
        authz.Action.TOKEN_CREATE,
        authz.Action.AI_CONNECT,
        authz.Action.CHANGE_SIGN_IN,
    ):
        resource = OWNER if action in authz.PROJECT_ROLES else None
        with pytest.raises(authz.StepUpRequiredError):
            authz.require(ai, action, resource)
    # Still only owners share.
    with pytest.raises(authz.ForbiddenError):
        authz.require(ai, authz.Action.PROJECT_SHARE, authz.ProjectAccess("editor"))


def test_never_owners_or_own_access() -> None:
    ai = _principal(ai_grant=True)
    authz.require_ai_member_change(ai, OTHER, None, "editor")
    authz.require_ai_member_change(ai, OTHER, "viewer", None)
    with pytest.raises(authz.ForbiddenError):
        authz.require_ai_member_change(ai, ME, "owner", "viewer")
    with pytest.raises(authz.ForbiddenError):
        authz.require_ai_member_change(ai, OTHER, None, "owner")
    with pytest.raises(authz.ForbiddenError):
        authz.require_ai_member_change(ai, OTHER, "owner", None)
