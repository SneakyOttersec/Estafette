# Bundled fonts

**Latin Modern** — the OpenType version of Donald Knuth's Computer Modern, the
typeface that gives the PDF its classic LaTeX look. Licensed under the GUST Font
License (a free, LPPL-style license).

- `lmroman10-regular/italic/bold/bolditalic.otf` — body text and headings
- `lmmono10-regular.otf` — code blocks

Downloaded from CTAN (`fonts/lm/fonts/opentype/public/lm`). Referenced via
`@font-face` in `src/build_pdf.py` so the PDF renders identically locally and in
CI without any system font install.
