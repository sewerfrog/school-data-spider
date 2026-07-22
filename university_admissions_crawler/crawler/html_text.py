"""HTML-to-text helpers for fetcher source normalization."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
import html as html_lib
import json
import re


_MAX_JSON_LD_COURSE_BLOCKS = 500


@dataclass(frozen=True, slots=True)
class HTMLBlockLink:
    text: str
    href: str


@dataclass(frozen=True, slots=True)
class HTMLContentBlock:
    kind: str
    text: str
    cells: tuple[str, ...] = ()
    heading_level: int | None = None
    section_path: tuple[str, ...] = ()
    links: tuple[HTMLBlockLink, ...] = ()
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HTMLTextDocument:
    plain_text: str
    blocks: tuple[HTMLContentBlock, ...]


@dataclass(slots=True)
class _BlockCapture:
    tag: str
    kind: str
    heading_level: int | None = None
    parts: list[str] = field(default_factory=list)
    links: list[HTMLBlockLink] = field(default_factory=list)


@dataclass(slots=True)
class _TableRowCapture:
    cells: list[str] = field(default_factory=list)
    links: list[HTMLBlockLink] = field(default_factory=list)


@dataclass(slots=True)
class _TableCellCapture:
    tag: str
    parts: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _LinkCapture:
    href: str
    target: _BlockCapture | _TableRowCapture | None
    parts: list[str] = field(default_factory=list)


class _ContentBlockParser(HTMLParser):
    _PARAGRAPH_TAGS = {"p", "pre", "blockquote", "dt", "dd"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[HTMLContentBlock] = []
        self._active_block: _BlockCapture | None = None
        self._active_row: _TableRowCapture | None = None
        self._active_cell: _TableCellCapture | None = None
        self._link_stack: list[_LinkCapture] = []
        self._headings: dict[int, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._finish_active_block()
            self._finish_row()
            self._active_row = _TableRowCapture()
            return
        if tag in {"td", "th"} and self._active_row is not None:
            self._finish_cell()
            self._active_cell = _TableCellCapture(tag=tag)
            return
        if tag == "br":
            self._append_fragment("\n")
            return
        if tag == "a":
            href = next((value for name, value in attrs if name.lower() == "href" and value), "")
            target: _BlockCapture | _TableRowCapture | None = self._active_block or self._active_row
            self._link_stack.append(_LinkCapture(href=href.strip(), target=target))
            return
        if self._active_row is not None:
            return

        heading_match = re.fullmatch(r"h([1-6])", tag)
        if heading_match:
            self._finish_active_block()
            self._active_block = _BlockCapture(tag=tag, kind="heading", heading_level=int(heading_match.group(1)))
        elif tag == "li":
            self._finish_active_block()
            self._active_block = _BlockCapture(tag=tag, kind="list_item")
        elif tag in self._PARAGRAPH_TAGS and self._active_block is None:
            self._active_block = _BlockCapture(tag=tag, kind="paragraph")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a":
            self._finish_link()
            return
        if tag in {"td", "th"} and self._active_cell is not None and self._active_cell.tag == tag:
            self._finish_cell()
            return
        if tag == "tr":
            self._finish_row()
            return
        if self._active_row is not None:
            return
        if self._active_block is not None and self._active_block.tag == tag:
            self._finish_active_block()

    def handle_data(self, data: str) -> None:
        self._append_fragment(data)

    def close(self) -> None:
        super().close()
        while self._link_stack:
            self._finish_link()
        self._finish_cell()
        self._finish_row()
        self._finish_active_block()

    def _append_fragment(self, value: str) -> None:
        if self._active_cell is not None:
            self._active_cell.parts.append(value)
        elif self._active_block is not None:
            self._active_block.parts.append(value)
        if self._link_stack:
            self._link_stack[-1].parts.append(value)

    def _finish_link(self) -> None:
        if not self._link_stack:
            return
        capture = self._link_stack.pop()
        text = _normalize_block_text("".join(capture.parts))
        if not capture.href or not text or capture.target is None:
            return
        capture.target.links.append(HTMLBlockLink(text=text, href=capture.href))

    def _finish_cell(self) -> None:
        if self._active_cell is None:
            return
        if self._active_row is not None:
            self._active_row.cells.append(_normalize_block_text("".join(self._active_cell.parts)))
        self._active_cell = None

    def _finish_row(self) -> None:
        if self._active_row is None:
            return
        self._finish_cell()
        row = self._active_row
        self._active_row = None
        if not any(row.cells):
            return
        text = " | ".join(row.cells)
        self.blocks.append(
            HTMLContentBlock(
                kind="table_row",
                text=text,
                cells=tuple(row.cells),
                section_path=self._section_path(),
                links=_dedupe_links(row.links),
                flags=_block_flags(text),
            )
        )

    def _finish_active_block(self) -> None:
        if self._active_block is None:
            return
        capture = self._active_block
        self._active_block = None
        text = _normalize_block_text("".join(capture.parts))
        if not text:
            return
        if capture.kind == "heading" and capture.heading_level is not None:
            section_path = self._update_section_path(capture.heading_level, text)
        else:
            section_path = self._section_path()
        self.blocks.append(
            HTMLContentBlock(
                kind=capture.kind,
                text=text,
                heading_level=capture.heading_level,
                section_path=section_path,
                links=_dedupe_links(capture.links),
                flags=_block_flags(text),
            )
        )

    def _update_section_path(self, level: int, text: str) -> tuple[str, ...]:
        for existing_level in tuple(self._headings):
            if existing_level >= level:
                del self._headings[existing_level]
        self._headings[level] = text
        return self._section_path()

    def _section_path(self) -> tuple[str, ...]:
        return tuple(self._headings[level] for level in sorted(self._headings))


class _JSONLDParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.payloads: list[str] = []
        self._active_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "script" or self._active_parts is not None:
            return
        content_type = next((value for name, value in attrs if name.lower() == "type" and value), "")
        if content_type.split(";", 1)[0].strip().lower() == "application/ld+json":
            self._active_parts = []

    def handle_data(self, data: str) -> None:
        if self._active_parts is not None:
            self._active_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "script" or self._active_parts is None:
            return
        payload = "".join(self._active_parts).strip()
        self._active_parts = None
        if payload:
            self.payloads.append(payload)


def _html_to_text(html: str) -> str:
    text = _main_content_fragment(html)
    text = _remove_html_noise(text)
    text = _tables_to_text(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def extract_html_text_document(html: str) -> HTMLTextDocument:
    plain_text = _html_to_text(html)
    fragment = _remove_html_noise(_main_content_fragment(html))
    parser = _ContentBlockParser()
    parser.feed(fragment)
    parser.close()
    blocks = tuple(parser.blocks)
    if not blocks:
        blocks = _json_ld_course_blocks(html, visible_text=plain_text)
    return HTMLTextDocument(plain_text=plain_text, blocks=blocks)


def _json_ld_course_blocks(html: str, *, visible_text: str) -> tuple[HTMLContentBlock, ...]:
    parser = _JSONLDParser()
    parser.feed(html)
    parser.close()

    blocks: list[HTMLContentBlock] = []
    seen: set[tuple[str, str]] = set()
    visible_name_haystack = _normalize_name_search_text(visible_text)
    for payload in parser.payloads:
        try:
            value = json.loads(payload)
        except (TypeError, ValueError):
            continue
        for item in _walk_json_objects(value):
            if not _json_ld_has_type(item, "Course"):
                continue
            name_value = item.get("name")
            if not isinstance(name_value, str):
                continue
            name = _normalize_block_text(html_lib.unescape(name_value))
            if not name or _normalize_name_search_text(name) not in visible_name_haystack:
                continue
            url_value = item.get("url") or item.get("@id")
            url = url_value.strip() if isinstance(url_value, str) else ""
            key = (name.casefold(), url)
            if key in seen:
                continue
            seen.add(key)
            links = (HTMLBlockLink(text=name, href=url),) if url else ()
            blocks.append(HTMLContentBlock(kind="card", text=name, links=links))
            if len(blocks) >= _MAX_JSON_LD_COURSE_BLOCKS:
                return tuple(blocks)
    return tuple(blocks)


def _normalize_name_search_text(value: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(value)).casefold()


def _walk_json_objects(value: object) -> Iterator[dict[object, object]]:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            yield current
            pending.extend(reversed(current.values()))
        elif isinstance(current, list):
            pending.extend(reversed(current))


def _json_ld_has_type(item: dict[object, object], expected: str) -> bool:
    value = item.get("@type")
    values = value if isinstance(value, list) else [value]
    return any(isinstance(item_type, str) and item_type.casefold() == expected.casefold() for item_type in values)


def _normalize_block_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def _dedupe_links(links: list[HTMLBlockLink]) -> tuple[HTMLBlockLink, ...]:
    return tuple(dict.fromkeys(links))


def _block_flags(text: str) -> tuple[str, ...]:
    return ("css_like",) if _looks_like_css(text) else ()


def _looks_like_css(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact:
        return False
    if re.search(r"(?:^|[;}])\s*@(?:media|font-face|keyframes|supports|import)\b", compact, flags=re.IGNORECASE):
        return True
    has_rule = bool(re.search(r"(?:^|[}\s])(?:[.#][a-z_-][\w-]*|[a-z][\w-]*(?:\s+[.#]?[a-z][\w-]*)?)\s*\{", compact, flags=re.IGNORECASE))
    has_property = bool(re.search(r"\b[a-z-]{2,}\s*:\s*[^;{}]+;", compact, flags=re.IGNORECASE))
    return has_rule and has_property and "}" in compact


def _strip_tags(value: str) -> str:
    return html_lib.unescape(re.sub(r"<[^>]+>", " ", value))


def _main_content_fragment(html: str) -> str:
    for pattern in (
        r"<main\b[^>]*>(.*?)</main>",
        r"<article\b[^>]*>(.*?)</article>",
        r"<(?:div|section)\b[^>]*(?:role|id|class)\s*=\s*[\"'][^\"']*(?:main|content|page-content|body-content)[^\"']*[\"'][^>]*>(.*?)</(?:div|section)>",
    ):
        match = re.search(pattern, html, flags=re.IGNORECASE | re.DOTALL)
        if match:
            fragment = match.group(1)
            if len(_strip_tags(fragment).strip()) >= 80:
                return fragment
    return html


def _remove_html_noise(html: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", html, flags=re.DOTALL)
    for tag in ("script", "style", "noscript", "svg", "canvas", "iframe", "nav", "header", "footer", "aside"):
        text = re.sub(rf"<{tag}\b[^>]*>.*?</{tag}>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    noisy_attr = (
        "breadcrumb|cookie|consent|banner|global|nav|menu|mega|header|footer|"
        "sidebar|social|share|skip|search|modal|popup|toolbar|utility"
    )
    pattern = rf"<(?P<tag>div|section|form|ul|ol)\b[^>]*(?:class|id|role|aria-label)\s*=\s*[\"'][^\"']*(?:{noisy_attr})[^\"']*[\"'][^>]*>.*?</(?P=tag)>"
    previous = None
    while previous != text:
        previous = text
        text = re.sub(pattern, " ", text, flags=re.IGNORECASE | re.DOTALL)
    return text


def _tables_to_text(html: str) -> str:
    def replace_table(match: re.Match) -> str:
        rows: list[str] = []
        for row_match in re.finditer(r"<tr\b[^>]*>(.*?)</tr>", match.group(1), flags=re.IGNORECASE | re.DOTALL):
            cells = [
                re.sub(r"\s+", " ", _strip_tags(cell_match.group(1))).strip()
                for cell_match in re.finditer(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row_match.group(1), flags=re.IGNORECASE | re.DOTALL)
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(" | ".join(cells))
        return " . ".join(rows)

    return re.sub(r"<table\b[^>]*>(.*?)</table>", replace_table, html, flags=re.IGNORECASE | re.DOTALL)
