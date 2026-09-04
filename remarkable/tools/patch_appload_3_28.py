#!/usr/bin/env python3
"""Replace only AppLoad 0.5.3's embedded, pre-3.28 QMLDiff regions."""
from __future__ import annotations

import argparse
from pathlib import Path


MAINVIEW_START = b"AFFECT [[2328484894988065446]]"
SIDEBAR_START = b"AFFECT [[4911547370760691430]]"
NEXT_SECTION = b"; Reach within the appload files themselves:"


def compact(raw: bytes) -> bytes:
    lines = (line.lstrip() for line in raw.splitlines())
    return b"\n".join(line for line in lines if line) + b"\n"


def replace(binary: bytearray, start_marker: bytes, end_marker: bytes, content: bytes, label: str) -> None:
    start = binary.find(start_marker)
    end = binary.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit(f"AppLoad 0.5.3 {label} region was not found")
    if len(content) > end - start:
        raise SystemExit(f"3.28 {label} patch exceeds its fixed ELF region")
    binary[start:end] = content + b" " * (end - start - len(content))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--compat", type=Path, default=Path(__file__).resolve().parents[1] / "compat")
    args = parser.parse_args()
    original = args.source.read_bytes()
    binary = bytearray(original)
    replace(binary, MAINVIEW_START, SIDEBAR_START, (args.compat / "appload-mainview-3.28.qmd").read_bytes(), "MainView")
    replace(binary, SIDEBAR_START, NEXT_SECTION, compact((args.compat / "appload-sidebar-3.28.qmd").read_bytes()), "Sidebar")
    if len(binary) != len(original):
        raise SystemExit("ELF size changed")
    args.destination.write_bytes(binary)
    args.destination.chmod(0o755)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
