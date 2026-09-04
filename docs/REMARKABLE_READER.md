# Estafette reader for reMarkable Paper Pro

Status: **public beta (`0.1.0-beta.14`)**. Do not publish `v1.0.0` until the
device acceptance checklist at the end of this document passes on the target
Paper Pro.

## Architecture

The weekly PDF and daily tablet feeds share `urls.txt` and the article cleanup
helpers, but no state:

```text
urls.txt
   │
   ├── Monday 05:00 UTC ── detect/extract/PDF ── state/seen.json
   │
   └── Daily 06:00 UTC ── remarkable_publisher.py
                                │
                                ├── publisher-state.json
                                ├── previous/
                                └── current/ ── validated into GitHub Pages
                                                      │
                                                      └── Go sync backend ── QML UI
```

The rolling state and snapshots live in the stable, non-edition GitHub Release
asset `remarkable-content.tar.gz`. They are never committed. A failed feed,
extraction, size check, validation, or workflow run cannot upload a replacement
asset. GitHub Pages deployments are atomic, and the tablet commits its feed
only after all article JSON and image assets verify.

Cloud Run remains exclusive to OAuth and Google Drive delivery. Reader content
is static, public, and same-origin on Pages.

## Publisher contract

`src/remarkable_publisher.py` uses 12 feed workers and a 15-second request
timeout. Each source record stores its recent feed entries and their first-seen
times. If one source fails, its prior record is carried forward; a success does
not depend on any other source. Entries are canonical-URL deduplicated and
ordered by publication time, falling back to the stable first-seen time.

The tablet publisher excludes PortSwigger and drops its prior tablet-feed state
on the next successful snapshot. The weekly PDF source list remains unchanged.

The newest extractable 100 articles are published. Previously published,
unchanged articles and assets are copied from the prior snapshot. New Markdown
is converted by Pandoc (`gfm-raw_html`) into this allowlisted block model:

- `heading`, `paragraph`, `list`, `code`, `quote`
- `image`, `table`, `divider`

Pandoc raw nodes and unknown nodes are discarded. Summaries are the first
readable paragraph, truncated deterministically at a word boundary. There is no
AI summarization dependency.

Raster images are orientation-normalized, flattened on white, stripped of
metadata, converted to grayscale, and bounded to 1400 px on their longest edge.
SVG is rasterized first. The smaller deterministic optimized PNG/JPEG result is
addressed by SHA-256. Individual source-image responses are capped at 40 MB.
The complete Pages snapshot, including the app package, must be at most 480
MiB. The declaration in `feed.json` must equal the exact current-tree size.

## Public API

All tablet-consumed URLs use the same HTTPS origin:

| Resource | Purpose |
| --- | --- |
| `/remarkable/api/v1/feed.json` | Schema, generation timestamp, exact snapshot bytes, and up to 100 summaries |
| `/remarkable/api/v1/articles/<id>-<hash>.json` | Immutable article metadata, content blocks, and asset manifest |
| `/remarkable/api/v1/assets/<sha256>.<ext>` | Immutable normalized image |
| `/remarkable/app/v1/manifest.json` | App version, ZIP URL/hash, feed URL, model, tested firmware |
| `/remarkable/downloads/estafette-rmpp-<version>.zip` | AppLoad app plus reviewed installer resources |

`article_url` is the same-origin content JSON URL. `canonical_url` is retained
separately for source attribution. Every article/feed JSON and every asset is
size-bounded and checksummed. `src/expand_remarkable_snapshot.py` re-verifies
the entire graph before a release snapshot is copied into Pages.

## AppLoad application

The ZIP contains the required internal-app files:

```text
estafette/
├── manifest.json
├── icon.png
├── resources.rcc
└── backend/entry
```

`resources.rcc` includes the Qt Quick/Controls/Settings UI. The backend is
built with `CGO_ENABLED=0 GOOS=linux GOARCH=arm64`; no libraries are installed
on the tablet. Persistent content lives at
`/home/root/.local/share/estafette/`, outside the replaceable app directory.

AppLoad uses an eight-byte little-endian header and a second `SOCK_SEQPACKET`
record for its UTF-8 contents. The application messages are:

| Type | Direction | Meaning |
| --- | --- | --- |
| `100` | QML → Go | Return cached feed |
| `101` | QML → Go | Start refresh |
| `102` | QML → Go | Return article by stable ID |
| `200` | Go → QML | Feed JSON |
| `201` | Go → QML | Article with verified local `file:` image paths |
| `202` | Go → QML | Non-blocking synchronization progress |
| `203` | Go → QML | Synchronization complete |
| `400` | Go → QML | Structured offline/validation/storage/network error |

The backend uses the platform CA roots and normal TLS hostname verification.
Feed, article, and asset download URLs must have HTTPS and the compiled Pages
host. Downloads use `.part` files and HTTP Range; checksum-valid files are
reused. Article/assets are synchronized first and `feed.json` is the atomic
commit point. Unreferenced immutable files are pruned afterward. The on-disk
cache may not exceed 512 MiB. A partial or failed run leaves the prior feed and
all its references readable.

