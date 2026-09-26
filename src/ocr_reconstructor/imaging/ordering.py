from __future__ import annotations

import re
from typing import Iterable

_DIGITS = re.compile(r"(\d+)")


def natural_key(value: str) -> tuple:
    parts = [part for part in _DIGITS.split(value) if part]
    return tuple(
        (1, int(part)) if part.isdigit() else (0, part.casefold()) for part in parts
    )


def sort_relative_paths(paths: Iterable[str]) -> list[str]:
    return sorted(paths, key=natural_key)
