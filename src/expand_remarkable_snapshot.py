#!/usr/bin/env python3
"""Safely validate and expand the current release snapshot into a Pages tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tarfile
import tempfile
from pathlib import Path
from urllib.parse import urlparse

LIMIT = 480 * 1024 * 1024


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def resolve_public_file(root: Path, raw_url: str) -> Path:
    path = urlparse(raw_url).path
    marker = "/remarkable/"
    index = path.find(marker)
    if index < 0:
        raise SystemExit(f"URL is outside remarkable namespace: {raw_url}")
    relative = Path(path[index + 1 :])
    target = (root / relative).resolve()
    if root.resolve() not in target.parents:
        raise SystemExit("snapshot URL escapes current tree")
    return target


def url_origin(raw_url: str) -> tuple[str, str]:
    parsed = urlparse(raw_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username is not None:
        raise SystemExit(f"public URL is not absolute HTTPS: {raw_url}")
    return parsed.scheme, parsed.netloc.lower()


def validate(root: Path) -> None:
    feed_path = root / "remarkable/api/v1/feed.json"
    feed = json.loads(feed_path.read_text(encoding="utf-8"))
    if feed.get("schema_version") != 1 or not 0 < len(feed.get("articles", [])) <= 100:
        raise SystemExit("invalid feed schema or article count")
    manifest_path = root / "remarkable/app/v1/manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("application manifest is absent")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_origin = url_origin(manifest["feed_url"])
    if not urlparse(manifest["feed_url"]).path.endswith(
        "/remarkable/api/v1/feed.json"
    ):
        raise SystemExit("manifest feed URL is invalid")
    if url_origin(manifest["package_url"]) != expected_origin:
        raise SystemExit("application package is not same-origin")
    total = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if total != feed.get("total_bytes") or total > LIMIT:
        raise SystemExit(f"snapshot byte count mismatch or limit violation: {total}")
    for summary in feed["articles"]:
        if url_origin(summary["article_url"]) != expected_origin:
            raise SystemExit(f"article is not same-origin: {summary['id']}")
        article_path = resolve_public_file(root, summary["article_url"])
        if article_path.name != f"{summary['id']}-{summary['sha256'][:16]}.json":
            raise SystemExit(f"article filename integrity failure: {summary['id']}")
        if (
            article_path.stat().st_size != summary["bytes"]
            or digest(article_path) != summary["sha256"]
        ):
            raise SystemExit(f"article integrity failure: {summary['id']}")
        article = json.loads(article_path.read_text(encoding="utf-8"))
        if article.get("id") != summary["id"]:
            raise SystemExit("article ID mismatch")
        for asset in article.get("assets", []):
            if url_origin(asset["url"]) != expected_origin:
                raise SystemExit(f"asset is not same-origin: {asset['sha256']}")
            asset_path = resolve_public_file(root, asset["url"])
            if not asset_path.name.startswith(asset["sha256"] + "."):
                raise SystemExit(f"asset filename integrity failure: {asset['sha256']}")
            if (
                asset_path.stat().st_size != asset["bytes"]
                or digest(asset_path) != asset["sha256"]
            ):
                raise SystemExit(f"asset integrity failure: {asset['sha256']}")
    package = resolve_public_file(root, manifest["package_url"])
    if digest(package) != manifest["sha256"]:
        raise SystemExit("application package integrity failure")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="estafette-expand-") as temporary:
        staging = Path(temporary)
        with tarfile.open(args.archive, "r:gz") as bundle:
            for member in bundle.getmembers():
                path = Path(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or member.issym()
                    or member.islnk()
                ):
                    raise SystemExit(f"unsafe archive member: {member.name}")
            bundle.extractall(staging, filter="data")
        current = staging / "current"
        validate(current)
        args.destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(current, args.destination, dirs_exist_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
