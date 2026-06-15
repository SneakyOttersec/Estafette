# Blog → PDF → Google Drive

An automated pipeline that monitors a list of blog sources, detects new posts,
extracts their content (text + images), renders a PDF of **only the new
post(s)**, and uploads it to Google Drive. If a run finds nothing new, it does
nothing.

## How it works

1. You list blog sources in [`urls.txt`](urls.txt), one per line. Each line is
   either:
   - a **blog home/section page** (e.g. `https://rastamouse.me/`) — its RSS/Atom
     feed is auto-discovered, or
   - a **single post URL** — that one article is turned into a PDF.
2. On a schedule (and on every push to `urls.txt`), GitHub Actions runs:
   - `src/detect.py` — for each blog, finds the feed and selects posts:
     - **first run** for a blog → only its **latest** post (this sets the
       baseline),
     - **later runs** → every post **newer than the baseline**.
   - `src/extract.py` — pulls the main article (Markdown) + downloads images.
   - `src/build_pdf.py` — assembles the new posts into one HTML doc (Pandoc) and
     renders `dist/<YYYY-MM-DD>.pdf` with **WeasyPrint**, styled to read like a
     **LaTeX document**: bundled Latin Modern font, a `\\maketitle`-style title
     page, a numbered table of contents, per-post numbered sections
     (`1`, `1.2`, `1.2.1`), first-line-indented justified/hyphenated paragraphs,
     running headers, and grayscale images. Page size matches the Kindle Scribe
     reading area (157×210 mm).
   - `src/upload_drive.py` — uploads the per-tag PDFs to a Drive folder named
     `BLOG_INFOSEC_NEWS` (created automatically). Files are named per tag and
     date, e.g. `REDTEAM_15_06_2026.pdf`, `RESEARCH_15_06_2026.pdf`.
   - The workflow commits the updated `state/seen.json` back so baselines and
     processed posts persist between runs.

Each run that finds new posts produces one PDF per main tag containing that
run's new posts.

## One-time setup: Google Drive (OAuth)

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

## Usage

Edit `urls.txt` and push. The pipeline runs on push (and daily via cron). You
can also trigger it manually: **Actions → Build blog PDF and upload to Drive →
Run workflow**.

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

```bash
python src/detect.py        # discovers feeds, writes work/new_posts.json
python src/extract.py       # writes work/<slug>/article.md + images
python src/build_pdf.py     # writes dist/<date>.pdf

# To test the upload, point at a key file and folder:
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
export GDRIVE_FOLDER_ID=<folder id>
python src/upload_drive.py
```

> On Windows PowerShell, use `$env:GOOGLE_APPLICATION_CREDENTIALS = "..."` etc.
> The `src/detect.py` and `src/extract.py` steps don't need WeasyPrint, so they
> run anywhere; only `src/build_pdf.py` needs the native libraries.

## Notes

- `state/seen.json` is the only persisted state; `work/` and `dist/` are scratch
  and are git-ignored.
- A post that fails to extract is **not** recorded, so it's retried next run.
- WeasyPrint renders code blocks, long lines, webp, and SVG, and skips any image
  it can't read rather than failing the whole build.
- Sources whose feed can't be found are logged and skipped (the rest still run).
- For JavaScript-heavy sites where extraction returns empty, a headless-browser
  fallback (e.g. Playwright) would be needed — not enabled by default.
