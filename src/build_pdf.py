"""Build a single dated PDF of this run's posts, styled for e-reader reading.

Pipeline: each post's Markdown -> HTML fragment (Pandoc), assembled into one
HTML document with a cover, a table of contents and per-post "chapters", then
rendered to PDF by WeasyPrint. The layout targets the Kindle Scribe reading
area (157x210 mm) with a warm-paper background, the Literata reading serif
(bundled, justified + hyphenated), running headers, and page numbers.

Output: dist/<YYYY-MM-DD>.pdf. Sets the GitHub Actions step output pdf_path.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
import sys
from html import escape
from pathlib import Path

from common import DIST_DIR, ROOT, TAG_DISPLAY, WORK_DIR, use_utf8_stdout

FONTS_DIR = ROOT / "fonts"
MANIFEST_FILE = WORK_DIR / "manifest.json"
MASTER_HTML = WORK_DIR / "master.html"

# Read post content as plain Markdown: don't interpret raw TeX or $-math (so
# arbitrary prose is preserved literally). raw_html stays on for embedded markup.
INPUT_FORMAT = (
    "markdown"
    "-raw_tex"
    "-tex_math_dollars"
    "-tex_math_single_backslash"
    "-tex_math_double_backslash"
)

_FENCE_RE = re.compile(r"^\s*```")
_LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s")


def normalize_markdown(markdown: str) -> str:
    """Strip stray 4+ space indentation that trafilatura leaves on block
    elements (images, headings, prose), which Pandoc would otherwise misread as
    indented code blocks. Fenced code and real list nesting are preserved."""
    out: list[str] = []
    in_fence = False
    for line in markdown.split("\n"):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
        elif (
            not in_fence
            and len(line) - len(line.lstrip(" ")) >= 4
            and not _LIST_ITEM_RE.match(line)
        ):
            out.append(line.lstrip(" "))
        else:
            out.append(line)
    return "\n".join(out)

# Rewrite per-post 'images/x' refs to 'slug/images/x' (relative to work/).
MD_LOCAL_IMAGE_RE = re.compile(r"(!\[[^\]]*\]\()(?P<url>images/[^)\s]+)(\))")


def font_face_css() -> str:
    def uri(name: str) -> str:
        return (FONTS_DIR / name).as_uri()

    return f"""
@font-face {{ font-family:'LM Roman'; font-weight:400; font-style:normal;
             src:url('{uri("lmroman10-regular.otf")}'); }}
@font-face {{ font-family:'LM Roman'; font-weight:400; font-style:italic;
             src:url('{uri("lmroman10-italic.otf")}'); }}
@font-face {{ font-family:'LM Roman'; font-weight:700; font-style:normal;
             src:url('{uri("lmroman10-bold.otf")}'); }}
@font-face {{ font-family:'LM Roman'; font-weight:700; font-style:italic;
             src:url('{uri("lmroman10-bolditalic.otf")}'); }}
@font-face {{ font-family:'LM Mono'; font-weight:400; font-style:normal;
             src:url('{uri("lmmono10-regular.otf")}'); }}
"""


STYLESHEET = """
@page {
    size: 157mm 210mm;            /* Kindle Scribe reading area */
    margin: 18mm 17mm 20mm 17mm;
    @top-center {
        content: string(chaptitle, first-except);
        font-family: 'LM Roman', serif; font-size: 8.5pt; font-style: italic;
        color: #555; padding-top: 7mm;
    }
    @bottom-center {
        content: counter(page);
        font-family: 'LM Roman', serif; font-size: 10pt; color: #333;
        padding-bottom: 7mm;
    }
}
@page :first { @top-center { content: none; } @bottom-center { content: none; } }

