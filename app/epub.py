"""Read an EPUB book without a dependency.

An EPUB is a zip of XHTML documents plus a package document that says in which
order to read them (the spine) and what the book's own table of contents calls
its chapters. The app already knows how to work with a page of text at known
positions, so a book is converted into a synthetic PDF at import — the same
trick a .pptx goes through: page images, selection, highlights, objectives and
figure crops keep working.

Two things are taken from the EPUB itself rather than guessed later:

* the **spine** gives the reading order, so pages are not alphabetical;
* the **table of contents** (the EPUB 3 ``nav`` document or the EPUB 2
  ``toc.ncx``) becomes the PDF's outline, so ``chapters.py`` sees the real
  chapter titles instead of matching "Chapter 3" lines.

The text of every line is also returned with its position, so the stored page
text is the book's own words — not whatever a PDF text layer happened to
recover. That keeps ligatures, accents and non-Latin scripts intact; symbols
the chosen font has no glyph for appear as nothing on the rendered page but
still reach the model.

Only reading text is kept: headings, paragraphs, lists, tables and captions.
Fonts, colours, images and page layout are dropped — the page images Anki
Scribe shows are a rendering of the text that was written, which is what a
selection needs.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

import pymupdf

# A4 at 72 dpi. The page is a container for text, not a reproduction of the
# book: what matters is that a line is wide enough to read and a page holds a
# useful amount of it.
PAGE_WIDTH = 595.0
PAGE_HEIGHT = 842.0
MARGIN_X = 56.0
MARGIN_TOP = 56.0
MARGIN_BOTTOM = 56.0

BODY_SIZE = 10.5
LINE_FACTOR = 1.35
HEADING_GAP = 7.0
_HEADING_SIZES = {"h1": 16.0, "h2": 13.5, "h3": 12.0, "h4": 11.0, "h5": 10.5, "h6": 10.5}

MAX_PAGES = 1500
MAX_TITLE = 120

_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = _HEADING_TAGS | {
    "p",
    "div",
    "li",
    "blockquote",
    "dd",
    "dt",
    "pre",
    "figcaption",
    "caption",
    "tr",
}
_SKIP_TAGS = {"script", "style", "head", "nav", "svg", "math", "template", "noscript"}
# Only this range needs a Unicode font; the Latin-1 block (accented letters,
# curly quotes, dashes) is covered by the built-in Helvetica.
_RTL = re.compile(r"[\u0590-\u08ff\ufb1d-\ufdff\ufe70-\ufefc]")
_HEBREW = re.compile(r"[\u0590-\u05ff\ufb1d-\ufb4f]")

# Microsoft's core fonts are on every Windows install and cover Latin, Greek,
# Cyrillic and Arabic. If none are found the built-in font is used and the
# text still reaches the model — only the rendered page loses the glyphs.
_FONT_CANDIDATES = (
    (
        Path(r"C:\Windows\Fonts\arial.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf"),
    ),
    (
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ),
)


# -- XML helpers -------------------------------------------------------


def _local(tag: str) -> str:
    """The tag without its namespace: EPUB 2 and 3 disagree on namespaces."""
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _all(element, name: str) -> list:
    return [node for node in element.iter() if _local(node.tag) == name]


def _first(element, name: str):
    for node in element.iter():
        if _local(node.tag) == name:
            return node
    return None


def _attr(element, name: str) -> str | None:
    for key, value in element.attrib.items():
        if _local(key) == name:
            return value
    return None


def _text_of(element) -> str:
    if element is None:
        return ""
    return re.sub(r"\s+", " ", "".join(element.itertext())).strip()


def _clean_title(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:MAX_TITLE]


def _resolve(base: str, href: str) -> str:
    """An archive path for an href found inside ``base``'s folder."""
    href = unquote((href or "").split("#", 1)[0]).strip()
    if not href:
        return ""
    if href.startswith("/"):
        return posixpath.normpath(href.lstrip("/"))
    return posixpath.normpath(posixpath.join(base, href)) if base else posixpath.normpath(href)


def _split_fragment(href: str) -> tuple[str, str]:
    path, _, fragment = (href or "").partition("#")
    return unquote(path).strip(), unquote(fragment).strip()


# -- package document --------------------------------------------------


