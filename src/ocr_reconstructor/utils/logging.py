from __future__ import annotations

import sys

_VERBOSE = False


def configure(verbose: bool = False) -> None:
    global _VERBOSE
    _VERBOSE = verbose


def is_verbose() -> bool:
    return _VERBOSE


def _emit(tag: str, message: str, stream=None) -> None:
    print(f"[{tag}] {message}", file=stream or sys.stdout, flush=True)


def info(stage: str, message: str) -> None:
    _emit(stage, message)


def warn(stage: str, message: str) -> None:
    _emit(stage, f"WARNING: {message}")


def debug(stage: str, message: str) -> None:
    if _VERBOSE:
        _emit(stage, f"DEBUG: {message}")


def error(stage: str, message: str) -> None:
    _emit("ERROR", f"[{stage}] {message}", stream=sys.stderr)


def progress(stage: str, index: int, total: int, message: str) -> None:
    _emit(stage, f"{index}/{total} {message}")
