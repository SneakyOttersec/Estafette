import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import remarkable_publisher as publisher
from expand_remarkable_snapshot import validate

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 9, 4, 6, 0, tzinfo=dt.timezone.utc)


def test_validated_release_expands_current_tree_and_rejects_tampered_package(tmp_path):
    origin = "https://example.test"
    package = b"deterministic app package"
    overlay = tmp_path / "overlay"
    download = overlay / "remarkable/downloads/app.zip"
    download.parent.mkdir(parents=True)
    download.write_bytes(package)
    app_manifest = overlay / "remarkable/app/v1/manifest.json"
    app_manifest.parent.mkdir(parents=True)
    app_manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "version": "test",
                "package_url": origin + "/remarkable/downloads/app.zip",
                "sha256": hashlib.sha256(package).hexdigest(),
                "feed_url": origin + "/remarkable/api/v1/feed.json",
                "supported_model": "reMarkable Paper Pro / Ferrari",
                "tested_firmware": "3.28.0.172",
            }
        )
    )
    source_entry = {
        "url": "https://source.test/article",
        "title": "Article",
        "published_at": "2026-09-04T00:00:00Z",
        "first_seen_at": "2026-09-04T00:00:00Z",
        "category": "general",
        "topics": [],
    }
    state = {
        "schema_version": 1,
        "sources": {"https://source.test/": {"entries": [source_entry]}},
    }

    def extract(entry, _snapshot, _origin):
        article = {
            "schema_version": 1,
            "id": publisher.stable_id(entry["url"]),
            "title": "Article",
            "source": "source.test",
            "source_url": "https://source.test/",
            "canonical_url": entry["url"],
            "published_at": entry["published_at"],
            "first_seen_at": entry["first_seen_at"],
            "category": "general",
            "topics": [],
            "content": [{"type": "paragraph", "text": "Body"}],
            "assets": [],
        }
        return article, publisher.json_bytes(article)

    current = tmp_path / "current"
    publisher.build_snapshot(
        state,
        tmp_path / "absent",
        current,
        origin,
        NOW,
        site_overlay=overlay,
        extractor=extract,
    )
    archive = tmp_path / "remarkable-content.tar.gz"
    publisher.make_archive(archive, state, current, tmp_path / "absent")
    expanded = tmp_path / "expanded"
    subprocess.run(
        ["python", ROOT / "src/expand_remarkable_snapshot.py", archive, expanded],
        check=True,
    )
    assert (expanded / "remarkable/api/v1/feed.json").is_file()
    assert (expanded / "remarkable/downloads/app.zip").read_bytes() == package

    feed_path = expanded / "remarkable/api/v1/feed.json"
    valid_feed = feed_path.read_bytes()
    feed_path.write_bytes(valid_feed.replace(b"example.test", b"evilxxx.test", 1))
    with pytest.raises(SystemExit, match="same-origin"):
        validate(expanded)
    feed_path.write_bytes(valid_feed)

    (expanded / "remarkable/downloads/app.zip").write_bytes(b"tampered")
    result = subprocess.run(
        [
            "python",
            "-c",
            (
                "from pathlib import Path; "
                "from expand_remarkable_snapshot import validate; "
                f"validate(Path({str(expanded)!r}))"
            ),
        ],
        env={"PYTHONPATH": str(ROOT / "src")},
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert b"mismatch" in result.stderr or b"integrity" in result.stderr
