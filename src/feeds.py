"""Discover and parse RSS/Atom feeds for blog sources.

A "source" line in urls.txt is either:
  - a blog root / section page (e.g. https://rastamouse.me/), from which we
    auto-discover the feed and read its posts, or
  - a single post URL (e.g. .../post/2018/native_rdp_pass_the_hash/), handled
    as a one-off and never feed-discovered.

classify() decides which, by URL path shape.
"""
from __future__ import annotations

import datetime as dt
from urllib.parse import urljoin, urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; BlogToPdfBot/1.0; +https://github.com/)"
TIMEOUT = 30

# A one-segment path equal to one of these is treated as a blog section root.
SECTION_NAMES = {"blog", "blogs", "posts", "news", "articles"}

# Common feed locations to try when autodiscovery via <link> fails.
FEED_CANDIDATES = [
    "feed.xml",
    "index.xml",
    "atom.xml",
    "rss.xml",
    "feed/",
    "feed",
    "rss/",
    "rss",
    "feed/index.xml",
    "?feed=rss2",
]


def make_session() -> requests.Session:
    sess = requests.Session()
    sess.headers["User-Agent"] = USER_AGENT
    return sess


def classify(url: str) -> str:
    """Return 'blog' for a site/section root, 'post' for a single article URL."""
    segments = [s for s in urlparse(url).path.split("/") if s]
    if len(segments) == 0:
        return "blog"
    if len(segments) == 1 and segments[0].lower() in SECTION_NAMES:
        return "blog"
    return "post"


def _looks_like_feed(text: str, content_type: str) -> bool:
    head = text.lstrip()[:512].lower()
    return (
        "xml" in content_type.lower()
        or head.startswith("<?xml")
        or "<rss" in head
        or "<feed" in head
    )


def discover_feed(root_url: str, sess: requests.Session) -> str | None:
    """Find a blog's feed URL: the URL itself if it's a feed, else a <link>
    autodiscovery tag, else a guess from common feed paths. None if not found."""
    try:
        resp = sess.get(root_url, timeout=TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException:
        resp = None

    bad_links: list[str] = []
    if resp is not None:
        ctype = resp.headers.get("Content-Type", "")
        if _looks_like_feed(resp.text, ctype) and feedparser.parse(resp.content).entries:
            return root_url
        soup = BeautifulSoup(resp.text, "lxml")
        for link in soup.find_all("link"):
            rel = " ".join(link.get("rel") or []).lower()
            typ = (link.get("type") or "").lower()
            if "alternate" in rel and ("rss" in typ or "atom" in typ) and link.get("href"):
                href = urljoin(root_url, link["href"])
                hint = (href + " " + (link.get("title") or "")).lower()
                # A site often advertises secondary feeds (podcast, comments)
                # before the main post feed. Prefer the main one.
                if "podcast" in hint or "comment" in hint:
                    bad_links.append(href)
                else:
                    return href

    base = root_url if root_url.endswith("/") else root_url + "/"
    for candidate in FEED_CANDIDATES:
        cand_url = urljoin(base, candidate)
        try:
            rr = sess.get(cand_url, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if rr.status_code == 200 and feedparser.parse(rr.content).entries:
            return cand_url

    # No "main" feed found via <link> or common paths — fall back to a
    # secondary advertised feed (podcast/comments) rather than nothing.
    return bad_links[0] if bad_links else None


def _entry_timestamp(entry) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            return dt.datetime(*parsed[:6], tzinfo=dt.timezone.utc)
    return None


def feed_entries(feed_url: str, sess: requests.Session) -> list[dict]:
    """Return feed entries as [{url, title, ts}] sorted newest-first.

    `ts` is a timezone-aware UTC datetime, or None if the feed gives no date.
    """
    try:
        rr = sess.get(feed_url, timeout=TIMEOUT)
        rr.raise_for_status()
        parsed = feedparser.parse(rr.content)
    except requests.RequestException:
        parsed = feedparser.parse(feed_url)

    # Some feeds give relative entry links; resolve them against the feed's own
    # site link (anchored on the feed URL) so they become absolute, fetchable URLs.
    site_link = (getattr(parsed, "feed", {}) or {}).get("link") or ""
    base = urljoin(feed_url, site_link) if site_link else feed_url
    entries: list[dict] = []
    for entry in parsed.entries:
        link = entry.get("link")
        if not link:
            continue
        link = urljoin(base, link)
        entries.append(
            {
                "url": link,
                "title": (entry.get("title") or "").strip(),
                "ts": _entry_timestamp(entry),
            }
        )

    # Sort newest-first only when every entry has a usable timestamp; otherwise
    # trust the feed's own order (conventionally newest-first).
    if entries and all(e["ts"] for e in entries):
        entries.sort(key=lambda e: e["ts"], reverse=True)
    return entries
