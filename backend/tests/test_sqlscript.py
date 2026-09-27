from app.db.schema_migrations.sqlscript import split_statements


def test_splits_plain_statements() -> None:
    assert split_statements("SELECT 1;\nSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_keeps_dollar_quoted_bodies_whole() -> None:
    sql = "CREATE FUNCTION f() AS $$ BEGIN a; b; END $$; SELECT 1;"
    assert split_statements(sql) == ["CREATE FUNCTION f() AS $$ BEGIN a; b; END $$", "SELECT 1"]


def test_keeps_semicolons_in_strings() -> None:
    sql = "SELECT ';'; SELECT 'it''s; fine'; SELECT $tag$ ; $tag$;"
    assert split_statements(sql) == ["SELECT ';'", "SELECT 'it''s; fine'", "SELECT $tag$ ; $tag$"]


def test_ignores_semicolons_in_comments() -> None:
    sql = "-- first; not a split\nSELECT 1; -- trailing; comment\nSELECT 2;"
    assert split_statements(sql) == [
        "-- first; not a split\nSELECT 1",
        "-- trailing; comment\nSELECT 2",
    ]