The QML UI requests the cached feed and a refresh on startup. Its persistent
left rail starts with a 72-hour News view, then holds the All, Offensive, Vuln
Dev, Threat Intel, and General filters, plus persistent To Read and Like views,
counts, synchronization state, and the refresh action. Each feed headline has
compact read-later and heart controls; a liked heart remains filled in the
grayscale feed. A title search at the top filters the active
section case-insensitively. Holding a feed card for two seconds opens its
actions: assign or replace one personal custom tag, clear that tag, or delete
the entry. Custom tags are persisted locally and become count-bearing filters
in the left rail. The article menu can persistently remove
an entry from every on-device list without deleting the shared snapshot.
The palette and monospaced typography mirror the Ottersec Blog theme while
remaining e-ink friendly. Feed and menu screens stay in the fast grayscale
display mode. Article reading uses content-quality refresh, and tapping a valid
cached image opens a full-screen viewer with 100–400% zoom and drag-to-pan.
Scrollable regions switch to the animation waveform only while moving, use
pixel-aligned updates, and cap inertial motion to roughly 75 ms so a released
swipe cannot produce a one-second repaint tail.
QSettings owns read/unread state, saved page, selected category, and the
Compact/Standard/Large type choice. This avoids the Paper Pro 3.28 image's
missing Qt SQLite driver while keeping navigation independent from preference
persistence. Page controls move 90% of the viewport.
AppLoad display-method areas request content-quality refresh for reading and
fast refresh for controls.

## Installation and recovery

The safe host installer downloads the app manifest and package using `curl`
with certificate verification and TLS 1.2+, rejects a foreign package origin,
and checks SHA-256 before unpacking. The tablet helper refuses an incomplete
AppLoad installation, stages on the target filesystem, backs up the prior app,
and renames atomically. It never touches the cache.

On Paper Pro/Ferrari OS `3.28.0.172`, it also installs
`zz-estafette-sidebar.qmd` and `estafette-shortcut.rcc`. These files are
idempotent and separate from AppLoad's embedded compatibility diff. The action
launches internal AppLoad ID `estafette`. The QMLDiff does not contain or
rewrite Calculator; the compatibility patch retains the already validated
Calculator insertion, so both sidebar actions coexist. Other firmware receives
only the portable AppLoad tile and a warning.

The advanced path refuses non-Ferrari hardware, Paper Pro Move, every firmware
except `3.28.0.172`, and non-aarch64 systems. It verifies:

- Xovi extensions `v19-23052026` archive:
  `32d64d1262ddc984e3235c7d0340a398fe6d5b3efa6a979865f5977b32630d27`
- AppLoad `v0.5.3` archive:
  `032e3f2c57a004aba4425894758e4b542c67590efd222e3b3d5141124c45e84d`
- upstream AppLoad binary before patch:
  `31214cbbe64c8bfe7d99096f077c3009dba8a42ef1a733801aa0ec59c134e7cc`
- deterministic 3.28-patched AppLoad binary:
  `29733851d7b6a81e8f7cb754bc122aca5a2e519879c795ebfe0a4625306b108a`

It generates the live firmware hashtable, starts Xovi once, and confirms both
xochitl health and `LD_PRELOAD=/home/root/xovi/xovi.so`. Failure runs Xovi's
stock recovery, restores changed runtime files, and restarts stock xochitl.

Triple-tap is opt-in (`--triple-tap`) and fetched from reviewed upstream commit
`869497aa61435448bf0077fbf75fb264dcba92c5`. Its `install.sh` must hash to
`c84f0c441118078a74bf3a7e1ee9aa136ab1fed3cc43668637a97a3cd0cddfa2`.
No automatic Xovi/xochitl boot-unit injection is shipped.

## Verification

Run:

```bash
PYTHONPATH=src:backend pytest -q
go test -C remarkable/backend ./...
node remarkable/tests/test_qml_logic.js remarkable/app/ui/logic.js
sh -n site/remarkable/install-*.sh remarkable/installers/*.sh
```

The automated suite covers source failure retention, deduplication, missing
dates, top-100 selection, Pandoc sanitization, image normalization,
deterministic hashes, pruning, size rejection, protocol framing, TLS and origin
checks, malformed/oversized JSON, checksum failure, resume, atomic feed
recovery, complete image prefetch, cache enforcement, QML filtering/state/page
logic, package hashes, safe refusal, idempotent install, rollback, shortcut
separation, and exact advanced gates.

## Device acceptance before v1.0.0

- [ ] Install the hosted beta on the current Paper Pro/Ferrari 3.28.0.172.
- [ ] Complete a real 100-article synchronization; hash every cached asset.
- [ ] Read headings, paragraphs, lists, code, quotes, images, tables, dividers,
      and all four categories.
- [ ] Reopen articles at their saved page in all three text sizes.
- [ ] Disable networking; read the full feed, text, and images.
- [ ] Confirm Calculator and Estafette shortcuts both launch.
- [ ] Reboot, explicitly install/activate triple-tap, and confirm Estafette returns.
- [ ] Record firmware, package SHA-256, feed generation, cache byte count, and
      results in a release validation note.

Only after every item passes should `APP_VERSION` become `1.0.0` and a matching
public release be announced.
