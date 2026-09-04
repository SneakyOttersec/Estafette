"""Build the immutable, offline Estafette feed for reMarkable tablets.

This publisher deliberately owns its state and snapshots.  It never imports the
weekly detector's state helpers and never writes ``state/seen.json``.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
import requests
import trafilatura
from PIL import Image, ImageOps

import feeds
from common import parse_source_line, read_urls, slugify, use_utf8_stdout
from extract import (
    _IMG_TITLE_RE,
    MD_IMAGE_RE,
    extract_title,
    prepare_html,
    restore_inline_assets,
)

SCHEMA_VERSION = 1
WORKERS = 12
REQUEST_TIMEOUT = 15
ARTICLE_LIMIT = 100
MAX_SNAPSHOT_BYTES = 480 * 1024 * 1024
MAX_JSON_BYTES = 10 * 1024 * 1024
MAX_IMAGE_BYTES = 40 * 1024 * 1024
MAX_IMAGE_EDGE = 1400
DEFAULT_ORIGIN = "https://sneakyottersec.github.io/Estafette"
TABLET_EXCLUDED_SOURCE_HOSTS = frozenset({"portswigger.net"})
USER_AGENT = (
    "EstafetteRemarkablePublisher/1.0 (+https://github.com/SneakyOttersec/Estafette)"
)
STATE_MEMBER = "publisher-state.json"
CURRENT_PREFIX = "current"
PREVIOUS_PREFIX = "previous"
SAFE_BLOCK_TYPES = {
    "heading",
    "paragraph",
    "list",
    "code",
    "quote",
    "image",
    "table",
    "divider",
}


class PublicationError(RuntimeError):
    """The new snapshot is invalid and must not replace the published one."""


@dataclass(frozen=True)
class SourceResult:
    source: str
    feed: str | None
    entries: list[dict[str, Any]]
    ok: bool
    error: str = ""


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def isoformat(value: dt.datetime) -> str:
    return (
        value.astimezone(dt.timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def parse_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def canonical_url(value: str) -> str:
    """Normalize URL identity without changing meaningful path/query content."""
    parsed = urlparse(value.strip())
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    if parsed.port and not (
        (scheme == "https" and parsed.port == 443)
        or (scheme == "http" and parsed.port == 80)
    ):
        host = f"{host}:{parsed.port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    # Fragments are presentation-only.  Preserve the query because some feeds
    # use it as the stable article identifier.
    return urlunparse((scheme, host, path, "", parsed.query, ""))


def stable_id(url: str) -> str:
    readable = slugify(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1], "article")[
        :48
    ]
    digest = hashlib.sha256(canonical_url(url).encode()).hexdigest()[:16]
    return f"{readable}-{digest}"


def source_name(source: str) -> str:
    host = (urlparse(source).hostname or source).lower()
    return host.removeprefix("www.")


def tablet_source_lines(lines: Iterable[str]) -> list[str]:
    """Apply reader-only source exclusions without changing the PDF pipeline."""
    included: list[str] = []
    for line in lines:
        source = parse_source_line(line)["url"]
        host = (urlparse(source).hostname or "").lower()
        if any(
            host == excluded or host.endswith(f".{excluded}")
            for excluded in TABLET_EXCLUDED_SOURCE_HOSTS
        ):
            continue
        included.append(line)
    return included


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, text/html;q=0.8, */*;q=0.5",
        }
    )
    return session


def _entry_time(entry: Any) -> dt.datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            return dt.datetime(*parsed[:6], tzinfo=dt.timezone.utc)
    return None


def fetch_source(line: str) -> SourceResult:
    parsed_source = parse_source_line(line)
    source = parsed_source["url"]
    session = make_session()
    try:
        if not parsed_source["feed"] and feeds.classify(source) == "post":
            return SourceResult(
                source,
                None,
                [
                    {
                        "url": canonical_url(source),
                        "title": "",
                        "published_at": None,
                        "category": parsed_source["tag"],
                        "topics": parsed_source["subs"],
                    }
                ],
                True,
            )
        feed_url = parsed_source["feed"] or feeds.discover_feed(
            source, session, timeout=REQUEST_TIMEOUT
        )
        if not feed_url:
            raise PublicationError("no feed discovered")
        response = session.get(feed_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        if len(response.content) > MAX_JSON_BYTES:
            raise PublicationError("feed response exceeds 10 MB")
        document = feedparser.parse(response.content)
        if document.bozo and not document.entries:
            raise PublicationError(f"invalid feed: {document.bozo_exception}")
        site_link = (document.feed or {}).get("link") or ""
        base = urljoin(feed_url, site_link) if site_link else feed_url
        entries: list[dict[str, Any]] = []
        for item in document.entries:
            link = item.get("link")
            if not link:
                continue
            absolute = canonical_url(urljoin(base, link))
            if urlparse(absolute).scheme not in {"http", "https"}:
                continue
            stamp = _entry_time(item)
            entries.append(
                {
                    "url": absolute,
                    "title": (item.get("title") or "").strip(),
                    "published_at": isoformat(stamp) if stamp else None,
                    "category": parsed_source["tag"],
                    "topics": parsed_source["subs"],
                }
            )
        if not entries:
            raise PublicationError("feed contains no usable entries")
        return SourceResult(source, feed_url, entries, True)
    except Exception as exc:  # noqa: BLE001 - failure is isolated per source
        return SourceResult(source, parsed_source["feed"], [], False, str(exc))
    finally:
        session.close()


def refresh_sources(
    lines: Iterable[str],
    previous_state: dict[str, Any],
    now: dt.datetime,
    fetcher: Callable[[str], SourceResult] = fetch_source,
) -> tuple[dict[str, Any], list[str]]:
    """Fetch every source concurrently and retain stale entries on failure."""
    prior_sources = previous_state.get("sources", {})
    refreshed: dict[str, Any] = {}
    warnings: list[str] = []
    lines = list(lines)
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetcher, line): line for line in lines}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            prior = prior_sources.get(result.source, {})
            if not result.ok:
                if prior.get("entries"):
                    refreshed[result.source] = prior
                    warnings.append(
                        f"{result.source}: {result.error}; retained previous entries"
                    )
                else:
                    warnings.append(
                        f"{result.source}: {result.error}; no previous entries"
                    )
                continue
            prior_by_url = {
                canonical_url(item["url"]): item for item in prior.get("entries", [])
            }
            entries = []
            for item in result.entries:
                previous = prior_by_url.get(item["url"], {})
                entries.append(
                    {
                        **item,
                        "first_seen_at": previous.get("first_seen_at")
                        or isoformat(now),
                    }
                )
            refreshed[result.source] = {
                "feed": result.feed,
                "last_success_at": isoformat(now),
                "entries": entries,
            }
    return {"schema_version": SCHEMA_VERSION, "sources": refreshed}, sorted(warnings)


def select_newest(
    state: dict[str, Any], limit: int = ARTICLE_LIMIT
) -> list[dict[str, Any]]:
    """Deduplicate globally and order by publication time then first-seen."""
    unique: dict[str, dict[str, Any]] = {}
    for source, record in state.get("sources", {}).items():
        for entry in record.get("entries", []):
            url = canonical_url(entry["url"])
            candidate = {
                **entry,
                "url": url,
                "source_url": source,
                "source": source_name(source),
            }
            current = unique.get(url)
            candidate_time = (
                parse_time(candidate.get("published_at"))
                or parse_time(candidate.get("first_seen_at"))
                or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            )
            current_time = (
                (
                    parse_time(current.get("published_at"))
                    or parse_time(current.get("first_seen_at"))
                    or dt.datetime.min.replace(tzinfo=dt.timezone.utc)
                )
                if current
                else dt.datetime.min.replace(tzinfo=dt.timezone.utc)
            )
            if current is None or candidate_time > current_time:
                unique[url] = candidate
    ordered = list(unique.values())
    ordered.sort(
        key=lambda item: (
            parse_time(item.get("published_at"))
            or parse_time(item.get("first_seen_at"))
            or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            item["url"],
        ),
        reverse=True,
    )
    return ordered[:limit]


def _plain_inlines(inlines: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for inline in inlines or []:
        kind, content = inline.get("t"), inline.get("c")
        if kind in {"Str", "Code", "Math"}:
            parts.append(content if isinstance(content, str) else content[-1])
        elif kind in {"Space", "SoftBreak", "LineBreak"}:
            parts.append(" ")
        elif kind in {
            "Emph",
            "Strong",
            "Strikeout",
            "SmallCaps",
            "Superscript",
            "Subscript",
        }:
            parts.append(_plain_inlines(content))
        elif kind in {"Link", "Image"} or kind == "Quoted":
            parts.append(_plain_inlines(content[1]))
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _blocks_text(blocks: list[dict[str, Any]]) -> str:
    values: list[str] = []
    for block in blocks:
        kind, content = block.get("t"), block.get("c")
        if kind in {"Para", "Plain"}:
            values.append(_plain_inlines(content))
        elif kind == "Header":
            values.append(_plain_inlines(content[2]))
        elif kind in {"BlockQuote", "Div"}:
            values.append(_blocks_text(content if kind == "BlockQuote" else content[1]))
        elif kind in {"BulletList", "OrderedList"}:
            items = content if kind == "BulletList" else content[1]
            values.extend(_blocks_text(item) for item in items)
        elif kind == "CodeBlock":
            values.append(content[1])
    return "\n".join(value for value in values if value)


def _table_rows(content: Any) -> list[list[str]]:
    """Extract readable cells from Pandoc's current or legacy Table node."""
    if not isinstance(content, list):
        return []

    def modern_row(row: Any) -> list[str]:
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[1], list):
            return []
        cells: list[str] = []
        for cell in row[1]:
            # Pandoc 2+/3+: [attr, alignment, rowSpan, colSpan, blocks].
            if isinstance(cell, list) and len(cell) >= 5 and isinstance(cell[-1], list):
                cells.append(_blocks_text(cell[-1]))
        return cells

    if len(content) >= 6:
        result: list[list[str]] = []
        head = content[3]
        if isinstance(head, list) and len(head) == 2:
            result.extend(filter(None, (modern_row(row) for row in head[1])))
        for body in content[4] if isinstance(content[4], list) else []:
            if isinstance(body, list) and len(body) >= 4:
                result.extend(filter(None, (modern_row(row) for row in body[2])))
                result.extend(filter(None, (modern_row(row) for row in body[3])))
        foot = content[5]
        if isinstance(foot, list) and len(foot) == 2:
            result.extend(filter(None, (modern_row(row) for row in foot[1])))
        return result

    # Legacy Pandoc: [caption, aligns, widths, headerCells, bodyRows].
    result = []
    if len(content) >= 5:
        header = [_blocks_text(cell) for cell in content[3]]
        if any(header):
            result.append(header)
        for row in content[4]:
            values = [_blocks_text(cell) for cell in row]
            if values:
                result.append(values)
    return result