def _rootfile(archive: zipfile.ZipFile) -> str:
    try:
        data = archive.read("META-INF/container.xml")
    except KeyError:
        candidates = sorted(
            name for name in archive.namelist() if name.lower().endswith(".opf")
        )
        if candidates:
            return candidates[0]
        raise ValueError("That file isn't an EPUB (it has no META-INF/container.xml).")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("That EPUB's container.xml is damaged.") from exc
    for element in root.iter():
        if _local(element.tag) == "rootfile":
            path = (_attr(element, "full-path") or "").strip()
            if path:
                return path.lstrip("/")
    raise ValueError("That EPUB has no package document (.opf).")


def _read_package(archive: zipfile.ZipFile, opf_path: str) -> dict:
    try:
        data = archive.read(opf_path)
    except KeyError as exc:
        raise ValueError(f"That EPUB is missing its package document ({opf_path}).") from exc
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError("That EPUB's package document is damaged.") from exc

    folder = posixpath.dirname(opf_path)
    manifest: dict[str, dict] = {}
    for item in _all(root, "item"):
        item_id = _attr(item, "id")
        href = _attr(item, "href")
        if not item_id or not href:
            continue
        manifest[item_id] = {
            "href": _resolve(folder, href),
            "type": (_attr(item, "media-type") or "").lower(),
            "properties": (_attr(item, "properties") or "").lower().split(),
        }

    spine: list[tuple[str, bool]] = []
    for itemref in _all(root, "itemref"):
        idref = _attr(itemref, "idref")
        if not idref:
            continue
        linear = (_attr(itemref, "linear") or "yes").lower() != "no"
        spine.append((idref, linear))

    metadata = _first(root, "metadata")
    return {
        "manifest": manifest,
        "spine": spine,
        "title": _text_of(_first(metadata, "title")) if metadata is not None else "",
        "author": _text_of(_first(metadata, "creator")) if metadata is not None else "",
    }


def _spine_documents(package: dict) -> list[str]:
    documents: list[str] = []
    seen: set[str] = set()
    for idref, linear in package["spine"]:
        if not linear:
            continue
        item = package["manifest"].get(idref)
        if item is None or not item["href"]:
            continue
        is_markup = item["type"] in ("", "application/xhtml+xml", "text/html", "application/xml")
        if not is_markup and not item["href"].lower().endswith((".xhtml", ".html", ".htm")):
            continue
        if item["href"] in seen:
            continue
        seen.add(item["href"])
        documents.append(item["href"])
    return documents


# -- table of contents -------------------------------------------------


def _toc_from_nav(archive: zipfile.ZipFile, package: dict) -> list[dict]:
    nav_item = next(
        (item for item in package["manifest"].values() if "nav" in item["properties"]),
        None,
    )
    if nav_item is None or not nav_item["href"]:
        return []
    try:
        root = ET.fromstring(archive.read(nav_item["href"]))
    except (KeyError, ET.ParseError):
        return []
    base = posixpath.dirname(nav_item["href"])
    navs = _all(root, "nav")
    chosen = None
    for nav in navs:
        kind = (_attr(nav, "type") or "").lower()
        role = (_attr(nav, "role") or "").lower()
        if kind == "toc" or role == "doc-toc":
            chosen = nav
            break
    if chosen is None and navs:
        chosen = navs[0]
    if chosen is None:
        return []

    entries: list[dict] = []

    def walk(element, level: int) -> None:
        lists = [node for node in element if _local(node.tag) in ("ol", "ul")]
        if not lists:
            nested = _first(element, "ol")
            lists = [nested] if nested is not None else []
        for ordered_list in lists:
            for item in [node for node in ordered_list if _local(node.tag) == "li"]:
                # Only the item's own label counts: the first link found by a
                # deep search belongs to a child list, which would rename a
                # "Part II" heading after its first chapter.
                link = next((node for node in item if _local(node.tag) == "a"), None)
                if link is not None:
                    href = _attr(link, "href") or ""
                    title = _text_of(link)
                else:
                    label = next(
                        (node for node in item if _local(node.tag) == "span"), None
                    )
                    href = ""
                    title = _text_of(label) if label is not None else ""
                if title:
                    path, fragment = _split_fragment(href)
                    entries.append(
                        {
                            "level": level,
                            "title": _clean_title(title),
                            "href": _resolve(base, path),
                            "fragment": fragment,
                        }
                    )
                walk(item, level + 1)

    walk(chosen, 1)
    return entries


