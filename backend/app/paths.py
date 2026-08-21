"""Path containment, in one place.

Used by the media routes, the SPA fallback and the file-deleting helpers -- a
second, subtly different implementation of this check is how directory
traversal gets in.
"""
from __future__ import annotations

from pathlib import Path


def is_within(path: Path, root: Path) -> bool:
    """True if ``path`` is ``root`` itself or sits underneath it.

    Compares resolved path *components*: a string prefix test would accept a
    sibling directory that merely starts with the same characters
    (``/srv/frontend-secrets`` vs ``/srv/frontend``).
    """
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def safe_join(root: Path, relative: str) -> Path | None:
    """Resolve ``relative`` (straight off a URL) under ``root``, or None.

    ``Path.__truediv__`` neither normalises ``..`` nor protects against an
    absolute right-hand side -- ``Path("/srv") / "/etc/passwd"`` is
    ``/etc/passwd`` -- so both are handled before the containment check.
    """
    candidate = (root / relative.lstrip("/")).resolve()
    return candidate if is_within(candidate, root) else None
