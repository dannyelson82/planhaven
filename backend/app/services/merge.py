"""Saving over a newer copy when it's safe (owner decision, 2026-10-02: "merge when safe").

A save carries the version it started from. If someone else (or the same person on another
device) saved in between, the save is still applied when none of the fields it changes were
touched meanwhile: the client also sends `base`, the values those fields had when it started,
and they must all still be the current values. Otherwise it's a conflict, and the person
chooses what to keep.
"""

from collections.abc import Collection, Mapping
from typing import Any


def unchanged_since(
    current: Mapping[str, Any],
    fields: Mapping[str, Any],
    base: Mapping[str, Any] | None,
    *,
    ignore: Collection[str] = (),
) -> bool:
    """True when every field being saved still has the value the client started from."""
    if base is None:
        return False
    for name in fields:
        if name in ignore:
            continue
        if name not in base or current.get(name) != base[name]:
            return False
    return True
