# Estafette — security reading for Drive and reMarkable

An automated pipeline and opt-in web app that monitor a list of security blogs,
detect new posts, render an e-reader-friendly PDF of **only the new post(s)**,
and deliver each weekly edition into an `Estafette` folder owned by every
registered Google Drive user. If a run finds nothing new, it does nothing.

It's built to read on a **Kindle Scribe** (the PDF page size and grayscale
images are tuned for e-ink), but the output is a normal PDF that reads fine
anywhere.

---

## Deploy the PDF builder

The GitHub Actions workflow
([`.github/workflows/build-blog-pdf.yml`](.github/workflows/build-blog-pdf.yml))
ships with the repo. Forking the repo and enabling Actions deploys the builder
on GitHub-hosted runners. Without the optional web application configuration,
the pipeline still builds the PDFs and attaches them to each run as a
downloadable artifact.

Step by step, in the GitHub web UI:

1. **Get your own copy.** Click **Use this template → Create a new repository**
   (or **Fork**) so the repo lives under your account or org.
2. **Enable Actions.** Open the **Actions** tab → click
   **"I understand my workflows, enable them."** GitHub disables workflows on
   new forks/templates until you confirm.
3. **Grant write permission to the workflow.** **Settings → Actions → General →
   Workflow permissions** → select **Read and write permissions** → **Save**.
   The pipeline commits `state/seen.json` back after each run to remember which
   posts it has already processed; on a fresh repo the default token is
   read-only and that final step would fail without this.