def pandoc_blocks(markdown: str) -> list[dict[str, Any]]:
    try:
        process = subprocess.run(
            ["pandoc", "--from=gfm-raw_html", "--to=json"],
            input=markdown.encode(),
            capture_output=True,
            check=True,
            timeout=60,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise PublicationError(f"Pandoc conversion failed: {exc}") from exc
    if len(process.stdout) > MAX_JSON_BYTES:
        raise PublicationError("Pandoc document exceeds 10 MB")
    document = json.loads(process.stdout)
    output: list[dict[str, Any]] = []

    def convert(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for node in nodes:
            kind, content = node.get("t"), node.get("c")
            if kind == "Header":
                converted.append(
                    {
                        "type": "heading",
                        "level": max(1, min(6, int(content[0]))),
                        "text": _plain_inlines(content[2]),
                    }
                )
            elif kind in {"Para", "Plain"}:
                images = [inline for inline in content if inline.get("t") == "Image"]
                text = _plain_inlines(
                    [inline for inline in content if inline.get("t") != "Image"]
                )
                if text:
                    converted.append({"type": "paragraph", "text": text})
                for image in images:
                    alt = _plain_inlines(image["c"][1])
                    target = image["c"][2][0]
                    converted.append({"type": "image", "url": target, "caption": alt})
            elif kind in {"BulletList", "OrderedList"}:
                items = content if kind == "BulletList" else content[1]
                converted.append(
                    {
                        "type": "list",
                        "ordered": kind == "OrderedList",
                        "items": [
                            _blocks_text(item) for item in items if _blocks_text(item)
                        ],
                    }
                )
            elif kind == "CodeBlock":
                language = content[0][1][0] if content[0][1] else ""
                converted.append(
                    {"type": "code", "language": language, "text": content[1]}
                )
            elif kind == "BlockQuote":
                converted.append({"type": "quote", "text": _blocks_text(content)})
            elif kind == "HorizontalRule":
                converted.append({"type": "divider"})
            elif kind == "Table":
                rows = _table_rows(content)
                if rows:
                    converted.append({"type": "table", "rows": rows})
            elif kind == "Div":
                converted.extend(convert(content[1]))
            # RawBlock and every unknown/active node are intentionally dropped.
        return converted

    output.extend(convert(document.get("blocks", [])))
    for block in output:
        if block.get("type") not in SAFE_BLOCK_TYPES:
            raise PublicationError(f"unsafe converted block: {block.get('type')}")
    return output


def normalize_image(
    raw: bytes, content_type: str = "", source: str = ""
) -> tuple[bytes, str]:
    if len(raw) > MAX_IMAGE_BYTES:
        raise PublicationError(f"image exceeds 40 MB: {source}")
    is_svg = (
        "svg" in content_type.lower()
        or raw.lstrip().startswith(b"<svg")
        or source.lower().endswith(".svg")
    )
    try:
        if is_svg:
            import cairosvg

            raw = cairosvg.svg2png(bytestring=raw, output_width=MAX_IMAGE_EDGE)
        with Image.open(io.BytesIO(raw)) as opened:
            opened.load()
            image = ImageOps.exif_transpose(opened)
            has_alpha = image.mode in {"RGBA", "LA"} or (
                image.mode == "P" and "transparency" in image.info
            )
            if has_alpha:
                rgba = image.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                image = Image.alpha_composite(background, rgba).convert("L")
            else:
                image = image.convert("L")
            image.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE), Image.Resampling.LANCZOS)
            png = io.BytesIO()
            image.save(png, "PNG", optimize=True)
            jpeg = io.BytesIO()
            image.save(jpeg, "JPEG", quality=82, optimize=True, progressive=False)
    except Exception as exc:
        raise PublicationError(f"cannot normalize image {source}: {exc}") from exc
    # Diagrams usually win as PNG; photographs usually win as JPEG.  Choosing
    # the smaller output also makes the result deterministic for a Pillow build.
    if len(jpeg.getvalue()) + 256 < len(png.getvalue()):
        return jpeg.getvalue(), "jpg"
    return png.getvalue(), "png"


