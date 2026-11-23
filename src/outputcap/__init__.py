"""Cap and offload large tool outputs so they cannot flood an agent's context.

A tool that returns a 400 kB JSON blob, a full web page or a 2 000-line log is not
returning an answer, it is returning the haystack. The model pays for every character and
loses the thread; the run then fails on a context limit that had nothing to do with the
question.

    >>> from outputcap import cap
    >>> capped = cap({"rows": list(range(5000))}, max_chars=200)
    >>> capped.truncated
    True
    >>> capped.original_chars > 200
    True
    >>> "truncated" in capped.note
    True

The full value is kept in memory (and, if you give it a directory, on disk), so a follow-up
call can read the part that matters. Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["Capped", "cap", "read_handle", "slices"]

__version__ = "0.1.0"

DEFAULT_MAX_CHARS = 4000


@dataclass
class Capped:
    """A tool result reduced to a preview, with the full value available on request."""

    text: str
    truncated: bool
    original_chars: int
    handle: Path | None = None
    full: Any = field(default=None, repr=False)
    head_chars: int = 0
    tail_chars: int = 0

    @property
    def note(self) -> str:
        """One line to append to the preview, or an empty string when nothing was cut."""
        if not self.truncated:
            return ""
        where = f"; full value at {self.handle}" if self.handle else ""
        return (
            f"[output truncated: {self.original_chars} chars, showing the first "
            f"{self.head_chars} and the last {self.tail_chars}{where}]"
        )

    def message(self) -> str:
        """The preview with the note appended — what a tool message should contain."""
        return self.text if not self.note else f"{self.text}\n\n{self.note}"

    def read(self, start: int = 0, end: int | None = None) -> str:
        """A slice of the full text, so a follow-up call can ask for the rest.

        Raises :class:`FileNotFoundError` when the value was stored and the file is gone:
        a silent empty answer is worse than a loud one.
        """
        return self._full_text()[start:end]

    def _full_text(self) -> str:
        if self.handle is not None:
            if not self.handle.exists():
                raise FileNotFoundError(f"stored output is gone: {self.handle}")
            return self.handle.read_text(encoding="utf-8")
        return self.text if not self.truncated else _as_text(self.full)


def _as_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    try:
        return json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return repr(value)


def cap(
    value: Any,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    head: int | None = None,
    tail: int | None = None,
    directory: str | Path | None = None,
    name: str | None = None,
) -> Capped:
    """Reduce ``value`` to at most ``max_chars`` characters.

    ``head`` and ``tail`` split the budget (default: 80% head, the rest tail, so an error
    at the end of a log stays visible). With ``directory``, the full text is written to a
    file and its path is reported in the note.
    """
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    text = _as_text(value)
    if head is None and tail is None:
        head = max(int(max_chars * 0.8), 1)
        tail = max(max_chars - head, 0)
    elif head is None:
        head = max(max_chars - (tail or 0), 0)
    elif tail is None:
        tail = max(max_chars - head, 0)
    if max_chars < 16:
        head, tail = max_chars, 0
    if len(text) <= max_chars:
        return Capped(text=text, truncated=False, original_chars=len(text), full=value)
    if head + tail > max_chars:
        tail = max(max_chars - head, 0)
    preview = text[:head]
    if tail:
        preview += "\n...\n" + text[-tail:]
    handle: Path | None = None
    if directory is not None:
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        filename = name or f"output-{uuid.uuid4().hex[:8]}.txt"
        handle = target / filename
        handle.write_text(text, encoding="utf-8", newline="")
    return Capped(
        text=preview,
        truncated=True,
        original_chars=len(text),
        handle=handle,
        full=None if handle else value,
        head_chars=head,
        tail_chars=tail,
    )


def read_handle(path: str | Path, start: int = 0, end: int | None = None) -> str:
    """Read a slice of a stored output, for a follow-up tool call."""
    return Path(path).read_text(encoding="utf-8")[start:end]


def slices(text: str, size: int, *, overlap: int = 0) -> list[tuple[int, int]]:
    """Split ``text`` into ranges of ``size`` characters, with an optional overlap.

    This is what a follow-up tool exposes: ``read(start, end)`` plus the ranges to ask for.
    """
    if size < 1:
        raise ValueError("size must be at least 1")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be between 0 and size - 1")
    if not text:
        return []
    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        ranges.append((start, end))
        if end == len(text):
            break
        start = end - overlap
    return ranges

