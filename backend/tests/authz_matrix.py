"""The authorization matrix (SECURITY.md §7.4): every route, and who may call it.

Classes:
- public        no sign-in needed (health, setup status)
- public_origin no sign-in, but unsafe requests must come from our Origin
- partial       any session, including password-only (second-factor and sign-out flows)
- enroll        partial only while the account has no second factor; otherwise step-up
- verified      a session that completed the second factor
- step_up       verified, with a second factor in the last 5 minutes
- admin         admin with step-up; everyone else gets 404

A route missing from this table fails the tests. When token principals (sync, PAT, OAuth)
arrive, they get their own columns.
"""

MATRIX: dict[tuple[str, str], str] = {
    ("GET", "/healthz"): "public",
    ("GET", "/readyz"): "public",
    ("GET", "/api/v1/setup"): "public",
    ("GET", "/assets/{file_path:path}"): "public",
    ("GET", "/{path:path}"): "public",
    ("POST", "/api/v1/setup"): "public_origin",
    ("POST", "/api/v1/auth/login"): "public_origin",
    ("POST", "/api/v1/auth/passkeys/login/options"): "public_origin",
    ("POST", "/api/v1/auth/passkeys/login"): "public_origin",
    ("POST", "/api/v1/invites/check"): "public_origin",
    ("POST", "/api/v1/invites/accept"): "public_origin",
    ("GET", "/api/v1/auth/session"): "partial",
    ("GET", "/api/v1/auth/mfa/status"): "partial",
    ("POST", "/api/v1/auth/mfa/totp/confirm"): "partial",
    ("POST", "/api/v1/auth/mfa/totp/verify"): "partial",
    ("POST", "/api/v1/auth/mfa/recovery/verify"): "partial",
    ("POST", "/api/v1/auth/passkeys/verify/options"): "partial",
    ("POST", "/api/v1/auth/passkeys/verify"): "partial",
    # Registration re-checks the enroll rule after verifying the credential.
    ("POST", "/api/v1/auth/passkeys/register"): "partial",
    ("POST", "/api/v1/auth/logout"): "partial",
    ("POST", "/api/v1/auth/mfa/totp/enroll"): "enroll",
    ("POST", "/api/v1/auth/passkeys/register/options"): "enroll",
    ("GET", "/api/v1/auth/sessions"): "verified",
    ("DELETE", "/api/v1/auth/sessions/{session_id}"): "verified",
    ("POST", "/api/v1/auth/sessions/revoke-others"): "verified",
    ("GET", "/api/v1/auth/passkeys"): "verified",
    ("GET", "/api/v1/notifications"): "verified",
    ("POST", "/api/v1/notifications/{notification_id}/read"): "verified",
    # Projects and tasks: verified, then the caller's project role (tests/db/test_projects.py)
    ("GET", "/api/v1/projects"): "verified",
    ("POST", "/api/v1/projects"): "verified",
    ("GET", "/api/v1/projects/{project_id}"): "verified",
    ("PATCH", "/api/v1/projects/{project_id}"): "verified",
    ("DELETE", "/api/v1/projects/{project_id}"): "verified",
    ("GET", "/api/v1/projects/{project_id}/tasks"): "verified",
    ("POST", "/api/v1/projects/{project_id}/tasks"): "verified",
    ("PATCH", "/api/v1/tasks/{task_id}"): "verified",
    ("DELETE", "/api/v1/tasks/{task_id}"): "verified",
    # Sharing: verified; project role and step-up checked inside (tests/db/test_sharing.py)
    ("GET", "/api/v1/people"): "verified",
    ("GET", "/api/v1/projects/{project_id}/members"): "verified",
    ("POST", "/api/v1/projects/{project_id}/members"): "verified",
    ("PATCH", "/api/v1/projects/{project_id}/members/{user_id}"): "verified",
    ("DELETE", "/api/v1/projects/{project_id}/members/{user_id}"): "verified",
    ("POST", "/api/v1/auth/password"): "step_up",
    ("POST", "/api/v1/auth/mfa/recovery/regenerate"): "step_up",
    ("DELETE", "/api/v1/auth/passkeys/{passkey_id}"): "step_up",
    ("GET", "/api/v1/admin/users"): "admin",
    ("POST", "/api/v1/admin/users/{user_id}/disabled"): "admin",
    ("POST", "/api/v1/admin/users/{user_id}/admin"): "admin",
    ("POST", "/api/v1/admin/users/{user_id}/reset-second-factor"): "admin",
    ("POST", "/api/v1/admin/invites"): "admin",
    ("GET", "/api/v1/admin/invites"): "admin",
    ("DELETE", "/api/v1/admin/invites/{invite_id}"): "admin",
    ("GET", "/api/v1/admin/plugins"): "admin",
    ("POST", "/api/v1/admin/plugins/{plugin_id}/enabled"): "admin",
}

# Bodies that pass validation, so checks inside services (step-up) are reached.
BODIES: dict[tuple[str, str], object] = {
    ("POST", "/api/v1/auth/password"): {
        "current_password": "definitely not it",
        "new_password": "x" * 20,
    },
    ("POST", "/api/v1/admin/users/{user_id}/disabled"): {"value": False},
    ("POST", "/api/v1/admin/users/{user_id}/admin"): {"value": False},
    ("POST", "/api/v1/admin/invites"): {},
    ("POST", "/api/v1/admin/plugins/{plugin_id}/enabled"): {"value": False},
    ("POST", "/api/v1/projects"): {"title": "Matrix test project"},
    ("POST", "/api/v1/projects/{project_id}/tasks"): {"title": "Matrix test task"},
}

# Expected outcome per principal: "ok" means authorization passed (any status except
# 401/403, and except 404 where 404 is the denial).
EXPECT: dict[str, dict[str, object]] = {
    "public": {
        p: "ok" for p in ("anon", "partial", "stale", "fresh", "admin_stale", "admin_fresh")
    },
    "public_origin": {
        p: "ok" for p in ("anon", "partial", "stale", "fresh", "admin_stale", "admin_fresh")
    },
    "partial": {
        "anon": 401,
        "partial": "ok",
        "stale": "ok",
        "fresh": "ok",
        "admin_stale": "ok",
        "admin_fresh": "ok",
    },
    "enroll": {
        "anon": 401,
        "partial": 403,
        "stale": 403,
        "fresh": "ok",
        "admin_stale": 403,
        "admin_fresh": "ok",
    },
    "verified": {
        "anon": 401,
        "partial": 403,
        "stale": "ok",
        "fresh": "ok",
        "admin_stale": "ok",
        "admin_fresh": "ok",
    },
    "step_up": {
        "anon": 401,
        "partial": 403,
        "stale": 403,
        "fresh": "ok",
        "admin_stale": 403,
        "admin_fresh": "ok",
    },
    "admin": {
        "anon": 401,
        "partial": 404,
        "stale": 404,
        "fresh": 404,
        "admin_stale": 403,
        "admin_fresh": "ok",
    },
}

# Which guard each class must have in its dependency chain (structural check).
GUARDS: dict[str, set[str]] = {
    "public": set(),
    "public_origin": {"require_same_origin"},
    "partial": {"require_session"},
    "enroll": {"require_session"},
    "verified": {"require_verified_session"},
    "step_up": {"require_verified_session"},
    "admin": {"require_admin", "require_admin_network"},
}
SESSION_GUARDS = {"require_session", "require_verified_session", "require_admin"}
