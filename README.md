# Blog → PDF → Google Drive

An automated pipeline that monitors a list of blog sources, detects new posts,
extracts their content (text + images), renders an e-reader-friendly PDF of
**only the new post(s)**, and (optionally) uploads it to Google Drive. If a run
finds nothing new, it does nothing.

It's built to read on a **Kindle Scribe** (the PDF page size and grayscale
images are tuned for e-ink), but the output is a normal PDF that reads fine
anywhere.

---

## Deploy your own copy

The GitHub Actions workflow
([`.github/workflows/build-blog-pdf.yml`](.github/workflows/build-blog-pdf.yml))
ships with the repo, so there is nothing to install or host — **forking the repo
and enabling Actions *is* the deployment.** GitHub runs it on their hosted
runners. You can run it with **zero Google setup**: without Drive secrets the
pipeline still builds the PDFs and attaches them to each run as a downloadable
artifact (Drive upload is optional on top).

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
   Build blog PDF and upload to Drive**. When it finishes, download the PDFs
   from the run's **Artifacts** section (`blog-pdf`).
6. **(Optional) Send to Google Drive.** Add the three secrets from
   [Google Drive upload](#optional-google-drive-upload); from then on every run
   drops the PDFs into a Drive folder automatically.

After deployment it runs three ways: **on the schedule** (default: Mondays
05:00 UTC), on **every push to `urls.txt`**, and **on demand** via
**Actions → Build blog PDF and upload to Drive → Run workflow**.

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
4. **`src/upload_drive.py`** — *(only if Drive secrets are set)* uploads the
   PDFs to a Drive folder (default `BLOG_INFOSEC_NEWS`, created automatically).

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

## (Optional) Google Drive upload

A personal Gmail can't use a service account for Drive uploads (service-account
files have no storage quota, and Gmail has no Shared Drive). So the pipeline
uses **your own** Google credentials via OAuth — uploads are owned by you and
use your storage.

1. **Google Cloud Console** (<https://console.cloud.google.com>):
   - Enable the **Google Drive API**.
   - **OAuth consent screen**: User type *External*; add your Google account
     under **Test users**.
   - **Credentials → Create credentials → OAuth client ID → Desktop app**;
     download the JSON.
2. **Get a refresh token** (one time, locally — opens a browser):
   ```bash
   pip install google-auth-oauthlib
   python scripts/get_gdrive_token.py path/to/client_secret.json
   ```
   It prints `GDRIVE_CLIENT_ID`, `GDRIVE_CLIENT_SECRET`, `GDRIVE_REFRESH_TOKEN`.
3. **GitHub secrets** — Repo → *Settings → Secrets and variables → Actions*:

   | Secret | Value |
   | --- | --- |
   | `GDRIVE_CLIENT_ID` | from step 2 |
   | `GDRIVE_CLIENT_SECRET` | from step 2 |
   | `GDRIVE_REFRESH_TOKEN` | from step 2 |

Once those are set, the upload step activates automatically (it's skipped until
then) and drops the PDFs into a `BLOG_INFOSEC_NEWS` folder in your Drive,
updating that day's file in place on re-runs. The folder name is configurable
via the `GDRIVE_FOLDER_NAME` env in the workflow. The workflow uses the built-in
`GITHUB_TOKEN` to commit state back (`contents: write`, already set).

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

# To test the Drive upload locally, export the same OAuth values the workflow uses:
export GDRIVE_CLIENT_ID=...
export GDRIVE_CLIENT_SECRET=...
export GDRIVE_REFRESH_TOKEN=...
export GDRIVE_FOLDER_NAME=BLOG_INFOSEC_NEWS   # optional; this is the default
python src/upload_drive.py
```

> On Windows PowerShell, use `$env:GDRIVE_CLIENT_ID = "..."` etc.
> `src/detect.py` and `src/extract.py` don't need WeasyPrint, so they run
> anywhere; only `src/build_pdf.py` needs the native libraries.

---

## Notes & troubleshooting

- `state/seen.json` is the only persisted state; `work/` and `dist/` are scratch
  and are git-ignored.
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
