"""Package the generated PDFs into one public weekly ZIP bundle."""

from __future__ import annotations

import os
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from common import DIST_DIR, use_utf8_stdout

DATE_SUFFIX = re.compile(r"_(\d{2}_\d{2}_\d{4})\.pdf$", re.IGNORECASE)


def package_downloads(dist_dir: Path = DIST_DIR) -> Path:
    pdfs = sorted(dist_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs found in {dist_dir}")

    match = DATE_SUFFIX.search(pdfs[0].name)
    date_label = match.group(1) if match else "LATEST"
    output = dist_dir / f"ESTAFETTE_{date_label}.zip"

    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for pdf in pdfs:
            archive.write(pdf, arcname=pdf.name)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output_file:
            output_file.write(f"zip_path={output}\n")

    return output


def main() -> None:
    use_utf8_stdout()
    output = package_downloads()
    print(f"Packaged weekly downloads: {output}")


if __name__ == "__main__":
    main()