def _toc_from_ncx(archive: zipfile.ZipFile, package: dict) -> list[dict]:
    ncx_item = next(
        (
            item
            for item in package["manifest"].values()
            if item["type"] == "application/x-dtbncx+xml"
            or item["href"].lower().endswith(".ncx")
        ),
        None,
    )
    if ncx_item is None:
        candidates = sorted(name for name in archive.namelist() if name.lower().endswith(".ncx"))
        if not candidates:
            return []
        ncx_item = {"href": candidates[0]}
    try:
        root = ET.fromstring(archive.read(ncx_item["href"]))
    except (KeyError, ET.ParseError):
        return []
    base = posixpath.dirname(ncx_item["href"])
    entries: list[dict] = []

    def walk(element, level: int) -> None:
        for point in [node for node in element if _local(node.tag) == "navPoint"]:
            label = _first(point, "navLabel")
            title = _clean_title(_text_of(_first(label, "text")) if label is not None else "")
            content = _first(point, "content")
            href = _attr(content, "src") if content is not None else ""
            if title:
                path, fragment = _split_fragment(href or "")
                entries.append(
                    {
                        "level": level,
                        "title": title,
                        "href": _resolve(base, path),
                        "fragment": fragment,
                    }
                )
            walk(point, level + 1)

    nav_map = _first(root, "navMap")
    if nav_map is not None:
        walk(nav_map, 1)
    return entries


_CHAPTER_WORD = re.compile(
    r"^(?:chapter|part|unit|section|module|book|volume|lesson|lecture)\b",
    re.IGNORECASE,
)
# A contents page lists its own front and back matter too. Those entries are
# navigation, not chapters: a deck called "Cover" or "Index" is never useful.
_NOISE_TITLE = re.compile(
    r"^(?:cover|half[- ]?title|title page|front matter|copyright|dedication|"
    r"epigraph|contents|table of contents|also by|about this (?:book|ebook)|"
    r"about the author|acknowledg|permissions|credits|colophon|index|"
    r"bibliography|references|glossary)\b",
    re.IGNORECASE,
)


_EXACT_NOISE = {
    "content",
    "contents",
    "table of contents",
    "cover",
    "copyright",
    "dedication",
    "half-title",
    "half title",
    "title page",
    "front matter",
    "index",
    "references",
    "bibliography",
    "glossary",
    "colophon",
}


def _looks_like_chapter(title: str) -> bool:
    return bool(_CHAPTER_WORD.match((title or "").strip()))


def _drop_noise(entries: list[dict]) -> list[dict]:
    kept = [
        entry
        for entry in entries
        if entry["title"].strip().casefold() not in _EXACT_NOISE
        and not _NOISE_TITLE.match(entry["title"].strip())
    ]
    return kept if len(kept) >= 2 else entries


def _chapter_entries(entries: list[dict]) -> list[dict]:
    """Pick the contents level that reads as "chapters" and drop its noise.

    A book's contents nest parts over chapters over sections. The chapter level
    is the deepest one that still describes a manageable number of units: a
    handful of parts is too coarse, two hundred sections too fine, and a level
    whose titles announce themselves ("Chapter 7", "Part II") is trusted even
    when it is larger. The whole level is kept — a book whose chapters are
    "Strategy one…", with "Appendix A" as its tail, must not split into the
    appendices alone.
    """
    if len(entries) <= 1:
        return entries
    by_level: dict[int, list[dict]] = {}
    for entry in entries:
        by_level.setdefault(int(entry["level"]), []).append(entry)
    levels = sorted(by_level)
    for level in reversed(levels):
        group = by_level[level]
        if not 2 <= len(group) <= 80:
            continue
        named = sum(1 for entry in group if _looks_like_chapter(entry["title"]))
        if named >= 2 or len(group) <= 60:
            return _drop_noise(group)
    return _drop_noise(by_level[levels[0]])


# -- XHTML text --------------------------------------------------------


