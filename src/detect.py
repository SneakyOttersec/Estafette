"""Decide which blog posts to turn into PDFs on this run.

For each source line in urls.txt:
  - 'post' sources (single article URLs) are candidates if never processed.
  - 'blog' sources have their feed discovered (and cached in state). Then:
      * first time we see the blog (no baseline) -> take only the LATEST post,
        which also establishes the baseline once it's extracted;
      * afterwards -> take every post newer than the stored baseline.

Candidates are written to work/new_posts.json for extract.py. Discovered feed
URLs are cached back into state immediately (cheap and idempotent). The
per-blog baseline and processed-post records are advanced by extract.py only
after a post is successfully extracted, so failures are retried.

Sets GitHub Actions step outputs has_new (true/false) and count.
"""
from __future__ import annotations

import json
import os

import feeds
from common import (
    NEW_POSTS_FILE,
    WORK_DIR,
    load_state,
    normalize_state,
    parse_iso,
    parse_source_line,
    read_urls,
    save_state,
    use_utf8_stdout,
)


def _iso(ts) -> str | None:
    return ts.isoformat() if ts else None


def find_candidates(state: dict, sess) -> list[dict]:
    posts_seen = state["posts"]
    sources_state = state["sources"]
    candidates: list[dict] = []

    for line in read_urls():
        parsed = parse_source_line(line)
        src, feed_override = parsed["url"], parsed["feed"]
        tags = {"tag": parsed["tag"], "subs": parsed["subs"]}

        if not feed_override and feeds.classify(src) == "post":
            if src in posts_seen:
                print(f"[post] already processed: {src}")
                continue
            print(f"[post] NEW single post: {src}")
            candidates.append(
                {"url": src, "title": None, "source": src,
                 "source_type": "post", "feed": None, "ts": None, **tags}
            )
            continue

        # Blog source: use the pinned feed, the cached one, or auto-discover.
        srec = sources_state.setdefault(src, {})
        feed = feed_override or srec.get("feed") or feeds.discover_feed(src, sess)
        if not feed:
            print(f"[blog] !! no feed found: {src}")
            continue
        srec["feed"] = feed

        entries = feeds.feed_entries(feed, sess)
        if not entries:
            print(f"[blog] !! feed empty: {feed}")
            continue

        baseline = parse_iso(srec.get("baseline"))
        if baseline is None:
            # First time: take only the latest post.
            latest = entries[0]
            if latest["url"] in posts_seen:
                print(f"[blog] first run, latest already seen: {src}")
                continue
            print(f"[blog] first run, latest post: {latest['url']}")
            candidates.append(
                {"url": latest["url"], "title": latest["title"], "source": src,
                 "source_type": "blog", "feed": feed, "ts": _iso(latest["ts"]), **tags}
            )
            continue

        # Subsequent runs: every post newer than the baseline.
        new_for_blog = 0
        for i, entry in enumerate(entries):
            if entry["url"] in posts_seen:
                continue
            if entry["ts"] is not None:
                if entry["ts"] <= baseline:
                    continue
            elif i != 0:
                # No date on this entry: only trust the newest one to avoid
                # re-ingesting an entire backlog from an undated feed.
                continue
            candidates.append(
                {"url": entry["url"], "title": entry["title"], "source": src,
                 "source_type": "blog", "feed": feed, "ts": _iso(entry["ts"]), **tags}
            )
            new_for_blog += 1
        print(f"[blog] {new_for_blog} new post(s) since baseline: {src}")

    return candidates


def set_github_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def main() -> None:
    use_utf8_stdout()
    state = normalize_state(load_state())
    sess = feeds.make_session()

    candidates = find_candidates(state, sess)

    WORK_DIR.mkdir(parents=True, exist_ok=True)
    NEW_POSTS_FILE.write_text(
        json.dumps(candidates, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    # Persist any feed URLs discovered this run (baselines come later).
    save_state(state)

    set_github_output("has_new", "true" if candidates else "false")
    set_github_output("count", str(len(candidates)))
    print(f"\n{len(candidates)} post(s) to extract this run.")


if __name__ == "__main__":
    main()
