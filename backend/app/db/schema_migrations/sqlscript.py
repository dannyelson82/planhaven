"""Helpers for migrations written in SQL."""

import re

from alembic import op

_DOLLAR = re.compile(r"\$[A-Za-z_]*\$")


def split_statements(sql: str) -> list[str]:
    """Split on semicolons, except inside dollar-quoted bodies ($$ ... $$), '...' strings
    (a doubled '' inside a string toggles twice, so it stays inside) and -- comments."""
    statements: list[str] = []
    current: list[str] = []
    quote: str | None = None
    in_string = False
    i = 0
    while i < len(sql):
        char = sql[i]
        if quote is None and char == "'":
            in_string = not in_string
        if in_string:
            current.append(char)
            i += 1
            continue
        if quote is None and sql.startswith("--", i):
            end = sql.find("\n", i)
            end = len(sql) if end == -1 else end
            current.append(sql[i:end])
            i = end
            continue
        match = _DOLLAR.match(sql, i)
        if match:
            tag = match.group()
            if quote is None:
                quote = tag
            elif tag == quote:
                quote = None
            current.append(tag)
            i = match.end()
            continue
        if char == ";" and quote is None:
            statements.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        i += 1
    statements.append("".join(current).strip())
    return [s for s in statements if s]


def execute_script(sql: str) -> None:
    """Run statements one at a time (asyncpg executes a single statement per call)."""
    for statement in split_statements(sql):
        op.execute(statement)
