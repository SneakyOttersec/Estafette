"""Build a reflowable EPUB per tag, alongside the PDFs.

Where the PDF (build_pdf.py) is a fixed-layout document tuned to the Kindle
Scribe's screen, the EPUB is reflowable: the reader controls font size and
margins, so it adapts to any Kindle and never clips a fixed header/footer.
The trade-off is that fixed typography and multi-column layout are gone — so
this is the prose-friendly companion to the code-faithful PDF.

Pipeline: each post's Markdown is reused as-is. For each tag we assemble one
Markdown document — a level-1 heading per post (so Pandoc makes it an EPUB
chapter and a TOC entry), a small source/tags line, then the body — and hand
it to Pandoc's EPUB writer. Images referenced by the posts are embedded by
Pandoc (paths resolve from work/). The reading fonts are embedded too.

Output: dist/<TAG>_<DD_MM_YYYY>.epub. Reuses helpers from build_pdf.
"""
from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
from html import escape
from pathlib import Path

from common import DIST_DIR, ROOT, TAG_DISPLAY, WORK_DIR, use_utf8_stdout

# Reuse the PDF builder's Markdown handling so the two outputs stay in sync.
from build_pdf import (
    INPUT_FORMAT,
    _FENCE_RE,
    group_by_tag,
    load_manifest,
    normalize_markdown,
    reroot_images,
    set_github_output,
)

FONTS_DIR = ROOT / "fonts"
EPUB_CSS_FILE = WORK_DIR / "epub.css"

# Embedded reading fonts (referenced by bare filename in the CSS below, which is
# how Pandoc's --epub-embed-font expects them).
EMBED_FONTS = [
    "lmroman10-regular.otf",
    "lmroman10-italic.otf",
    "lmroman10-bold.otf",
    "lmroman10-bolditalic.otf",
    "lmmono10-regular.otf",
]

EPUB_CSS = """
@font-face { font-family:'LM Roman'; font-weight:normal; font-style:normal;
             src:url('lmroman10-regular.otf'); }
@font-face { font-family:'LM Roman'; font-weight:normal; font-style:italic;
             src:url('lmroman10-italic.otf'); }
@font-face { font-family:'LM Roman'; font-weight:bold; font-style:normal;
             src:url('lmroman10-bold.otf'); }
@font-face { font-family:'LM Roman'; font-weight:bold; font-style:italic;
             src:url('lmroman10-bolditalic.otf'); }
@font-face { font-family:'LM Mono'; font-weight:normal; font-style:normal;
             src:url('lmmono10-regular.otf'); }

body { font-family:'LM Roman', Georgia, serif; line-height:1.5;
       text-align:justify; hyphens:auto; }
h1, h2, h3, h4, h5, h6 { font-family:'LM Roman', Georgia, serif; font-weight:bold;
                         line-height:1.25; text-align:left; }
h1 { font-size:1.6em; margin:0 0 0.6em; }
h2 { font-size:1.3em; } h3 { font-size:1.1em; }
p { margin:0 0 0.2em; text-indent:1.4em; }
/* First paragraph after a heading/block isn't indented (LaTeX behaviour). */
h1 + p, h2 + p, h3 + p, .source + *, .tags + *, figure + p,
pre + p, blockquote + p, ul + p, ol + p, table + p { text-indent:0; }

.source { font-style:italic; font-size:0.8em; color:#555; text-indent:0;
          margin:0; word-break:break-all; }
.tags { font-size:0.8em; color:#444; text-indent:0; margin:0.2em 0 1em; }
.tags .main { font-weight:bold; }

a { color:inherit; }
code, pre, kbd, samp { font-family:'LM Mono', 'DejaVu Sans Mono', monospace; }
code { font-size:0.85em; }
pre { font-size:0.8em; line-height:1.3; white-space:pre-wrap; overflow-wrap:anywhere;
      background:#f4f4f2; border:1px solid #ccc; padding:0.5em; text-align:left;
      hyphens:none; }
pre code { font-size:1em; }
img { max-width:100%; height:auto; }
figure { margin:1em 0; text-align:center; }
figcaption { font-size:0.85em; color:#333; }
table { border-collapse:collapse; width:100%; font-size:0.85em; margin:1em 0; }
th, td { border:1px solid #bbb; padding:2px 5px; text-align:left; vertical-align:top; }
th { background:#efefee; }
blockquote { border-left:3px solid #bbb; margin:1em 0; padding-left:1em; color:#333; }
blockquote p { text-indent:0; }
"""

