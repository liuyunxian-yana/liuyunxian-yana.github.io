#!/usr/bin/env python3
"""Extract JSON payloads that follow ``request=`` in log files.

The script scans the input file incrementally, so it works with large logs
without loading them entirely into memory. Each extracted JSON blob is written
to stdout (or an optional output file) on its own line.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, Iterator, TextIO


MARKER = "request="


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract request JSON payloads from log files."
    )
    parser.add_argument(
        "logfile",
        type=Path,
        help="Path to the log file that contains request=... segments.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        help="Optional path to write the extracted payloads. Defaults to stdout.",
    )
    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Parse each payload as JSON and re-serialize it (orders keys as read).",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=None,
        help="Pretty-print JSON with the given indent (implies --normalize).",
    )
    parser.add_argument(
        "--ensure-ascii",
        action="store_true",
        help="Force ASCII output when normalizing (default keeps Unicode).",
    )
    return parser.parse_args()


def _find_balanced_segment(text: str) -> int | None:
    """Return the length of the first balanced JSON object in ``text``."""
    depth = 0
    in_string = False
    escape = False

    for idx, ch in enumerate(text):
        if escape:
            escape = False
            continue

        if ch == "\\":
            escape = True
            continue

        if ch == '"' and not escape:
            in_string = not in_string
            continue

        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return idx + 1

    return None


def iter_request_payloads(stream: Iterable[str]) -> Iterator[str]:
    """Yield request JSON strings as they are found in the stream."""
    buffer = ""
    waiting_for_more = False

    for chunk in stream:
        buffer += chunk
        search_start = 0

        while True:
            idx = buffer.find(MARKER, search_start)
            if idx == -1:
                waiting_for_more = False
                break

            value_start = idx + len(MARKER)
            while value_start < len(buffer) and buffer[value_start].isspace():
                value_start += 1

            if value_start >= len(buffer):
                waiting_for_more = True
                break

            if buffer[value_start] != "{":
                search_start = value_start
                continue

            segment_length = _find_balanced_segment(buffer[value_start:])
            if segment_length is None:
                waiting_for_more = True
                break

            waiting_for_more = False
            payload = buffer[value_start : value_start + segment_length]
            yield payload
            buffer = buffer[value_start + segment_length :]
            search_start = 0

        if not waiting_for_more and len(buffer) > len(MARKER):
            buffer = buffer[-len(MARKER) :]

    if waiting_for_more:
        print(
            "Warning: file ended while a request payload was incomplete.",
            file=sys.stderr,
        )


def write_payloads(payloads: Iterator[str], dest: TextIO, args: argparse.Namespace):
    normalize = args.normalize or args.indent is not None
    for payload in payloads:
        output_line = payload

        if normalize:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError as exc:
                print(
                    f"Skipping malformed JSON payload: {exc}",
                    file=sys.stderr,
                )
                continue

            output_line = json.dumps(
                data,
                ensure_ascii=args.ensure_ascii,
                indent=args.indent,
            )

        dest.write(output_line)
        if not output_line.endswith("\n"):
            dest.write("\n")


def main() -> None:
    args = parse_args()

    if not args.logfile.exists():
        print(f"Log file '{args.logfile}' does not exist.", file=sys.stderr)
        sys.exit(1)

    try:
        stream = args.logfile.open("r", encoding="utf-8", errors="ignore")
    except OSError as exc:
        print(f"Failed to open log file: {exc}", file=sys.stderr)
        sys.exit(1)

    with stream:
        payloads = iter_request_payloads(stream)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("w", encoding="utf-8") as dest:
                write_payloads(payloads, dest, args)
        else:
            write_payloads(payloads, sys.stdout, args)


if __name__ == "__main__":
    main()