4. **Add your sources.** Edit [`urls.txt`](urls.txt) (see
   [Configuring sources](#configuring-sources)) and **commit/push to the default
   branch** (`main`).
5. **Watch the first run.** That push triggers the workflow — open **Actions →
   Build and distribute weekly blog PDF**. When it finishes, download the PDFs
   from the run's **Artifacts** section (`blog-pdf`).
6. **(Optional) Enable per-user Drive delivery.** Deploy the registration page,
   OAuth backend, and Firestore registry using the
   [Drive app deployment guide](docs/DRIVE_APP_DEPLOYMENT.md).

After deployment it runs three ways: **on the schedule** (default: Mondays
05:00 UTC), on **every push to `urls.txt`**, and **on demand** via
**Actions → Build and distribute weekly blog PDF → Run workflow**.

> **Scheduling caveats:** cron runs only fire from the repo's **default branch**,
> and GitHub may pause schedules on repos with no recent activity (push or a
> manual run resumes them). The schedule is the `cron: "0 5 * * 1"` line in the
> workflow file (always UTC) — edit it there to change cadence.

---

## How it works

On a schedule (and on every push to `urls.txt`), GitHub Actions runs four steps:

1. **`src/detect.py`** — for each blog source, finds the RSS/Atom feed and
   selects which posts are new:
   - **first run** for a blog → only its **latest** post (this sets the
     baseline),
   - **later runs** → every post **newer than the baseline**.
2. **`src/extract.py`** — pulls the main article as Markdown and downloads its
   images (converting raster images to grayscale PNG for the e-ink look).
3. **`src/build_pdf.py`** — assembles the new posts into one HTML document
   (Pandoc) and renders a PDF with **WeasyPrint**, styled to read like a
   **LaTeX document**: bundled Latin Modern fonts, a title page, a numbered
   table of contents, per-post numbered sections (`1`, `1.2`, `1.2.1`),
   first-line-indented justified/hyphenated paragraphs, and running headers.
   The page is **150×200 mm** — just inside the Kindle Scribe screen so the
   reader shows it edge-to-edge without clipping the header/footer.
4. **`backend/distribute.py`** — *(when the Drive app is configured)* loads the
   active encrypted registrations and uploads the PDFs into each user's own
   app-created `Estafette` folder.

The workflow then commits the updated `state/seen.json` back to the repo so
baselines and processed posts persist between runs.

**One PDF per main tag.** Each run that finds new posts produces one PDF per
tag, named `<TAG>_<DD_MM_YYYY>.pdf` — e.g. `REDTEAM_16_06_2026.pdf`,
`RESEARCH_16_06_2026.pdf`.

---

## Configuring sources

List your sources in [`urls.txt`](urls.txt), one per line. Blank lines and lines
starting with `#` are ignored. Each line is a **blog home/section page**
(e.g. `https://rastamouse.me/`) whose RSS/Atom feed is auto-discovered.

Fields after the URL are optional, `|`-separated, and order-free:

```
<url> | feed=<feed-url> | tag=<main-tag> | sub=<comma,separated,subtags>
```

| Field | Meaning |
| --- | --- |
| `tag`  | One of `offensive`, `vuln-dev`, `threat-intel`, `general`. The pipeline builds **one PDF per tag**. Defaults to `general`. |
| `feed` | Pin a specific feed URL (skips auto-discovery). Useful for sites where discovery fails or that are bot-blocked. |
| `sub`  | Free-form topic tags (`web`, `cloud`, `ad`, `evasion`, …) shown on the cover and per post. |

Example:

```
https://rastamouse.me/ | tag=red-team | sub=c2,cobalt-strike,evasion
https://www.sentinelone.com/labs/ | feed=https://www.sentinelone.com/feed/ | tag=research | sub=malware
```

If a feed can't be found, that source is logged and skipped — the rest still run.

---

## Layout options

The PDF layout is selected by the `PDF_LAYOUT` env var in the workflow (default
`compact`):

| `PDF_LAYOUT` | Look |
| --- | --- |
| `compact`     | Single column, smaller type (default). |
| `comfortable` | Single column, roomier type. |
| `twocol`      | Dense two-column "Paged Out" style. |

Change it in
[`.github/workflows/build-blog-pdf.yml`](.github/workflows/build-blog-pdf.yml),
or set it locally (`PDF_LAYOUT=twocol python src/build_pdf.py`).

---

## Google Drive registration app

The static frontend in `site/` has its own Estafette identity and a responsive
download archive. The latest PDF and ZIP are available directly from the home
page, alongside the personal Drive-delivery panel. The **All editions** page
groups the archive by publication year. Future weekly builds publish both
formats as GitHub Release assets, which the pages discover automatically
through GitHub's public API.

The homepage links to the same-origin reMarkable installation page. That page
publishes the current package checksum, safe and advanced installer paths, and
manual installation commands.

Users connect through a Cloud Run OAuth callback. The app requests Google's
narrow `drive.file` scope, creates a user-owned `Estafette` folder, and stores
the refresh grant encrypted in Firestore. The weekly workflow builds the PDF
once, then writes it into every registered folder. It never needs permission to
browse unrelated Drive files, and it sends no email.

See [Deploy the Google Drive delivery app](docs/DRIVE_APP_DEPLOYMENT.md) for the
complete Google Cloud, OAuth, Secret Manager, Workload Identity Federation,
Cloud Run, and GitHub Pages setup.

The older `src/upload_drive.py` utility remains available for a single personal
Drive, but the scheduled web-app flow uses the per-user backend distributor.

## Native reMarkable reader

Estafette also ships an internal AppLoad application for reMarkable Paper Pro.
It opens the last verified feed immediately and independently synchronizes the
latest 100 posts—including cleaned full text and optimized images—for offline
reading. The four categories, unread state, reading position, and typography
choice are handled by the native QML interface. The synchronization backend is
a static ARM64 Go binary.

The reader has a completely separate daily publisher state. The Monday PDF
workflow and `state/seen.json` are unchanged. A stable `remarkable-content`
GitHub Release contains the publisher state plus previous/current snapshots;
only its validated current tree is expanded into Pages, so generated articles
do not accumulate in Git history.

The public beta installation page is [`site/remarkable/index.html`](site/remarkable/index.html).
Implementation, API, recovery, and device-acceptance details are in
[`docs/REMARKABLE_READER.md`](docs/REMARKABLE_READER.md).

Build and test locally with Qt 6 `rcc`, Go 1.23+, Pandoc, and the Python
dependencies installed:

```bash
make test
make RCC=/path/to/qt6/rcc remarkable-overlay
```

---

## Running locally

```bash
pip install -r requirements.txt
```

You also need **Pandoc** and **WeasyPrint's native libraries** installed:

- Linux (Debian/Ubuntu): `sudo apt-get install pandoc libpango-1.0-0 \
  libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 shared-mime-info fonts-dejavu-core`
- macOS: `brew install pandoc pango gdk-pixbuf libffi`
- Windows: Pandoc + the GTK3 runtime (see the
  [WeasyPrint install docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows)).

Then run the steps in order:

```bash
python src/detect.py        # discovers feeds, writes work/new_posts.json
python src/extract.py       # writes work/<slug>/article.md + images
python src/build_pdf.py     # writes dist/<TAG>_<DD_MM_YYYY>.pdf
python src/package_downloads.py  # bundles all generated PDFs into one ZIP

# To test multi-user distribution locally, authenticate Application Default
# Credentials and export the backend values documented in the deployment guide:
PYTHONPATH=backend python backend/distribute.py --dist dist
```

> `src/detect.py` and `src/extract.py` don't need WeasyPrint, so they run
> anywhere; only `src/build_pdf.py` needs the native libraries.

---

## Notes & troubleshooting

- `state/seen.json` is the weekly PDF state. The reader's independent publisher
  state is stored only in the rolling `remarkable-content` Release asset;
  `work/`, `dist/`, and `remarkable/build/` are scratch and are git-ignored.
- A post that fails to extract is **not** recorded, so it's retried next run.
- WeasyPrint renders code blocks, long lines, webp, and SVG, and skips any image
  it can't read rather than failing the whole build.
- Sources whose feed can't be found are logged and skipped (the rest still run).
  For bot-blocked sites, pin the feed with `feed=` in `urls.txt`.
- For JavaScript-heavy sites where extraction returns empty, a headless-browser
  fallback (e.g. Playwright) would be needed — not enabled by default.
- **Resetting baselines:** to re-ingest a blog from scratch, remove its entries
  from `state/seen.json` (or clear the file to re-baseline everything to the
  latest post per source).