# A line that opens an ATX heading: 1-6 leading '#', then whitespace + content.
_ATX_RE = re.compile(r"^(#{1,6})\s+\S")


def demote_headings(markdown: str) -> str:
    """Push every ATX heading down one level (h1->h2, ...), fence-aware, so the
    only level-1 heading in a post is the chapter title we prepend. Without this
    a post whose body starts at h1 would split into several EPUB chapters."""
    out: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if not in_fence and _ATX_RE.match(line) and not line.startswith("######"):
            line = "#" + line
        out.append(line)
    return "\n".join(out)


def post_block(post: dict, tag_name: str) -> str:
    """One post as Markdown: a level-1 title (chapter), source + tags, then body."""
    slug = post["slug"]
    markdown = (WORK_DIR / slug / "article.md").read_text(encoding="utf-8")
    body = demote_headings(reroot_images(normalize_markdown(markdown), slug))

    title = (post.get("title") or slug).replace("\n", " ").strip()
    subs = post.get("subs", [])
    tag_bits = f'<span class="main">{escape(tag_name)}</span>'
    if subs:
        tag_bits += " · " + " · ".join(escape(s) for s in subs)

    # Raw-HTML paragraphs (own line, blank line before) become an HTML block we
    # can style by class; the '#' title stays a real heading for chaptering/TOC.
    return (
        f"# {title}\n\n"
        f'<p class="source">{escape(post["url"])}</p>\n'
        f'<p class="tags">{tag_bits}</p>\n\n'
        f"{body}\n"
    )


def build_markdown(posts: list[dict], tag_name: str) -> str:
    return "\n\n".join(post_block(p, tag_name) for p in posts)


def render_epub(markdown: str, title: str, run_date: str, output: Path) -> None:
    EPUB_CSS_FILE.write_text(EPUB_CSS, encoding="utf-8")
    cmd = [
        "pandoc",
        "-f", INPUT_FORMAT,
        "-t", "epub3",
        "--toc", "--toc-depth=1",
        "--css", str(EPUB_CSS_FILE),
        "--metadata", f"title={title}",
        "--metadata", "lang=en",
        "--metadata", f"date={run_date}",
        "--metadata", "creator=Scribe Infosec Blog",
        "-o", str(output),
    ]
    for font in EMBED_FONTS:
        cmd += ["--epub-embed-font", str(FONTS_DIR / font)]
    # cwd=WORK_DIR so the posts' relative image paths (slug/images/x) resolve and
    # Pandoc embeds them into the EPUB.
    subprocess.run(
        cmd, input=markdown, text=True, encoding="utf-8", cwd=WORK_DIR, check=True
    )


def main() -> None:
    use_utf8_stdout()
    manifest = load_manifest()
    if not manifest:
        print("No posts in manifest — nothing to build.")
        return

    now = dt.datetime.now(dt.timezone.utc)
    run_date = now.strftime("%Y-%m-%d")
    file_date = now.strftime("%d_%m_%Y")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    only = os.environ.get("PDF_ONLY_TAG")  # build a single tag (for previews)
    built: list[str] = []
    try:
        for tag_slug, posts in group_by_tag(manifest).items():
            if only and tag_slug != only:
                continue
            tag_name = TAG_DISPLAY.get(tag_slug, tag_slug.replace("-", " ").title())
            title = f"{tag_name} — {run_date}"
            label = tag_slug.upper().replace("-", "")
            output = DIST_DIR / f"{label}_{file_date}.epub"
            render_epub(build_markdown(posts, tag_name), title, run_date, output)
            built.append(str(output))
            print(f"Built {tag_slug} EPUB with {len(posts)} post(s): {output}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"EPUB build failed: {exc}", file=sys.stderr)
        sys.exit(1)

    set_github_output("epub_count", str(len(built)))
    print(f"\nBuilt {len(built)} tag EPUB(s) from {len(manifest)} post(s).")


if __name__ == "__main__":
    main()
