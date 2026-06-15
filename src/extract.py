"""Extract the new posts (from work/new_urls.txt) into local Markdown + images.

For each URL:
  - fetch the page and pull out the main article as Markdown (via trafilatura),
  - download every referenced image into work/<slug>/images/,
  - rewrite image references to local relative paths so Pandoc can embed them,
  - write work/<slug>/article.md and a small work/<slug>/meta.json.

Successfully-extracted posts are recorded in state/seen.json so they are not
processed again. A manifest of this run's posts is written to
work/manifest.json for build_pdf.py to consume.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

from common import (
    NEW_URLS_FILE,
    WORK_DIR,
    load_state,
    save_state,
    slugify,
    use_utf8_stdout,
)

USER_AGENT = (
    "Mozilla/5.0 (compatible; BlogToPdfBot/1.0; "
    "+https://github.com/) requests"
)
REQUEST_TIMEOUT = 30
MANIFEST_FILE = WORK_DIR / "manifest.json"

# Matches Markdown images:  ![alt](url "title")
MD_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<url>[^)\s]+)(?P<rest>\s+[^)]*)?\)")


def fetch_html(url: str) -> str | None:
    """Download raw HTML for a URL, returning None on failure."""
    try:
        resp = requests.get(
            url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as exc:
        print(f"  ! failed to fetch {url}: {exc}")
        return None


def extract_title(html: str, url: str) -> str:
    meta = trafilatura.extract_metadata(html)
    if meta and meta.title:
        return meta.title.strip()
    soup = BeautifulSoup(html, "lxml")
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    if soup.h1:
        return soup.h1.get_text(strip=True)
    # Fall back to the last meaningful path segment.
    path = urlparse(url).path.rstrip("/")
    return path.rsplit("/", 1)[-1].replace("-", " ").title() or url


def download_image(img_url: str, base_url: str, images_dir: Path) -> str | None:
    """Download an image, returning the local relative path or None on failure."""
    abs_url = urljoin(base_url, img_url)
    parsed = urlparse(abs_url)
    if parsed.scheme not in ("http", "https"):
        return None  # skip data: URIs and other schemes
    try:
        resp = requests.get(
            abs_url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"    ! image download failed {abs_url}: {exc}")
        return None

    # Build a stable filename from the URL hash + a sensible extension.
    digest = hashlib.sha1(abs_url.encode("utf-8")).hexdigest()[:12]
    ext = Path(parsed.path).suffix.lower()
    if not ext or len(ext) > 5:
        ext = mimetypes.guess_extension(
            resp.headers.get("Content-Type", "").split(";")[0].strip()
        ) or ".img"
    images_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{digest}{ext}"
    (images_dir / filename).write_bytes(resp.content)
    return f"images/{filename}"


def localize_images(markdown: str, base_url: str, post_dir: Path) -> str:
    """Download referenced images and rewrite their paths to local files."""
    images_dir = post_dir / "images"
    cache: dict[str, str | None] = {}

    def repl(match: re.Match) -> str:
        original = match.group("url")
        if original not in cache:
            cache[original] = download_image(original, base_url, images_dir)
        local = cache[original]
        if not local:
            return match.group(0)  # leave original on failure
        alt = match.group("alt")
        return f"![{alt}]({local})"

    return MD_IMAGE_RE.sub(repl, markdown)


def extract_one(url: str, post_dir: Path) -> dict | None:
    """Extract a single URL into post_dir. Returns metadata dict or None."""
    html = fetch_html(url)
    if html is None:
        return None

    markdown = trafilatura.extract(
        html,
        url=url,
        output_format="markdown",
        include_images=True,
        include_links=True,
        favor_precision=True,
    )
    if not markdown or not markdown.strip():
        print(f"  ! no extractable content for {url}")
        return None

    title = extract_title(html, url)
    markdown = localize_images(markdown, url, post_dir)

    post_dir.mkdir(parents=True, exist_ok=True)
    (post_dir / "article.md").write_text(markdown, encoding="utf-8")

    meta = {
        "url": url,
        "title": title,
        "slug": post_dir.name,
        "date_processed": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d"),
    }
    (post_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return meta


def read_new_urls() -> list[str]:
    if not Path(NEW_URLS_FILE).exists():
        return []
    return [
        line.strip()
        for line in Path(NEW_URLS_FILE).read_text(encoding="utf-8-sig").splitlines()
        if line.strip()
    ]


def main() -> None:
    use_utf8_stdout()
    urls = read_new_urls()
    if not urls:
        print("No new URLs to extract.")
        MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_FILE.write_text("[]\n", encoding="utf-8")
        return

    state = load_state()
    manifest: list[dict] = []
    used_slugs: set[str] = set()

    for url in urls:
        print(f"Extracting {url}")
        base_slug = slugify(urlparse(url).path.rsplit("/", 1)[-1] or urlparse(url).netloc)
        slug = base_slug
        i = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{i}"
            i += 1
        used_slugs.add(slug)

        meta = extract_one(url, WORK_DIR / slug)
        if meta is None:
            # Do not record failures in seen.json — retry on the next run.
            continue
        manifest.append(meta)
        state[url] = {
            "title": meta["title"],
            "slug": meta["slug"],
            "date_processed": meta["date_processed"],
        }
        print(f"  -> {meta['title']!r} ({slug})")

    save_state(state)
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Extracted {len(manifest)} of {len(urls)} new post(s).")


if __name__ == "__main__":
    main()
