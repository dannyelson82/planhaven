"""Experimental features (ADR 0012; owner request, 2026-09-28).

Features still in development are listed in REGISTRY. None is on by default:
1. an admin turns experimental features on for this PlanHaven (the master switch), then makes
   each feature available (step-up, audited);
2. each person opts in to the available ones they want.
Nobody gets an experiment they didn't choose, and turning the master switch off stops them all.
A feature leaves the registry (graduates) only with tests, a SECURITY.md entry and the
maintainer's sign-off.
"""

import json
from dataclasses import dataclass

from app import authz
from app.db import auth as audit
from app.db import experiments as store
from app.db.database import Database
from app.services.admin import AdminContext, require_admin
from app.services.auth import CurrentSession

MASTER = "experimental"


@dataclass(frozen=True, slots=True)
class Experiment:
    title: str
    description: str
    risks: str


# Features in development, by name (lowercase, dots allowed). Empty until the first one lands.
REGISTRY: dict[str, Experiment] = {}


@dataclass(frozen=True, slots=True)
class FeatureState:
    name: str
    experiment: Experiment
    available: bool
    opted_in: bool


class UnknownExperimentError(Exception):
    """Not an experimental feature (message is safe to show)."""


async def admin_view(db: Database, ctx: AdminContext) -> tuple[bool, list[FeatureState]]:
    require_admin(ctx.session)
    async with db.system_transaction() as conn:
        states = await store.availability(conn)
    return states.get(MASTER, False), [
        FeatureState(name, e, states.get(name, False), False) for name, e in REGISTRY.items()
    ]


async def admin_set(
    db: Database, ctx: AdminContext, enabled: bool, available: dict[str, bool]
) -> tuple[bool, list[FeatureState]]:
    require_admin(ctx.session)
    unknown = set(available) - set(REGISTRY)
    if unknown:
        raise UnknownExperimentError("That isn't an experimental feature.")
    async with db.system_transaction() as conn:
        await store.set_available(conn, MASTER, enabled, ctx.session.user.id)
        for name, on in available.items():
            await store.set_available(conn, name, on, ctx.session.user.id)
        await audit.record_audit(
            conn,
            action="experiments.changed",
            actor_user_id=ctx.session.user.id,
            ip=ctx.ip,
            details=json.dumps({"enabled": enabled, "available": available}),
        )
    return await admin_view(db, ctx)


async def for_user(db: Database, session: CurrentSession) -> tuple[bool, list[FeatureState]]:
    """Whether experiments are on, and the features this person may opt in to."""
    authz.require(session.principal, authz.Action.USE_APP)
    async with db.system_transaction() as conn:
        states = await store.availability(conn)
    enabled = states.get(MASTER, False)
    async with db.user_transaction(session.user.id) as conn:
        mine = await store.optins(conn)
    features = [
        FeatureState(name, e, True, name in mine)
        for name, e in REGISTRY.items()
        if enabled and states.get(name, False)
    ]
    return enabled, features


async def opt_in(db: Database, session: CurrentSession, name: str, on: bool) -> None:
    _, features = await for_user(db, session)
    if name not in {f.name for f in features}:
        raise UnknownExperimentError("That experimental feature isn't available.")
    async with db.user_transaction(session.user.id) as conn:
        await store.set_optin(conn, name, on)


async def is_on(db: Database, session: CurrentSession, name: str) -> bool:
    """For code behind an experimental feature: available, and this person opted in."""
    _, features = await for_user(db, session)
    return any(f.name == name and f.opted_in for f in features)
