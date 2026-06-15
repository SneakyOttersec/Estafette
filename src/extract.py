"""Extract the candidate posts (from work/new_posts.json) into Markdown + images.

For each candidate post:
  - fetch the page and pull out the main article as Markdown (via trafilatura),
  - download every referenced image into work/<slug>/images/,
  - rewrite image references to local relative paths so Pandoc can embed them,
  - write work/<slug>/article.md and a small work/<slug>/meta.json.

After a post is successfully extracted it is recorded in state/seen.json under
"posts", and its blog source's "baseline" is advanced to the newest extracted
post's timestamp. Failures are left unrecorded so they retry next run. A
manifest of this run's posts is written to work/manifest.json for build_pdf.py.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup
from PIL import Image

from common import (
    NEW_POSTS_FILE,
    WORK_DIR,
    load_state,
    normalize_state,
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
# Capture everything inside the parens so URLs containing spaces (e.g. GitHub
# raw links like ".../Pasted image 1.png") aren't truncated at the first space.
MD_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<inside>[^)]+)\)")
# Splits an optional Markdown title:  <url> "title"
_IMG_TITLE_RE = re.compile(r'^(?P<url>.+?)\s+"[^"]*"$')


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
    # Percent-encode spaces so URLs with spaces in the filename fetch correctly.
    abs_url = urljoin(base_url, img_url.strip()).replace(" ", "%20")
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

    digest = hashlib.sha1(abs_url.encode("utf-8")).hexdigest()[:12]
    ext = Path(parsed.path).suffix.lower()
    if not ext or len(ext) > 5:
        ext = mimetypes.guess_extension(
            resp.headers.get("Content-Type", "").split(";")[0].strip()
        ) or ".img"
    images_dir.mkdir(parents=True, exist_ok=True)

    # Convert raster images to grayscale PNG for the e-ink reading look (and a
    # smaller file). Formats Pillow can't decode (e.g. SVG) are kept as-is —
    # WeasyPrint renders those and skips anything it can't read.
    try:
        image = Image.open(io.BytesIO(resp.content))
        if image.mode in ("RGBA", "LA", "P"):
            rgba = image.convert("RGBA")
            white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            image = Image.alpha_composite(white, rgba).convert("L")
        else:
            image = image.convert("L")
        filename = f"{digest}.png"
        image.save(images_dir / filename, "PNG", optimize=True)
        return f"images/{filename}"
    except Exception:  # noqa: BLE001 - non-raster/undecodable -> keep original
        filename = f"{digest}{ext}"
        (images_dir / filename).write_bytes(resp.content)
        return f"images/{filename}"


def localize_images(markdown: str, base_url: str, post_dir: Path) -> str:
    """Download referenced images and rewrite their paths to local files."""
    images_dir = post_dir / "images"
    cache: dict[str, str | None] = {}

    def repl(match: re.Match) -> str:
        inside = match.group("inside").strip()
        title_match = _IMG_TITLE_RE.match(inside)
        url = title_match.group("url").strip() if title_match else inside
        if url not in cache:
            cache[url] = download_image(url, base_url, images_dir)
        local = cache[url]
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


def read_candidates() -> list[dict]:
    if not Path(NEW_POSTS_FILE).exists():
        return []
    text = Path(NEW_POSTS_FILE).read_text(encoding="utf-8-sig").strip()
    return json.loads(text) if text else []


def main() -> None:
    use_utf8_stdout()
    candidates = read_candidates()
    if not candidates:
        print("No candidate posts to extract.")
        MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        MANIFEST_FILE.write_text("[]\n", encoding="utf-8")
        return

    state = normalize_state(load_state())
    manifest: list[dict] = []
    used_slugs: set[str] = set()
    # Highest extracted-post timestamp per blog source, to advance baselines.
    source_max_ts: dict[str, str] = {}

    for cand in candidates:
        url = cand["url"]
        print(f"Extracting {url}")
        last_segment = urlparse(url).path.strip("/").rsplit("/", 1)[-1]
        base_slug = slugify(last_segment or urlparse(url).netloc)
        slug = base_slug
        i = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{i}"
            i += 1
        used_slugs.add(slug)

        meta = extract_one(url, WORK_DIR / slug)
        if meta is None:
            # Do not record failures — retry on the next run.
            continue
        meta["tag"] = cand.get("tag", "general")
        meta["subs"] = cand.get("subs", [])
        manifest.append(meta)
        state["posts"][url] = {
            "title": meta["title"],
            "slug": meta["slug"],
            "date_processed": meta["date_processed"],
            "source": cand.get("source"),
        }

        if cand.get("source_type") == "blog":
            source = cand["source"]
            srec = state["sources"].setdefault(source, {})
            if cand.get("feed"):
                srec["feed"] = cand["feed"]
            ts = cand.get("ts")
            if ts and ts > source_max_ts.get(source, ""):
                source_max_ts[source] = ts
        print(f"  -> {meta['title']!r} ({slug})")

    # Advance each blog's baseline to the newest post we actually extracted.
    for source, ts in source_max_ts.items():
        srec = state["sources"].setdefault(source, {})
        if ts > (srec.get("baseline") or ""):
            srec["baseline"] = ts

    save_state(state)
    MANIFEST_FILE.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Extracted {len(manifest)} of {len(candidates)} candidate post(s).")


if __name__ == "__main__":
    main()
