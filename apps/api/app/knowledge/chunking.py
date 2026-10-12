"""Deterministic structure-aware chunking.

Text is split into blocks at blank lines and headings, so paragraphs, list blocks and tables
stay whole; blocks are packed into chunks of at most `size` characters. Only a block longer
than a chunk is split further, at sentence and then word boundaries. Each new chunk starts
with up to `overlap` characters from the end of the previous one (cut at a word boundary).
Chunks never span PDF pages, and each records the heading it falls under.
"""

import re
from dataclasses import dataclass

from app.knowledge.extract import Section

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class ChunkDraft:
    index: int
    text: str
    page: int | None
    heading: str | None


def _blocks(text: str):
    """Yield (heading_or_None, block_text). Headings are emitted as their own marker."""
    current: list[str] = []
    for line in text.split("\n"):
        heading = HEADING.match(line.strip())
        if heading or not line.strip():
            if current:
                yield None, "\n".join(current).strip()
                current = []
            if heading:
                yield heading.group(2).strip(), None
            continue
        current.append(line.rstrip())
    if current:
        yield None, "\n".join(current).strip()


def _split_long(block: str, size: int) -> list[str]:
    pieces, current = [], ""
    for unit in SENTENCE_END.split(block):
        while len(unit) > size:  # a single sentence longer than a chunk: cut at a word
            cut = unit.rfind(" ", 0, size)
            cut = cut if cut > size // 2 else size
            pieces.append((current + " " + unit[:cut]).strip() if current else unit[:cut])
            current, unit = "", unit[cut:].strip()
        if current and len(current) + 1 + len(unit) > size:
            pieces.append(current)
            current = unit
        else:
            current = f"{current} {unit}".strip()
    if current:
        pieces.append(current)
    return pieces


def _tail(text: str, overlap: int) -> str:
    if overlap <= 0 or len(text) <= overlap:
        return "" if overlap <= 0 else text
    tail = text[-overlap:]
    space = tail.find(" ")
    return tail[space + 1 :] if 0 <= space < len(tail) - 1 else tail


class _Packer:
    """Accumulates blocks of one section into chunks."""

    def __init__(self, chunks: list[ChunkDraft], page: int | None, size: int, overlap: int):
        self.chunks, self.page, self.size, self.overlap = chunks, page, size, overlap
        self.buffer, self.heading, self.carry = "", None, ""

    def flush(self) -> None:
        if self.buffer.strip():
            text = self.buffer.strip()
            self.chunks.append(ChunkDraft(len(self.chunks), text, self.page, self.heading))
            self.carry = _tail(text, self.overlap)
        self.buffer = ""

    def add(self, unit: str, heading: str | None) -> None:
        if self.buffer and len(self.buffer) + 2 + len(unit) > self.size:
            self.flush()
        if self.buffer:
            self.buffer = f"{self.buffer}\n\n{unit}"
            return
        self.heading = heading
        self.buffer = f"{self.carry}\n\n{unit}" if self.carry else unit
        if len(self.buffer) > self.size:
            self.buffer = unit


def chunk_sections(sections: list[Section], size: int, overlap: int) -> list[ChunkDraft]:
    chunks: list[ChunkDraft] = []
    heading: str | None = None
    for section in sections:
        packer = _Packer(chunks, section.page, size, overlap)
        for marker, block in _blocks(section.text):
            if marker is not None:
                packer.flush()
                heading = marker
                packer.carry = ""  # a new heading starts a fresh context
                continue
            units = [block] if len(block) <= size - overlap else _split_long(block, size - overlap)
            for unit in units:
                packer.add(unit, heading)
        packer.flush()
    return chunks
