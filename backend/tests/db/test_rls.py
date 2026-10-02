"""Row-Level Security and privilege tests (SECURITY.md §7.4, §11)."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.db import health as db_health
from app.db.database import Database
from app.db.migrations import head_revision

pytestmark = [pytest.mark.db, pytest.mark.anyio]

# Tables that hold no user content and are deliberately exempt from RLS.
RLS_EXEMPT = {"alembic_version"}


async def test_rls_enabled_and_forced_on_every_table(db: Database) -> None:
    async with db.anonymous_transaction() as conn:
        rows = (
            await conn.execute(
                text("""
                    SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname IN ('public', 'app') AND c.relkind IN ('r', 'p')
                """)
            )
        ).all()
    tables = {name for name, _, _ in rows} - RLS_EXEMPT
    assert tables, "no tables found; did migrations run?"
    missing = sorted(
        name for name, enabled, forced in rows if name in tables and not (enabled and forced)
    )
    assert missing == [], f"RLS not enabled and forced on: {missing}"


async def test_app_role_owns_nothing_and_cannot_bypass_rls(db: Database) -> None:
    async with db.anonymous_transaction() as conn:
        owned = await conn.scalar(
            text(
                "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
                "WHERE r.rolname = 'planhaven_app'"
            )
        )
        flags = (
            await conn.execute(
                text(
                    "SELECT rolname, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb "
                    "FROM pg_roles WHERE rolname LIKE 'planhaven_%'"
                )
            )
        ).all()
    assert owned == 0
    for name, *privileged in flags:
        assert not any(privileged), name


async def _insert_audit(conn, actor: uuid.UUID | None, action: str = "test") -> None:  # type: ignore[no-untyped-def]
    await conn.execute(
        text(
            "INSERT INTO audit_events (actor_user_id, actor_client, action) "
            "VALUES (:actor, 'test', :action)"
        ),
        {"actor": actor, "action": action},
    )


async def test_no_identity_sees_no_rows(db: Database) -> None:
    user = uuid.uuid7()
    async with db.user_transaction(user) as conn:
        await _insert_audit(conn, user)

    async with db.anonymous_transaction() as conn:
        count = await conn.scalar(
            text("SELECT count(*) FROM audit_events WHERE actor_user_id = :u"), {"u": user}
        )
    assert count == 0


async def test_users_see_only_their_own_audit_events(db: Database) -> None:
    alice, bob = uuid.uuid7(), uuid.uuid7()
    async with db.user_transaction(alice) as conn:
        await _insert_audit(conn, alice, "alice-action")
    async with db.user_transaction(bob) as conn:
        await _insert_audit(conn, bob, "bob-action")

    async with db.user_transaction(bob) as conn:
        actors: set[uuid.UUID] = set(
            (
                await conn.execute(
                    text("SELECT actor_user_id FROM audit_events WHERE actor_user_id IN (:a, :b)"),
                    {"a": alice, "b": bob},
                )
            ).scalars()
        )
    assert actors == {bob}


async def test_cannot_write_audit_events_as_someone_else(db: Database) -> None:
    alice, mallory = uuid.uuid7(), uuid.uuid7()
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.user_transaction(mallory) as conn:
            await _insert_audit(conn, alice)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET action = 'tampered'",
        "DELETE FROM audit_events",
        "TRUNCATE audit_events",
    ],
)
async def test_audit_log_is_append_only(db: Database, statement: str) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with db.system_transaction() as conn:
            await conn.execute(text(statement))


async def test_identity_does_not_leak_between_transactions(db: Database) -> None:
    user = uuid.uuid7()
    async with db.user_transaction(user) as conn:
        assert await conn.scalar(text("SELECT app.current_user_id()")) == user
    for _ in range(10):  # exercise pooled connections
        async with db.anonymous_transaction() as conn:
            assert await conn.scalar(text("SELECT app.current_user_id()")) is None
            assert await conn.scalar(text("SELECT app.is_system()")) is False


async def test_event_outbox_permissions(db: Database) -> None:
    user = uuid.uuid7()
    async with db.user_transaction(user) as conn:
        await conn.execute(
            text("INSERT INTO events (type, user_id) VALUES ('test.created', :u)"), {"u": user}
        )
        # Users can append but not read the outbox.
        visible = await conn.scalar(
            text("SELECT count(*) FROM events WHERE user_id = :u"), {"u": user}
        )
    assert visible == 0

    async with db.system_transaction() as conn:
        event_id = await conn.scalar(text("SELECT id FROM events WHERE user_id = :u"), {"u": user})
        assert event_id is not None
        await conn.execute(
            text("UPDATE events SET processed_at = now() WHERE id = :id"), {"id": event_id}
        )

    with pytest.raises(ProgrammingError, match="permission denied"):
        async with db.system_transaction() as conn:
            await conn.execute(text("UPDATE events SET type = 'tampered'"))


async def test_cannot_append_events_for_another_user(db: Database) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with db.user_transaction(uuid.uuid7()) as conn:
            await conn.execute(
                text("INSERT INTO events (type, user_id) VALUES ('x', :u)"),
                {"u": uuid.uuid7()},
            )


async def test_database_ready_at_head(db: Database) -> None:
    assert head_revision() == "0027"
    assert await db_health.database_ready(db, head_revision()) is True
    assert await db_health.database_ready(db, "not-a-revision") is False


async def test_user_transaction_requires_uuid(db: Database) -> None:
    with pytest.raises(TypeError):
        async with db.user_transaction("' OR 1=1 --"):  # type: ignore[arg-type]
            pass
