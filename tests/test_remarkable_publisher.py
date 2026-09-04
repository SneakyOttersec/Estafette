import datetime as dt
import io
import json
import shutil
import tarfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from PIL import Image

import remarkable_publisher as rp

NOW = dt.datetime(2026, 9, 4, 6, 0, tzinfo=dt.timezone.utc)


def result(source, entries=None, ok=True):
    return rp.SourceResult(
        source, source + "feed.xml", entries or [], ok, "offline" if not ok else ""
    )


def entry(url, published=None, first_seen="2026-09-01T00:00:00Z", category="general"):
    return {
        "url": url,
        "title": url.rsplit("/", 1)[-1],
        "published_at": published,
        "first_seen_at": first_seen,
        "category": category,
        "topics": ["test"],
    }


class SourceStateTests(TestCase):
    def test_tablet_sources_exclude_portswigger_without_changing_source_file(self):
        lines = [
            "https://portswigger.net/research | tag=offensive",
            "https://research.portswigger.net/ | tag=offensive",
            "https://example.test/blog | tag=general",
        ]
        self.assertEqual(
            rp.tablet_source_lines(lines),
            ["https://example.test/blog | tag=general"],
        )

    def test_failed_source_retains_previous_entries_without_touching_other_sources(
        self,
    ):
        previous = {
            "sources": {
                "https://failed.example/": {
                    "entries": [entry("https://failed.example/old")]
                }
            }
        }

        def fetch(line):
            if "failed" in line:
                return result("https://failed.example/", ok=False)
            return result(
                "https://ok.example/",
                [entry("https://ok.example/new", "2026-09-04T01:00:00Z")],
            )

        state, warnings = rp.refresh_sources(
            ["https://failed.example/", "https://ok.example/"], previous, NOW, fetch
        )
        self.assertEqual(
            state["sources"]["https://failed.example/"]["entries"][0]["url"],
            "https://failed.example/old",
        )
        self.assertEqual(
            state["sources"]["https://ok.example/"]["entries"][0]["first_seen_at"],
            "2026-09-04T06:00:00Z",
        )
        self.assertIn("retained previous entries", warnings[0])

    def test_first_seen_is_preserved_when_feed_has_no_date(self):
        old = entry("https://example.test/post", first_seen="2026-08-01T00:00:00Z")
        previous = {"sources": {"https://example.test/": {"entries": [old]}}}
        state, _ = rp.refresh_sources(
            ["ignored"],
            previous,
            NOW,
            lambda _: result(
                "https://example.test/",
                [{k: v for k, v in old.items() if k != "first_seen_at"}],
            ),
        )
        self.assertEqual(
            state["sources"]["https://example.test/"]["entries"][0]["first_seen_at"],
            "2026-08-01T00:00:00Z",
        )

    def test_global_dedup_and_missing_date_order(self):
        shared = entry("https://same.test/post", None, "2026-09-03T00:00:00Z")
        state = {
            "sources": {
                "https://one.test/": {
                    "entries": [
                        shared,
                        entry("https://old.test/post", "2026-09-01T00:00:00Z"),
                    ]
                },
                "https://two.test/": {
                    "entries": [
                        shared,
                        entry("https://new.test/post", "2026-09-04T00:00:00Z"),
                    ]
                },
            }
        }
        selected = rp.select_newest(state)
        self.assertEqual(
            [item["url"] for item in selected],
            [
                "https://new.test/post",
                "https://same.test/post",
                "https://old.test/post",
            ],
        )

    def test_top_one_hundred_is_retained(self):
        entries = [
            entry(
                f"https://test/{number}", f"2026-08-{(number % 28) + 1:02d}T00:00:00Z"
            )
            for number in range(130)
        ]
        selected = rp.select_newest({"sources": {"s": {"entries": entries}}})
        self.assertEqual(len(selected), 100)
        self.assertGreaterEqual(
            rp.parse_time(selected[0]["published_at"]),
            rp.parse_time(selected[-1]["published_at"]),
        )


class ContentTests(TestCase):
    @unittest.skipUnless(
        shutil.which("pandoc") and Path(shutil.which("pandoc")).is_file(),
        "Pandoc is installed by the publisher workflow",
    )
    def test_pandoc_safe_block_conversion_drops_active_html(self):
        markdown = """# Heading

First readable paragraph.

- one
- two

```python
print('safe')
```

> quote

---

| left | right |
| --- | --- |
| one | two |

<script>alert(1)</script><style>body{display:none}</style><iframe src=x></iframe>
"""
        blocks = rp.pandoc_blocks(markdown)
        self.assertEqual(
            [block["type"] for block in blocks],
            ["heading", "paragraph", "list", "code", "quote", "divider", "table"],
        )
        self.assertEqual(blocks[-1]["rows"], [["left", "right"], ["one", "two"]])
        self.assertNotIn("alert", json.dumps(blocks))
        self.assertEqual(rp.deterministic_summary(blocks), "First readable paragraph.")

    def test_image_normalization_is_grayscale_bounded_and_deterministic(self):
        image = Image.new("RGB", (2400, 800), (10, 120, 220))
        raw = io.BytesIO()
        image.save(raw, "PNG", pnginfo=None)
        first, extension = rp.normalize_image(raw.getvalue(), "image/png", "test.png")
        second, second_extension = rp.normalize_image(
            raw.getvalue(), "image/png", "test.png"
        )
        self.assertEqual((extension, first), (second_extension, second))
        with Image.open(io.BytesIO(first)) as normalized:
            self.assertEqual(normalized.mode, "L")
            self.assertEqual(max(normalized.size), 1400)

    def test_stable_id_and_json_hash_are_deterministic(self):
        self.assertEqual(
            rp.stable_id("HTTPS://Example.COM/a/#fragment"),
            rp.stable_id("https://example.com/a"),
        )
        self.assertEqual(
            rp.json_bytes({"b": 1, "a": 2}), rp.json_bytes({"a": 2, "b": 1})
        )