html { background: #fdfdfc; }
body {
    font-family: 'LM Roman', 'Latin Modern Roman', Georgia, serif;
    font-size: 11pt; line-height: 1.42; color: #111;
    text-align: justify; hyphens: auto;
}
/* LaTeX paragraph style: first-line indent, no blank line between paragraphs. */
p { margin: 0; text-indent: 1.6em; orphans: 2; widows: 2; }
/* No indent on the first paragraph after a heading or block (LaTeX behaviour). */
h1 + p, h2 + p, h3 + p, h4 + p,
.chapter-head + p, figure + p, pre + p, blockquote + p, ul + p, ol + p,
table + p { text-indent: 0; }
a { color: #1a1a1a; text-decoration: none; border-bottom: 0.5pt solid #aaa;
    word-break: break-word; }
strong, b { font-weight: 700; }
em, i { font-style: italic; }

/* Title page — LaTeX \\maketitle feel */
.cover { page-break-after: always; text-align: center; padding-top: 62mm; }
.cover .kicker { font-size: 10.5pt; font-style: italic; color: #333;
                 margin-bottom: 6mm; }
.cover .title { font-size: 30pt; font-weight: 700; line-height: 1.1;
                margin: 0 auto 5mm; padding: 4mm 0;
                border-top: 0.4pt solid #222; border-bottom: 0.4pt solid #222;
                width: 80%; }
.cover .date { font-size: 12pt; color: #222; }
.cover .subtags { font-size: 10pt; font-style: italic; color: #555;
                  margin: 7mm auto 0; width: 80%; }

/* Table of contents — LaTeX \\tableofcontents */
.toc { page-break-after: always; }
.toc h2 { font-size: 17pt; font-weight: 700; margin: 0 0 8mm; text-indent: 0; }
.toc ol { list-style: none; padding: 0; margin: 0; counter-reset: toc; }
.toc li { margin: 0 0 2.6mm; font-size: 11pt; line-height: 1.3; }
.toc a { color: #111; text-decoration: none; border: none; }
.toc a::before { counter-increment: toc; content: counter(toc) "\\00a0\\00a0";
                 font-weight: 700; }
.toc a::after { content: leader('.\\00a0') target-counter(attr(href url), page); }

/* Each post = a numbered LaTeX \\section */
body { counter-reset: sec; }
.chapter { page-break-before: always; counter-reset: sub; }
.chapter-head { margin-bottom: 6mm; }
.chapter-head h1 {
    string-set: chaptitle content(text);
    counter-increment: sec;
    font-size: 20pt; font-weight: 700; line-height: 1.2;
    margin: 0 0 2mm; padding-top: 4mm; text-indent: 0;
}
.chapter-head h1::before { content: counter(sec) "\\2003"; }
.source { font-size: 8.5pt; font-style: italic; color: #666; margin: 0;
          text-indent: 0; word-break: break-all; }
.tags { font-size: 8.5pt; color: #444; margin: 1.5mm 0 0; text-indent: 0;
        letter-spacing: 0.3px; }
.tags .main { font-weight: 700; }

/* Body headings -> LaTeX \\subsection / \\subsubsection (numbered within post) */
h2, h3, h4, h5, h6 { font-weight: 700; text-indent: 0; break-after: avoid;
                     line-height: 1.25; }
h2 { font-size: 14pt; margin: 6mm 0 2mm; }
h3 { font-size: 12pt; margin: 4.5mm 0 1.5mm; }
h4, h5, h6 { font-size: 11pt; margin: 3.5mm 0 1mm; }
.chapter h2 { counter-increment: sub; counter-reset: subsub; }
.chapter h3 { counter-increment: subsub; }
.chapter h2::before { content: counter(sec) "." counter(sub) "\\2003"; }
.chapter h3::before { content: counter(sec) "." counter(sub) "." counter(subsub) "\\2003"; }

/* Code — Latin Modern Mono, verbatim-style */
pre, code, kbd, samp { font-family: 'LM Mono', 'DejaVu Sans Mono', monospace; }
code { font-size: 9.3pt; }
pre {
    background: #f4f4f2; border: 0.5pt solid #ccc;
    padding: 6px 8px; font-size: 8.6pt; line-height: 1.34;
    white-space: pre-wrap; word-break: break-all; overflow-wrap: anywhere;
    text-align: left; hyphens: none; text-indent: 0;
}
pre code { background: none; padding: 0; font-size: inherit; }

/* Media — LaTeX figure feel */
img { max-width: 100%; height: auto; }
figure { margin: 5mm 0; text-align: center; }
figcaption { font-size: 9pt; color: #333; margin-top: 1.5mm; }

/* Tables */
table { border-collapse: collapse; width: 100%; margin: 4mm 0; font-size: 9pt; }
th, td { border: 0.5pt solid #bbb; padding: 3px 6px; text-align: left;
         vertical-align: top; word-break: break-word; }
th { background: #efefee; }

blockquote { border-left: 2pt solid #bbb; margin: 4mm 0; padding: 0.5mm 0 0.5mm 5mm;
             color: #333; }
blockquote p { text-indent: 0; }
hr { border: none; border-top: 0.5pt solid #ccc; margin: 6mm 0; }
ul, ol { margin: 1mm 0 2mm; padding-left: 7mm; }
li { margin: 0 0 0.8mm; }
"""


def load_manifest() -> list[dict]:
    if not MANIFEST_FILE.exists():
        return []
    return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))


def reroot_images(markdown: str, slug: str) -> str:
    return MD_LOCAL_IMAGE_RE.sub(
        lambda m: f"{m.group(1)}{slug}/{m.group('url')}{m.group(3)}", markdown
    )


def md_to_fragment(markdown: str) -> str:
    """Convert one post's Markdown to an HTML fragment via Pandoc."""
    result = subprocess.run(
        ["pandoc", "-f", INPUT_FORMAT, "-t", "html5"],
        input=markdown,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=WORK_DIR,
        check=True,
    )
    return result.stdout


def build_html(manifest: list[dict], run_date: str, tag_slug: str) -> str:
    tag_name = TAG_DISPLAY.get(tag_slug, tag_slug.replace("-", " ").title())
    chapters: list[str] = []
    toc_items: list[str] = []
    all_subs: list[str] = []
    for i, post in enumerate(manifest, start=1):
        slug = post["slug"]
        pid = f"post-{i}"
        markdown = (WORK_DIR / slug / "article.md").read_text(encoding="utf-8")
        fragment = md_to_fragment(reroot_images(normalize_markdown(markdown), slug))
        title = escape(post["title"])
        url = escape(post["url"])
        subs = post.get("subs", [])
        all_subs.extend(subs)
        tag_bits = f'<span class="main">{escape(tag_name)}</span>'
        if subs:
            tag_bits += " · " + " · ".join(escape(s) for s in subs)
        chapters.append(
            f'<section class="chapter" id="{pid}">'
            f'<div class="chapter-head"><h1>{title}</h1>'
            f'<p class="source">{url}</p>'
            f'<p class="tags">{tag_bits}</p></div>\n{fragment}\n</section>'
        )
        toc_items.append(f'<li><a href="#{pid}">{title}</a></li>')

    # Distinct sub-tags across this tag's posts, shown on the cover.
    seen, distinct_subs = set(), []
    for s in all_subs:
        if s not in seen:
            seen.add(s)
            distinct_subs.append(s)
    subtags_line = (
        f'<div class="subtags">{escape(" · ".join(distinct_subs))}</div>'
        if distinct_subs else ""
    )

    cover = (
        '<section class="cover">'
        '<div class="kicker">Security Reading</div>'
        f'<div class="title">{escape(tag_name)}</div>'
        f'<div class="date">{run_date}</div>'
        f"{subtags_line}</section>"
    )
    toc = (
        '<nav class="toc"><h2>Contents</h2><ol>' + "".join(toc_items) + "</ol></nav>"
    )
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
        f"<title>{escape(tag_name)} — {run_date}</title></head><body>"
        f"{cover}{toc}{''.join(chapters)}</body></html>"
    )


def render_pdf(output: Path) -> None:
    # Imported lazily so the HTML step can run on machines without WeasyPrint's
    # native libraries; CI (and a configured local box) has them.
    from weasyprint import CSS, HTML
    from weasyprint.text.fonts import FontConfiguration

    font_config = FontConfiguration()
    css = CSS(string=font_face_css() + STYLESHEET, font_config=font_config)
    HTML(filename=str(MASTER_HTML)).write_pdf(
        str(output), stylesheets=[css], font_config=font_config
    )


def set_github_output(name: str, value: str) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def group_by_tag(manifest: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for post in manifest:
        groups.setdefault(post.get("tag") or "general", []).append(post)
    # Order: the known main tags first (in TAG_DISPLAY order), then any others.
    ordered = list(TAG_DISPLAY) + [t for t in groups if t not in TAG_DISPLAY]
    return {t: groups[t] for t in ordered if t in groups}


def main() -> None:
    use_utf8_stdout()
    manifest = load_manifest()
    if not manifest:
        print("No posts in manifest — nothing to build.")
        return

    run_date = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    built: list[str] = []
    try:
        for tag_slug, posts in group_by_tag(manifest).items():
            MASTER_HTML.write_text(
                build_html(posts, run_date, tag_slug), encoding="utf-8"
            )
            output = DIST_DIR / f"{run_date}-{tag_slug}.pdf"
            render_pdf(output)
            built.append(str(output))
            print(f"Built {tag_slug} PDF with {len(posts)} post(s): {output}")
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"PDF build failed: {exc}", file=sys.stderr)
        sys.exit(1)

    set_github_output("pdf_count", str(len(built)))
    print(f"\nBuilt {len(built)} tag PDF(s) from {len(manifest)} post(s).")


if __name__ == "__main__":
    main()
