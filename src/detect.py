"""Detect blog-post URLs in urls.txt that have not been processed yet.

Writes the new URLs (one per line) to work/new_urls.txt and, when running in
GitHub Actions, sets the step output `has_new` (true/false) via $GITHUB_OUTPUT.

Exit code is always 0; downstream steps gate on `has_new`.
"""
from __future__ import annotations

import os
from pathlib import Path

from common import NEW_URLS_FILE, WORK_DIR, load_state, read_urls, use_utf8_stdout


def find_new_urls() -> list[str]:
    urls = read_urls()
    state = load_state()
    seen = set(state.keys())
    # Preserve urls.txt order; de-duplicate while keeping first occurrence.
    new: list[str] = []
    emitted: set[str] = set()
    for url in urls:
        if url not in seen and url not in emitted:
            new.append(url)
            emitted.add(url)
    return new


def set_github_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def main() -> None:
    use_utf8_stdout()
    new_urls = find_new_urls()

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    Path(NEW_URLS_FILE).write_text(
        "\n".join(new_urls) + ("\n" if new_urls else ""), encoding="utf-8"
    )

    has_new = "true" if new_urls else "false"
    set_github_output("has_new", has_new)
    set_github_output("count", str(len(new_urls)))

    if new_urls:
        print(f"Found {len(new_urls)} new post(s):")
        for url in new_urls:
            print(f"  - {url}")
    else:
        print("No new posts. Nothing to do.")


if __name__ == "__main__":
    main()
