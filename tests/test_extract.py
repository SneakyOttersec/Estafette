from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from bs4 import BeautifulSoup

from extract import localize_images, prepare_html, restore_inline_assets


class PrepareHtmlTests(TestCase):
    def test_netspi_keeps_article_but_drops_feature_and_related_cards(self) -> None:
        html = """
        <html><body>
          <section id="header"><img src="https://cdn.example/hero.jpg" alt="Hero"></section>
          <div class="main-content"><div class="main">
            <p>Article body</p>
            <svg viewBox="0 0 10 10" role="img">
              <title>Architecture flow</title>
              <linearGradient id="fade" gradientUnits="userSpaceOnUse"></linearGradient>
              <path d="M0 0 L10 10"/>
            </svg>
          </div></div>
          <div class="tech-author"><p>Author biography</p></div>
          <section><h2>Explore More Blog Posts</h2>
            <img src="https://cdn.example/related.jpg" alt="Related">
          </section>
        </body></html>
        """

        with TemporaryDirectory() as tmp:
            post_dir = Path(tmp) / "post"
            prepared = prepare_html(
                html,
                "https://www.netspi.com/blog/technical-blog/example/",
                post_dir,
            )
            soup = BeautifulSoup(prepared, "lxml")

            self.assertIn("Article body", soup.get_text(" ", strip=True))
            self.assertNotIn("Author biography", soup.get_text(" ", strip=True))
            self.assertNotIn("Explore More Blog Posts", soup.get_text(" ", strip=True))
            self.assertIsNone(soup.find("img", src="https://cdn.example/hero.jpg"))
            self.assertIsNone(soup.find("img", src="https://cdn.example/related.jpg"))
            self.assertIsNone(soup.find("svg"))

            diagram = soup.find("img", alt="Architecture flow")
            self.assertIsNotNone(diagram)
            self.assertRegex(
                diagram["src"],
                r"^https://estafette\.invalid/inline-[0-9a-f]{12}\.png$",
            )
            relative_svg = restore_inline_assets(diagram["src"])
            svg_file = post_dir / relative_svg
            self.assertTrue(svg_file.exists())
            svg_text = svg_file.read_text(encoding="utf-8")
            self.assertIn("<svg", svg_text)
            self.assertIn('viewBox="0 0 10 10"', svg_text)
            self.assertIn("linearGradient", svg_text)
            self.assertIn('gradientUnits="userSpaceOnUse"', svg_text)

    def test_other_sites_are_unchanged(self) -> None:
        html = "<html><body><p>Original</p><svg></svg></body></html>"
        with TemporaryDirectory() as tmp:
            prepared = prepare_html(
                html, "https://example.com/post", Path(tmp) / "post"
            )
        self.assertEqual(prepared, html)


class LocalizeImagesTests(TestCase):
    def test_private_extraction_url_is_restored_to_local_svg(self) -> None:
        markdown = (
            "![Architecture flow]"
            "(https://estafette.invalid/inline-123456789abc.png)"
        )
        self.assertEqual(
            restore_inline_assets(markdown),
            "![Architecture flow](images/inline-123456789abc.svg)",
        )

    @patch("extract.download_image")
    def test_materialized_image_is_not_downloaded_again(self, download_image) -> None:
        markdown = "![Architecture flow](images/inline-123456789abc.svg)"
        with TemporaryDirectory() as tmp:
            localized = localize_images(
                markdown, "https://www.netspi.com/post", Path(tmp)
            )

        self.assertEqual(localized, markdown)
        download_image.assert_not_called()