def localize_and_normalize_images(
    markdown: str,
    article_url: str,
    prepared_dir: Path,
    snapshot: Path,
    origin: str,
    session: requests.Session,
) -> tuple[str, list[dict[str, Any]]]:
    manifest: dict[str, dict[str, Any]] = {}

    def replace(match: re.Match[str]) -> str:
        inside = match.group("inside").strip()
        title_match = _IMG_TITLE_RE.match(inside)
        reference = title_match.group("url").strip() if title_match else inside
        try:
            if reference.startswith("images/"):
                path = (prepared_dir / reference).resolve()
                if prepared_dir.resolve() not in path.parents:
                    raise PublicationError("image path escapes article directory")
                raw = path.read_bytes()
                content_type = "image/svg+xml" if path.suffix.lower() == ".svg" else ""
            else:
                remote = urljoin(article_url, reference.replace(" ", "%20"))
                if urlparse(remote).scheme not in {"http", "https"}:
                    return ""
                response = session.get(remote, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                raw = response.content
                content_type = response.headers.get("Content-Type", "")
            normalized, extension = normalize_image(raw, content_type, reference)
            digest = sha256_bytes(normalized)
            relative = f"remarkable/api/v1/assets/{digest}.{extension}"
            destination = snapshot / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists():
                destination.write_bytes(normalized)
            public_url = f"{origin}/{relative}"
            manifest[digest] = {
                "url": public_url,
                "sha256": digest,
                "bytes": len(normalized),
                "media_type": "image/jpeg" if extension == "jpg" else "image/png",
            }
            return f"![{match.group('alt')}]({public_url})"
        except (OSError, requests.RequestException, PublicationError) as exc:
            print(f"    ! dropped image {reference}: {exc}")
            return ""

    localized = MD_IMAGE_RE.sub(replace, markdown)
    return localized, sorted(manifest.values(), key=lambda item: item["sha256"])


def deterministic_summary(blocks: list[dict[str, Any]], maximum: int = 280) -> str:
    for block in blocks:
        if block.get("type") != "paragraph":
            continue
        text = re.sub(r"\s+", " ", block.get("text", "")).strip()
        if not text:
            continue
        if len(text) <= maximum:
            return text
        cut = text[: maximum + 1].rsplit(" ", 1)[0].rstrip(" ,;:-")
        return cut + "…"
    return ""


def extract_article(
    entry: dict[str, Any], snapshot: Path, origin: str
) -> tuple[dict[str, Any], bytes]:
    session = make_session()
    article_id = stable_id(entry["url"])
    with tempfile.TemporaryDirectory(
        prefix=f"estafette-{article_id[:20]}-"
    ) as temporary:
        prepared_dir = Path(temporary)
        try:
            response = session.get(entry["url"], timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            if len(response.content) > MAX_IMAGE_BYTES:
                raise PublicationError("article HTML exceeds 40 MB")
            html = response.text
            title = extract_title(html, entry["url"])
            prepared = prepare_html(html, entry["url"], prepared_dir)
            markdown = trafilatura.extract(
                prepared,
                url=entry["url"],
                output_format="markdown",
                include_images=True,
                include_links=True,
                include_tables=True,
                favor_precision=True,
            )
            if not markdown or not markdown.strip():
                raise PublicationError("no readable article content")
            markdown = restore_inline_assets(markdown)
            markdown, assets = localize_and_normalize_images(
                markdown,
                entry["url"],
                prepared_dir,
                snapshot,
                origin,
                session,
            )
            blocks = pandoc_blocks(markdown)
            if not blocks:
                raise PublicationError("article produced no safe content blocks")
            image_urls = {
                block["url"] for block in blocks if block.get("type") == "image"
            }
            assets = [asset for asset in assets if asset["url"] in image_urls]
            article = {
                "schema_version": SCHEMA_VERSION,
                "id": article_id,
                "title": title or entry.get("title") or entry["url"],
                "source": entry["source"],
                "source_url": entry["source_url"],
                "canonical_url": entry["url"],
                "published_at": entry.get("published_at"),
                "first_seen_at": entry["first_seen_at"],
                "category": entry.get("category", "general"),
                "topics": entry.get("topics", []),
                "content": blocks,
                "assets": assets,
            }
            data = json_bytes(article)
            if len(data) > MAX_JSON_BYTES:
                raise PublicationError("article JSON exceeds 10 MB")
            return article, data
        finally:
            session.close()


def _load_archive(path: Path | None, destination: Path) -> dict[str, Any]:
    if not path or not path.exists() or path.stat().st_size == 0:
        return {"schema_version": SCHEMA_VERSION, "sources": {}}
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            member_path = Path(member.name)
            if (
                member_path.is_absolute()
                or ".." in member_path.parts
                or member.issym()
                or member.islnk()
            ):
                raise PublicationError(f"unsafe previous archive member: {member.name}")
        archive.extractall(destination, filter="data")
    state_path = destination / STATE_MEMBER
    if not state_path.exists():
        raise PublicationError("previous archive has no publisher state")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("schema_version") != SCHEMA_VERSION:
        raise PublicationError("previous publisher-state schema is unsupported")
    return state


def _previous_articles(snapshot: Path) -> dict[str, tuple[dict[str, Any], Path]]:
    result: dict[str, tuple[dict[str, Any], Path]] = {}
    root = snapshot / "remarkable/api/v1/articles"
    if not root.exists():
        return result
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("id") and data.get("canonical_url"):
                result[canonical_url(data["canonical_url"])] = (data, path)
        except (OSError, ValueError):
            continue
    return result


def _copy_reused_article(
    article: dict[str, Any], path: Path, old_snapshot: Path, new_snapshot: Path
) -> bytes:
    data = path.read_bytes()
    destination = new_snapshot / path.relative_to(old_snapshot)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    for asset in article.get("assets", []):
        relative = urlparse(asset["url"]).path.lstrip("/")
        # Pages project paths can have a repository prefix; anchor at remarkable/.
        index = relative.find("remarkable/")
        if index >= 0:
            relative = relative[index:]
        source = old_snapshot / relative
        target = new_snapshot / relative
        if not source.is_file() or sha256_bytes(source.read_bytes()) != asset.get(
            "sha256"
        ):
            raise PublicationError(f"previous asset is damaged: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(source, target)
    return data


def _summary(
    entry: dict[str, Any], article: dict[str, Any], data: bytes, origin: str
) -> dict[str, Any]:
    digest = sha256_bytes(data)
    filename = f"{article['id']}-{digest[:16]}.json"
    return {
        "id": article["id"],
        "title": article["title"],
        "source": article["source"],
        "published_at": article.get("published_at"),
        "first_seen_at": article["first_seen_at"],
        "category": article["category"],
        "topics": article["topics"],
        "canonical_url": article["canonical_url"],
        "article_url": f"{origin}/remarkable/api/v1/articles/{filename}",
        "excerpt": deterministic_summary(article["content"]),
        "bytes": len(data),
        "sha256": digest,
    }


def directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def build_snapshot(
    state: dict[str, Any],
    prior_snapshot: Path,
    destination: Path,
    origin: str,
    generated_at: dt.datetime,
    site_overlay: Path | None = None,
    extractor: Callable[
        [dict[str, Any], Path, str], tuple[dict[str, Any], bytes]
    ] = extract_article,
) -> dict[str, Any]:
    if urlparse(origin).scheme != "https" or not urlparse(origin).netloc:
        raise PublicationError("public origin must be absolute HTTPS")
    origin = origin.rstrip("/")
    if site_overlay and site_overlay.exists():
        shutil.copytree(site_overlay, destination, dirs_exist_ok=True)
    prior = _previous_articles(prior_snapshot)
    candidates = select_newest(state, limit=max(ARTICLE_LIMIT * 3, ARTICLE_LIMIT))
    summaries: list[dict[str, Any]] = []
    referenced_assets: set[str] = set()
    article_dir = destination / "remarkable/api/v1/articles"
    article_dir.mkdir(parents=True, exist_ok=True)
    for entry in candidates:
        if len(summaries) >= ARTICLE_LIMIT:
            break
        try:
            previous = prior.get(entry["url"])
            if previous:
                article, previous_path = previous
                # Reuse only when feed-facing metadata is unchanged; otherwise
                # republish the immutable JSON so its metadata and summary agree.
                reusable = all(
                    (
                        article.get("source_url") == entry.get("source_url"),
                        article.get("source") == entry.get("source"),
                        article.get("published_at") == entry.get("published_at"),
                        article.get("first_seen_at") == entry.get("first_seen_at"),
                        article.get("category") == entry.get("category", "general"),
                        article.get("topics", []) == entry.get("topics", []),
                    )
                )
                if reusable:
                    data = _copy_reused_article(
                        article, previous_path, prior_snapshot, destination
                    )
                else:
                    article, data = extractor(entry, destination, origin)
            else:
                article, data = extractor(entry, destination, origin)
            summary = _summary(entry, article, data, origin)
            final_path = article_dir / Path(urlparse(summary["article_url"]).path).name
            if not final_path.exists():
                # Reused articles may carry a previous content-hash filename.
                prior_destination = (
                    destination / previous_path.relative_to(prior_snapshot)
                    if previous and reusable
                    else None
                )
                if prior_destination and prior_destination.exists():
                    prior_destination.replace(final_path)
                else:
                    final_path.write_bytes(data)
            summaries.append(summary)
            for asset in article.get("assets", []):
                referenced_assets.add(Path(urlparse(asset["url"]).path).name)
        except Exception as exc:  # noqa: BLE001 - one bad article should not erase the feed
            print(f"  ! skipped article {entry['url']}: {exc}")
    if not summaries:
        raise PublicationError("no articles could be published")
    asset_dir = destination / "remarkable/api/v1/assets"
    if asset_dir.exists():
        for asset_path in asset_dir.iterdir():
            if asset_path.is_file() and asset_path.name not in referenced_assets:
                asset_path.unlink()
    feed = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": isoformat(generated_at),
        "total_bytes": 0,
        "articles": summaries,
    }
    feed_path = destination / "remarkable/api/v1/feed.json"
    feed_path.parent.mkdir(parents=True, exist_ok=True)
    feed_path.write_bytes(json_bytes(feed))
    # total_bytes includes the final feed itself. Iterate until its digit length
    # stabilizes so the declared value exactly matches the snapshot.
    for _ in range(10):
        actual = directory_size(destination)
        if actual == feed["total_bytes"]:
            break
        feed["total_bytes"] = actual
        feed_path.write_bytes(json_bytes(feed))
    actual = directory_size(destination)
    if actual != feed["total_bytes"]:
        raise PublicationError("snapshot byte count did not stabilize")
    if actual > MAX_SNAPSHOT_BYTES:
        raise PublicationError(
            f"snapshot is {actual} bytes; limit is {MAX_SNAPSHOT_BYTES}"
        )
    return feed


def make_archive(
    output: Path, state: dict[str, Any], current: Path, old_current: Path
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with tempfile.TemporaryDirectory(prefix="estafette-archive-") as scratch:
        root = Path(scratch)
        (root / STATE_MEMBER).write_bytes(json_bytes(state))
        shutil.copytree(current, root / CURRENT_PREFIX)
        if old_current.exists():
            shutil.copytree(old_current, root / PREVIOUS_PREFIX)
        with (
            temporary.open("wb") as raw_archive,
            gzip.GzipFile(
                filename="", mode="wb", fileobj=raw_archive, compresslevel=9, mtime=0
            ) as compressed,
            tarfile.open(fileobj=compressed, mode="w") as archive,
        ):
            for path in sorted(root.rglob("*")):
                arcname = path.relative_to(root)
                info = archive.gettarinfo(str(path), str(arcname))
                info.mtime = 0
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                if path.is_file():
                    with path.open("rb") as handle:
                        archive.addfile(info, handle)
                else:
                    archive.addfile(info)
    os.replace(temporary, output)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-archive", type=Path)
    parser.add_argument("--output-archive", type=Path, required=True)
    parser.add_argument("--pages-output", type=Path, required=True)
    parser.add_argument("--site-overlay", type=Path)
    parser.add_argument(
        "--origin", default=os.environ.get("ESTAFETTE_PUBLIC_ORIGIN", DEFAULT_ORIGIN)
    )
    parser.add_argument(
        "--generated-at", help="ISO-8601 override used by deterministic tests"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    use_utf8_stdout()
    args = parse_args(argv)
    now = parse_time(args.generated_at) if args.generated_at else utc_now()
    if now is None:
        raise SystemExit("--generated-at must be ISO-8601")
    with (
        tempfile.TemporaryDirectory(prefix="estafette-previous-") as previous_temp,
        tempfile.TemporaryDirectory(prefix="estafette-new-") as new_temp,
    ):
        previous_root = Path(previous_temp)
        state = _load_archive(args.previous_archive, previous_root)
        old_current = previous_root / CURRENT_PREFIX
        refreshed, warnings = refresh_sources(
            tablet_source_lines(read_urls()), state, now
        )
        for warning in warnings:
            print(f"  ! {warning}")
        new_snapshot = Path(new_temp) / CURRENT_PREFIX
        new_snapshot.mkdir(parents=True)
        feed = build_snapshot(
            refreshed,
            old_current,
            new_snapshot,
            args.origin,
            now,
            site_overlay=args.site_overlay,
        )
        args.pages_output.parent.mkdir(parents=True, exist_ok=True)
        if args.pages_output.exists():
            shutil.rmtree(args.pages_output)
        shutil.copytree(new_snapshot, args.pages_output)
        make_archive(args.output_archive, refreshed, new_snapshot, old_current)
        print(
            f"Published {len(feed['articles'])} articles ({feed['total_bytes']} bytes)."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
