#!/usr/bin/env python3
"""Create a deterministic AppLoad ZIP and its public update manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import stat
import zipfile
from pathlib import Path
from urllib.parse import urlparse

REQUIRED = ("manifest.json", "icon.png", "resources.rcc", "backend/entry")


def package(bundle: Path, output: Path) -> str:
    for relative in REQUIRED:
        path = bundle / relative
        if not path.is_file() or path.stat().st_size == 0:
            raise SystemExit(f"missing bundle file: {relative}")
    manifest = json.loads((bundle / "manifest.json").read_text())
    if manifest.get("id") != "estafette" or not manifest.get("loadsBackend"):
        raise SystemExit("invalid AppLoad manifest")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(bundle.parent.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(bundle.parent).as_posix()
            info = zipfile.ZipInfo(relative, (1980, 1, 1, 0, 0, 0))
            executable = relative.endswith(("/entry", ".sh", ".py"))
            info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return hashlib.sha256(output.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--overlay", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--origin", required=True)
    args = parser.parse_args()
    origin = args.origin.rstrip("/")
    if urlparse(origin).scheme != "https":
        raise SystemExit("origin must use HTTPS")
    filename = f"estafette-rmpp-{args.version}.zip"
    destination = args.overlay / "remarkable/downloads" / filename
    digest = package(args.bundle, destination)
    app_manifest = {
        "schema_version": 1,
        "version": args.version,
        "package_url": f"{origin}/remarkable/downloads/{filename}",
        "sha256": digest,
        "feed_url": f"{origin}/remarkable/api/v1/feed.json",
        "supported_model": "reMarkable Paper Pro / Ferrari",
        "tested_firmware": "3.28.0.172",
    }
    manifest_path = args.overlay / "remarkable/app/v1/manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(app_manifest, indent=2) + "\n")
    print(f"{filename} {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
