"""Build a single dated PDF containing ONLY the posts extracted this run.

Reads work/manifest.json (written by extract.py), concatenates each post's
Markdown into one master document with a title page and per-post page breaks,
then invokes Pandoc + XeLaTeX to produce dist/<YYYY-MM-DD>.pdf.

Prints the path of the generated PDF as the last line of stdout, and sets the
GitHub Actions step output `pdf_path` when running in CI.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from common import DIST_DIR, TEMPLATE_FILE, WORK_DIR, use_utf8_stdout

MANIFEST_FILE = WORK_DIR / "manifest.json"
MASTER_FILE = WORK_DIR / "master.md"

# Matches Markdown images with local (non-http) targets so we can re-root them.
MD_LOCAL_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()(?P<url>images/[^)\s]+)(\))")


def load_manifest() -> list[dict]:
    if not MANIFEST_FILE.exists():
        return []
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def reroot_images(markdown: str, slug: str) -> str:
    """Rewrite per-post 'images/x' paths to 'slug/images/x' (relative to work/)."""
    return MD_LOCAL_IMAGE_RE.sub(
        lambda m: f"{m.group(1)}{slug}/{m.group('url')}{m.group(3)}", markdown
    )


def build_master(manifest: list[dict], run_date: str) -> str:
    title = f"Blog Posts — {run_date}"
    parts: list[str] = [
        "---",
        f'title: "{title}"',
        f'date: "{run_date}"',
        "geometry: margin=2.5cm",
        "---",
        "",
    ]
    for i, post in enumerate(manifest):
        slug = post["slug"]
        article = (WORK_DIR / slug / "article.md").read_text(encoding="utf-8")
        article = reroot_images(article, slug)
        if i > 0:
            parts.append("\n\\newpage\n")
        parts.append(f"# {post['title']}\n")
        parts.append(f"*Source: <{post['url']}>*\n")
        parts.append(article)
        parts.append("")
    return "\n".join(parts)


def run_pandoc(master: Path, output: Path) -> None:
    cmd = [
        "pandoc",
        master.name,  # run with cwd=work so relative image paths resolve
        "-o",
        str(output.resolve()),
        "--pdf-engine=xelatex",
        "--resource-path=.",
        "-V",
        "linkcolor=blue",
    ]
    if TEMPLATE_FILE.exists():
        cmd += ["--template", str(TEMPLATE_FILE.resolve())]
    print("  $", " ".join(cmd))
    subprocess.run(cmd, cwd=WORK_DIR, check=True)


def set_github_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def main() -> None:
    use_utf8_stdout()
    manifest = load_manifest()
    if not manifest:
        print("No posts in manifest — nothing to build.")
        return

    run_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    master_md = build_master(manifest, run_date)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    MASTER_FILE.write_text(master_md, encoding="utf-8")

    DIST_DIR.mkdir(parents=True, exist_ok=True)
    output = DIST_DIR / f"{run_date}.pdf"

    try:
        run_pandoc(MASTER_FILE, output)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Pandoc failed: {exc}", file=sys.stderr)
        sys.exit(1)

    set_github_output("pdf_path", str(output))
    print(f"Built PDF with {len(manifest)} post(s): {output}")


if __name__ == "__main__":
    main()
