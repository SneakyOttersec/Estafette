from zipfile import ZipFile

from package_downloads import package_downloads


def test_package_downloads_bundles_every_pdf_without_dist_prefix(tmp_path):
    first = tmp_path / "OFFENSIVE_24_08_2026.pdf"
    second = tmp_path / "REDTEAM_24_08_2026.pdf"
    first.write_bytes(b"first PDF")
    second.write_bytes(b"second PDF")

    output = package_downloads(tmp_path)

    assert output.name == "ESTAFETTE_24_08_2026.zip"
    with ZipFile(output) as archive:
        assert archive.namelist() == [first.name, second.name]
        assert archive.read(first.name) == b"first PDF"


def test_package_downloads_requires_a_pdf(tmp_path):
    try:
        package_downloads(tmp_path)
    except FileNotFoundError as error:
        assert "No PDFs found" in str(error)
    else:
        raise AssertionError("package_downloads should reject an empty directory")
