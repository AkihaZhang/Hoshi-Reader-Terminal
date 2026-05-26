from pathlib import Path
import tempfile
import unittest
import zipfile

from hoshi_terminal.epub import extract_book, strip_html


class EpubExtractionTests(unittest.TestCase):
    def test_strip_html_preserves_text(self) -> None:
        self.assertEqual(strip_html("<h1>Title</h1><p>読む 星</p>"), "Title\n読む 星")

    def test_extract_minimal_epub(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.epub"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("mimetype", "application/epub+zip")
                archive.writestr(
                    "META-INF/container.xml",
                    """<?xml version="1.0"?>
                    <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
                      <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
                    </container>""",
                )
                archive.writestr(
                    "OEBPS/content.opf",
                    """<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
                      <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Terminal Book</dc:title></metadata>
                      <manifest><item id="c1" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>
                      <spine><itemref idref="c1"/></spine>
                    </package>""",
                )
                archive.writestr("OEBPS/chapter.xhtml", "<html><body><p>端末で読む。</p></body></html>")

            book = extract_book(path)

        self.assertEqual(book.title, "Terminal Book")
        self.assertIn("端末で読む", book.text)


if __name__ == "__main__":
    unittest.main()
