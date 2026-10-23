"""Record exceptions that a module deliberately survives.

Several paths must keep going when one probe fails: a model that will not
answer a tag listing, a log line that cannot be parsed. Swallowing those
silently made the cause invisible. ``note`` keeps the survival and leaves a
private, one-line trace in ``data/logs/swallowed.log``.
"""

from __future__ import annotations

import time

from .config import LOCAL_AI_ROOT
from .safefile import ensure_private_dir, open_private

LOG_NAME = "swallowed.log"
_MAX_MESSAGE = 200


def note(where: str, exc: BaseException) -> None:
    """Append one line describing ``exc`` raised and survived in ``where``."""
    try:
        folder = ensure_private_dir(LOCAL_AI_ROOT / "data" / "logs")
        message = str(exc).replace("\n", " ")[:_MAX_MESSAGE]
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open_private(folder / LOG_NAME, "a") as handle:
            handle.write(f"{stamp} {where} {type(exc).__name__}: {message}\n")
    except OSError:
        return