class _TextParser(HTMLParser):
    """Collect the readable blocks of one XHTML document, with their anchors."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[dict] = []
        self._buffer: list[str] = []
        self._anchors: list[str] = []
        self._skip = 0
        self._kind = "p"
        self._cells = 0
        self._table_depth = 0
        self._table_rows = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attributes = {name.lower(): value for name, value in attrs}
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        anchor = attributes.get("id") or (attributes.get("name") if tag == "a" else None)
        if tag == "table":
            self._flush()
            self._table_depth += 1
            self._table_rows = 0
            if anchor:
                self._anchors.append(anchor)
            return
        if tag in ("td", "th"):
            self._cells += 1
            if self._cells > 1:
                self._buffer.append(" | ")
            if anchor:
                self._anchors.append(anchor)
            return
        if tag in _BLOCK_TAGS:
            self._flush()
            self._kind = tag
            self._cells = 0
        elif tag == "br":
            self._flush()
        if anchor:
            self._anchors.append(anchor)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "table":
            self._flush()
            self._table_depth = max(0, self._table_depth - 1)
            return
        if tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data):
        if self._skip or not data:
            return
        self._buffer.append(data)

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buffer)).strip()
        self._buffer = []
        if not text:
            # An anchor can arrive before the block it belongs to; keep it.
            return
        if self._table_depth and self._kind == "tr":
            # Rows become a Markdown grid, so a table survives the page layout
            # and reaches the model as cells instead of one run-on sentence.
            cells = [cell.strip() for cell in text.split("|")]
            row = "| " + " | ".join(cells) + " |"
            self.blocks.append({"kind": "table", "text": row, "anchors": self._anchors})
            if self._table_rows == 0:
                self.blocks.append(
                    {
                        "kind": "table",
                        "text": "| " + " | ".join(["---"] * len(cells)) + " |",
                        "anchors": [],
                    }
                )
            self._table_rows += 1
            self._anchors = []
            self._kind = "p"
            return
        self.blocks.append(
            {"kind": self._kind, "text": text, "anchors": self._anchors}
        )
        self._anchors = []
        self._kind = "p"


def _document_blocks(archive: zipfile.ZipFile, href: str) -> list[dict]:
    try:
        data = archive.read(href)
    except KeyError:
        return []
    parser = _TextParser()
    try:
        parser.feed(_decode(data))
        parser.close()
    except Exception:  # html.parser is lenient; never lose what was parsed
        pass
    return parser.blocks


def _decode(data: bytes) -> str:
    """EPUB markup is UTF-8 (or UTF-16); damaged bytes must not lose the book."""
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", "replace")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    return data.decode("utf-8", "replace")


def _heading_toc(documents: dict[str, list[dict]]) -> list[dict]:
    """A last-resort contents list: the first heading of each document."""
    entries: list[dict] = []
    for href, blocks in documents.items():
        for block in blocks:
            if block["kind"] in _HEADING_TAGS:
                entries.append(
                    {
                        "level": 1,
                        "title": _clean_title(block["text"]),
                        "href": href,
                        "fragment": block["anchors"][0] if block["anchors"] else "",
                    }
                )
                break
    return entries if len(entries) >= 2 else []


# -- layout ------------------------------------------------------------


class _Metrics:
    """Character advances for one font at one size.

    ``Font.text_length`` re-encodes every character through MuPDF on every
    call — roughly 11 microseconds each — which turns measuring a 600-page
    book into most of a minute. An advance is constant per glyph, so it is
    read once and kept.
    """

    def __init__(self, font: "pymupdf.Font", size: float) -> None:
        self.font = font
        self.size = size
        self._advances: dict[str, float] = {}

    def char(self, character: str) -> float:
        width = self._advances.get(character)
        if width is None:
            try:
                width = float(self.font.glyph_advance(ord(character))) * self.size
            except Exception:  # a glyph the font cannot name still needs width
                width = self.size * 0.5
            self._advances[character] = width
        return width

    def text(self, value: str) -> float:
        return sum(self.char(character) for character in value)


def _wrap(text: str, metrics: "_Metrics", width: float) -> list[str]:
    space = metrics.text(" ") or metrics.size * 0.25
    lines: list[str] = []
    current: list[str] = []
    current_width = 0.0

    def flush() -> None:
        nonlocal current, current_width
        if current:
            lines.append(" ".join(current))
        current, current_width = [], 0.0

    for word in text.split(" "):
        if not word:
            continue
        word_width = metrics.text(word)
        if word_width > width:
            flush()
            lines.extend(_split_word(word, metrics, width))
            continue
        addition = word_width + (space if current else 0.0)
        if current and current_width + addition > width:
            flush()
            current, current_width = [word], word_width
        else:
            current.append(word)
            current_width += addition
    flush()
    return lines or [""]


def _split_word(word: str, metrics: "_Metrics", width: float) -> list[str]:
    """Break a word that is wider than the page (URLs, unspaced scripts)."""
    pieces: list[str] = []
    remaining = word
    guard = 0
    while remaining and guard < 400:
        guard += 1
        low, high = 1, len(remaining)
        while low < high:
            middle = (low + high + 1) // 2
            if metrics.text(remaining[:middle]) <= width:
                low = middle
            else:
                high = middle - 1
        pieces.append(remaining[:low])
        remaining = remaining[low:]
    return pieces


class _Layout:
    """Write blocks onto A4 pages, one text line at a time.

    Text is placed line by line rather than through ``insert_textbox`` so the
    line that was written is exactly the line that is stored: the page text can
    then be the book's own characters, in reading order, whatever the font.
    """

    def __init__(self, pdf, regular, bold, scale: float) -> None:
        self.pdf = pdf
        self.regular = regular
        self.bold = bold
        self.scale = scale
        self.page = None
        self.writer = None
        self.y = MARGIN_TOP
        self.pages: list[list[dict]] = []
        self._metrics: dict[tuple[int, float], _Metrics] = {}

    def _measure(self, font, size: float) -> "_Metrics":
        key = (id(font), size)
        metrics = self._metrics.get(key)
        if metrics is None:
            metrics = _Metrics(font, size)
            self._metrics[key] = metrics
        return metrics

    # -- pages ---------------------------------------------------------

    def _new_page(self) -> None:
        self._flush()
        self.page = self.pdf.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.writer = pymupdf.TextWriter(self.page.rect)
        self.pages.append([])
        self.y = MARGIN_TOP

    def _flush(self) -> None:
        if self.writer is not None and self.page is not None:
            self.writer.write_text(self.page)
        self.writer = None

    def close(self) -> None:
        self._flush()

    def page_break(self) -> None:
        """Start a new page unless the current one is still empty.

        A printed book starts every chapter on a fresh page. Keeping that
        convention is also what makes a chapter a *page range*: without it two
        short chapters share a page and cannot be split apart.
        """
        if self.page is not None and self.pages[self.index]:
            self._new_page()

    @property
    def index(self) -> int:
        return len(self.pages) - 1

    @property
    def next_page(self) -> int:
        """Where the next character written will land (0-based)."""
        return len(self.pages) if self.page is None else max(0, len(self.pages) - 1)

    # -- blocks --------------------------------------------------------

    def place(self, text: str, kind: str) -> int | None:
        """Lay out one block and return the page its first line landed on."""
        if not text:
            return None
        if self.page is None:
            self._new_page()
        heading = kind in _HEADING_TAGS
        size = _HEADING_SIZES.get(kind, BODY_SIZE)
        font = self.bold if heading else self.regular
        if heading and self.y > MARGIN_TOP:
            self.y += HEADING_GAP

        step = size * LINE_FACTOR
        baseline = font.ascender * size
        width = PAGE_WIDTH - 2 * MARGIN_X
        bottom = PAGE_HEIGHT - MARGIN_BOTTOM
        metrics = self._measure(font, size)
        start_page: int | None = None

        for line in _wrap(text, metrics, width):
            if self.y + step > bottom:
                self._new_page()
            right_to_left = bool(_RTL.search(line))
            length = metrics.text(line)
            if right_to_left:
                x_right = PAGE_WIDTH - MARGIN_X
                self.writer.append(
                    pymupdf.Point(x_right, self.y + baseline),
                    line,
                    font=font,
                    fontsize=size,
                    language="he" if _HEBREW.search(line) else "ar",
                    right_to_left=True,
                )
                x0, x1 = x_right - length, x_right
            else:
                self.writer.append(
                    pymupdf.Point(MARGIN_X, self.y + baseline),
                    line,
                    font=font,
                    fontsize=size,
                )
                x0, x1 = MARGIN_X, MARGIN_X + length
            if start_page is None:
                start_page = self.index
            self.pages[self.index].append(
                {
                    "text": line,
                    "x0": round(x0 * self.scale, 2),
                    "y0": round((self.y + size * 0.12) * self.scale, 2),
                    "x1": round(x1 * self.scale, 2),
                    "y1": round((self.y + size * 1.06) * self.scale, 2),
                }
            )
            self.y += step
        return start_page


def _pick_fonts(documents: dict[str, list[dict]]) -> tuple["pymupdf.Font", "pymupdf.Font"]:
    unicode_needed = False
    for blocks in documents.values():
        for block in blocks:
            try:
                block["text"].encode("cp1252")
            except UnicodeEncodeError:
                unicode_needed = True
                break
        if unicode_needed:
            break

    if unicode_needed:
        for regular, bold in _FONT_CANDIDATES:
            if regular.is_file():
                try:
                    return (
                        pymupdf.Font(fontfile=str(regular)),
                        pymupdf.Font(fontfile=str(bold if bold.is_file() else regular)),
                    )
                except Exception:  # an unreadable font is not a reason to fail
                    continue
    return pymupdf.Font("helv"), pymupdf.Font("hebo")


def _outline(
    entries: list[dict],
    doc_start: dict[str, int],
    anchor_pages: dict[tuple[str, str], int],
    page_count: int,
) -> list[list]:
    """The PDF outline for the chosen chapter list.

    Entries are written flat on purpose: ``_chapter_entries`` has already
    picked one level of the book's contents (parts are too coarse, sections too
    fine), and nesting them under whichever entry happens to come first would
    make the next reader treat the others as its subheadings.
    """
    outline: list[list] = []
    for entry in entries:
        page = None
        fragment = entry.get("fragment") or ""
        if fragment:
            page = anchor_pages.get((entry["href"], fragment))
        if page is None:
            page = doc_start.get(entry["href"])
        if page is None:
            continue
        title = _clean_title(entry.get("title", ""))
        if not title:
            continue
        outline.append([1, title, max(1, min(page_count, page + 1))])
    return outline


def convert(source: Path, target: Path, scale: float = 2.0) -> dict:
    """Write a PDF version of the book to ``target`` and describe its pages."""
    source = Path(source)
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("That file isn't an EPUB (it isn't a zip archive).") from exc

    with archive:
        package = _read_package(archive, _rootfile(archive))
        spine = _spine_documents(package)
        if not spine:
            raise ValueError("That EPUB has no readable spine — its chapters are missing.")
        documents = {href: _document_blocks(archive, href) for href in spine}
        if not any(documents.values()):
            raise ValueError(
                "That EPUB has no extractable text. If it is a scan, an image-only "
                "comic or a fixed-layout book, export it to PDF first."
            )
        entries = _chapter_entries(
            _toc_from_nav(archive, package)
            or _toc_from_ncx(archive, package)
            or _heading_toc(documents)
        )
        chapter_anchors = {
            (entry["href"], entry["fragment"])
            for entry in entries
            if entry.get("fragment")
        }
        chapter_documents = {entry["href"] for entry in entries if not entry.get("fragment")}

        regular, bold = _pick_fonts(documents)
        pdf = pymupdf.open()
        try:
            layout = _Layout(pdf, regular, bold, scale)
            doc_start: dict[str, int] = {}
            anchor_pages: dict[tuple[str, str], int] = {}
            for href in spine:
                first_page: int | None = None
                if href in chapter_documents:
                    layout.page_break()
                for block in documents[href]:
                    if any((href, anchor) in chapter_anchors for anchor in block["anchors"]):
                        layout.page_break()
                    if len(layout.pages) > MAX_PAGES:
                        raise ValueError(
                            f"That EPUB needs more than {MAX_PAGES} pages of text."
                        )
                    placed = layout.place(block["text"], block["kind"])
                    if placed is None:
                        continue
                    if first_page is None:
                        first_page = placed
                    for anchor in block["anchors"]:
                        anchor_pages.setdefault((href, anchor), placed)
                doc_start[href] = first_page if first_page is not None else layout.next_page
            layout.close()
            page_count = len(layout.pages)
            if page_count == 0:
                raise ValueError("That EPUB has no readable text.")
            outline = _outline(entries, doc_start, anchor_pages, page_count)
            if len(outline) >= 2:
                try:
                    pdf.set_toc(outline)
                except Exception:  # a broken outline must not lose the book
                    outline = []
            pdf.save(target)
        finally:
            pdf.close()

    pages = [
        {
            "index": index,
            "width": int(round(PAGE_WIDTH * scale)),
            "height": int(round(PAGE_HEIGHT * scale)),
            "lines": lines,
        }
        for index, lines in enumerate(layout.pages)
    ]
    return {
        "title": package["title"] or source.stem,
        "author": package["author"],
        "pageCount": page_count,
        "pages": pages,
        "toc": outline,
    }
