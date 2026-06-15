"""Shared paths, constants and small helpers used across the pipeline."""
from __future__ import annotations

import datetime as dt
import json
import re
import sys
import unicodedata
from pathlib import Path


def use_utf8_stdout() -> None:
    """Force UTF-8 on stdout/stderr so non-ASCII titles/URLs print everywhere
    (notably the Windows console, which defaults to cp1252)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")

# Repo root is the parent of the src/ directory.
ROOT = Path(__file__).resolve().parent.parent

URLS_FILE = ROOT / "urls.txt"
STATE_FILE = ROOT / "state" / "seen.json"
NEW_POSTS_FILE = ROOT / "work" / "new_posts.json"
WORK_DIR = ROOT / "work"
DIST_DIR = ROOT / "dist"
TEMPLATE_FILE = ROOT / "templates" / "post.tex"


def read_urls() -> list[str]:
    """Return the cleaned list of URLs from urls.txt (skips blanks and # comments)."""
    if not URLS_FILE.exists():
        return []
    urls: list[str] = []
    for line in URLS_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def load_state() -> dict:
    """Load state/seen.json, returning {} if missing or empty."""
    if not STATE_FILE.exists():
        return {}
    text = STATE_FILE.read_text(encoding="utf-8-sig").strip()
    if not text:
        return {}
    return json.loads(text)


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def normalize_state(state: dict) -> dict:
    """Ensure the state dict has the expected top-level shape.

    Schema:
      {
        "sources": { <source-url>: {"feed": <feed-url>, "baseline": <iso8601>} },
        "posts":   { <post-url>:   {"title", "slug", "date_processed", "source"} }
      }
    """
    state.setdefault("sources", {})
    state.setdefault("posts", {})
    return state


def parse_iso(value: str | None) -> dt.datetime | None:
    """Parse an ISO-8601 timestamp, returning None if absent or unparseable."""
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(value)
    except ValueError:
        return None


def slugify(value: str, fallback: str = "post") -> str:
    """Turn a title or URL fragment into a filesystem/URL-safe slug."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    value = re.sub(r"[-\s]+", "-", value)
    value = value.strip("-")
    return value or fallback
