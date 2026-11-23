"""Command line entry point: ``outputcap`` or ``python -m outputcap``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import DEFAULT_MAX_CHARS, cap


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="outputcap",
        description="Show a bounded preview of a large tool output and keep the whole thing.",
    )
    parser.add_argument("path", nargs="?", type=Path, metavar="FILE", help="default: stdin")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--head", type=int, default=None, help="characters kept from the start")
    parser.add_argument("--tail", type=int, default=None, help="characters kept from the end")
    parser.add_argument(
        "--store",
        type=Path,
        default=None,
        metavar="DIR",
        help="write the full output here and report the path",
    )
    parser.add_argument("--note-only", action="store_true", help="print the summary line only")
    args = parser.parse_args(argv)

    try:
        text = args.path.read_text(encoding="utf-8") if args.path else sys.stdin.read()
    except OSError as error:
        print(f"cannot read {args.path}: {error}", file=sys.stderr)
        return 2

    payload: object = text
    stripped = text.strip()
    if stripped.startswith(("{", "[")):
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            payload = text

    try:
        capped = cap(
            payload,
            max_chars=args.max_chars,
            head=args.head,
            tail=args.tail,
            directory=args.store,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(capped.note if args.note_only else capped.message())
    print(f"{capped.original_chars} chars", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