class SnapshotTests(TestCase):
    def test_snapshot_prunes_unselected_articles_and_rejects_oversize(self):
        state = {
            "sources": {
                "https://source/": {
                    "entries": [entry("https://article/one", "2026-09-04T00:00:00Z")]
                }
            }
        }

        def extractor(item, snapshot, origin):
            article = {
                "schema_version": 1,
                "id": rp.stable_id(item["url"]),
                "title": "One",
                "source": "source",
                "source_url": "https://source/",
                "canonical_url": item["url"],
                "published_at": item["published_at"],
                "first_seen_at": item["first_seen_at"],
                "category": "general",
                "topics": [],
                "content": [{"type": "paragraph", "text": "Body"}],
                "assets": [],
            }
            return article, rp.json_bytes(article)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            prior = root / "prior"
            (prior / "remarkable/api/v1/articles").mkdir(parents=True)
            (prior / "remarkable/api/v1/articles/orphan.json").write_text("{}")
            output = root / "output"
            feed = rp.build_snapshot(
                state, prior, output, "https://example.test", NOW, extractor=extractor
            )
            self.assertEqual(len(feed["articles"]), 1)
            self.assertFalse(
                (output / "remarkable/api/v1/articles/orphan.json").exists()
            )
            self.assertEqual(feed["total_bytes"], rp.directory_size(output))
            old_limit = rp.MAX_SNAPSHOT_BYTES
            try:
                rp.MAX_SNAPSHOT_BYTES = 1
                with self.assertRaisesRegex(rp.PublicationError, "limit"):
                    rp.build_snapshot(
                        state,
                        prior,
                        root / "too-large",
                        "https://example.test",
                        NOW,
                        extractor=extractor,
                    )
            finally:
                rp.MAX_SNAPSHOT_BYTES = old_limit

    def test_archive_contains_separate_state_current_and_previous(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            current, previous = root / "new", root / "old"
            current.mkdir()
            previous.mkdir()
            (current / "new.txt").write_text("new")
            (previous / "old.txt").write_text("old")
            archive = root / "snapshot.tar.gz"
            rp.make_archive(
                archive, {"schema_version": 1, "sources": {}}, current, previous
            )
            first_hash = rp.sha256_bytes(archive.read_bytes())
            rp.make_archive(
                archive, {"schema_version": 1, "sources": {}}, current, previous
            )
            self.assertEqual(rp.sha256_bytes(archive.read_bytes()), first_hash)
            with tarfile.open(archive) as bundle:
                names = set(bundle.getnames())
            self.assertIn("publisher-state.json", names)
            self.assertIn("current/new.txt", names)
            self.assertIn("previous/old.txt", names)

    def test_assets_left_by_a_failed_extraction_are_pruned(self):
        state = {
            "sources": {
                "https://source/": {
                    "entries": [
                        entry("https://article/fails", "2026-09-04T01:00:00Z"),
                        entry("https://article/works", "2026-09-04T00:00:00Z"),
                    ]
                }
            }
        }

        def extractor(item, snapshot, _origin):
            asset_dir = snapshot / "remarkable/api/v1/assets"
            asset_dir.mkdir(parents=True, exist_ok=True)
            if item["url"].endswith("fails"):
                (asset_dir / "orphan.png").write_bytes(b"orphan")
                raise rp.PublicationError("synthetic failure")
            article = {
                "schema_version": 1,
                "id": rp.stable_id(item["url"]),
                "title": "Works",
                "source": "source",
                "source_url": "https://source/",
                "canonical_url": item["url"],
                "published_at": item["published_at"],
                "first_seen_at": item["first_seen_at"],
                "category": "general",
                "topics": ["test"],
                "content": [{"type": "paragraph", "text": "Body"}],
                "assets": [],
            }
            return article, rp.json_bytes(article)

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "output"
            rp.build_snapshot(
                state,
                root / "absent",
                output,
                "https://example.test",
                NOW,
                extractor=extractor,
            )
            self.assertFalse(
                (output / "remarkable/api/v1/assets/orphan.png").exists()
            )
