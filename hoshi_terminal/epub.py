from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote
import re
import xml.etree.ElementTree as ET
import zipfile


SUPPORTED_TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".html", ".htm", ".xhtml", ".xml"}


@dataclass(frozen=True)
class Chapter:
    title: str
    text: str


@dataclass(frozen=True)
class ExtractedBook:
    title: str
    chapters: list[Chapter]

    @property
    def text(self) -> str:
        return "\n\n".join(chapter.text for chapter in self.chapters if chapter.text.strip())


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "math", "rt"}:
            self.skip_depth += 1
            return
        if tag in {"p", "div", "section", "article", "header", "footer", "li", "tr", "h1", "h2", "h3"}:
            self._newline()
        if tag == "br":
            self._newline()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "svg", "math", "rt"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}:
            self._newline()

    def handle_data(self, data: str) -> None:
        if self.skip_depth:
            return
        collapsed = re.sub(r"\s+", " ", data)
        if collapsed.strip():
            self.parts.append(collapsed)

    def _newline(self) -> None:
        if self.parts and self.parts[-1] != "\n":
            self.parts.append("\n")

    def get_text(self) -> str:
        text = "".join(self.parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def strip_html(raw: str) -> str:
    parser = TextExtractor()
    parser.feed(raw)
    parser.close()
    return parser.get_text()


def extract_book(path: str | Path) -> ExtractedBook:
    book_path = Path(path)
    suffix = book_path.suffix.lower()
    if suffix == ".epub":
        return extract_epub(book_path)
    if suffix in SUPPORTED_TEXT_SUFFIXES:
        return extract_text_file(book_path)
    raise ValueError(f"Unsupported book type: {book_path.suffix or 'no suffix'}")


def extract_text_file(path: Path) -> ExtractedBook:
    raw = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix.lower() in {".html", ".htm", ".xhtml", ".xml"}:
        text = strip_html(raw)
    else:
        text = raw.strip()
    title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
    return ExtractedBook(title=title, chapters=[Chapter(title=title, text=text)])


def extract_epub(path: Path) -> ExtractedBook:
    with zipfile.ZipFile(path) as archive:
        rootfile = _find_rootfile(archive)
        opf_bytes = archive.read(rootfile)
        opf = ET.fromstring(opf_bytes)
        title = _first_text(opf, ".//{*}metadata/{*}title") or path.stem
        manifest = _manifest(opf)
        spine_ids = _spine(opf)
        base = PurePosixPath(rootfile).parent
        chapters: list[Chapter] = []

        for index, item_id in enumerate(spine_ids, start=1):
            href = manifest.get(item_id)
            if not href:
                continue
            member = _resolve_member(base, href)
            if member not in archive.namelist():
                continue
            raw = archive.read(member).decode("utf-8", errors="replace")
            text = strip_html(raw)
            if text:
                chapters.append(Chapter(title=f"Chapter {index}", text=text))

        if not chapters:
            chapters = _fallback_html_chapters(archive)

    if not chapters:
        raise ValueError(f"No readable text found in EPUB: {path}")
    return ExtractedBook(title=title.strip() or path.stem, chapters=chapters)


def _find_rootfile(archive: zipfile.ZipFile) -> str:
    try:
        container = ET.fromstring(archive.read("META-INF/container.xml"))
    except KeyError as exc:
        raise ValueError("EPUB is missing META-INF/container.xml") from exc
    rootfile = container.find(".//{*}rootfile")
    if rootfile is None or not rootfile.attrib.get("full-path"):
        raise ValueError("EPUB container has no rootfile")
    return rootfile.attrib["full-path"]


def _first_text(root: ET.Element, pattern: str) -> str | None:
    found = root.find(pattern)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _manifest(opf: ET.Element) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in opf.findall(".//{*}manifest/{*}item"):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if item_id and href:
            result[item_id] = href
    return result


def _spine(opf: ET.Element) -> list[str]:
    ids: list[str] = []
    for itemref in opf.findall(".//{*}spine/{*}itemref"):
        item_id = itemref.attrib.get("idref")
        if item_id:
            ids.append(item_id)
    return ids


def _resolve_member(base: PurePosixPath, href: str) -> str:
    without_fragment = href.split("#", 1)[0]
    decoded = unquote(without_fragment)
    if str(base) == ".":
        return str(PurePosixPath(decoded))
    return str(base / decoded)


def _fallback_html_chapters(archive: zipfile.ZipFile) -> list[Chapter]:
    chapters: list[Chapter] = []
    candidates = [
        name
        for name in archive.namelist()
        if name.lower().endswith((".html", ".htm", ".xhtml"))
    ]
    for index, name in enumerate(sorted(candidates), start=1):
        raw = archive.read(name).decode("utf-8", errors="replace")
        text = strip_html(raw)
        if text:
            chapters.append(Chapter(title=f"Chapter {index}", text=text))
    return chapters
