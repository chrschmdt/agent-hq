from __future__ import annotations

import re
import tomllib
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path

from ahq.retrieval.types import FOREVER, Chunk, KbDocument

_CHUNK_NAMESPACE = uuid.UUID("5c3f1d2e-8a4b-4c6d-9e0f-1a2b3c4d5e6f")
_FRONT_MATTER = re.compile(r"\A\+\+\+\n(.*?)\n\+\+\+\n", re.DOTALL)
_SECTION = re.compile(r"^## +(.+)$", re.MULTILINE)


def load_documents(root: Path) -> list[KbDocument]:
    return [
        parse_document(path.read_text(), source=str(path.relative_to(root.parent)))
        for path in sorted(root.rglob("*.md"))
    ]


def parse_document(text: str, *, source: str) -> KbDocument:
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise ValueError(f"{source}: missing +++ front matter")
    meta = tomllib.loads(match.group(1))
    return KbDocument.model_validate({**meta, "source": source, "body": text[match.end() :].strip()})


def chunk_documents(documents: Iterable[KbDocument]) -> list[Chunk]:
    documents = list(documents)
    versions: dict[str, list[KbDocument]] = defaultdict(list)
    for document in documents:
        versions[document.doc_id].append(document)
    chunks: list[Chunk] = []
    for document in documents:
        later = sorted(d.effective_date for d in versions[document.doc_id] if d.version > document.version)
        valid_until = later[0] if later else FOREVER
        chunks.extend(_chunks(document, valid_until))
    return chunks


def _chunks(document: KbDocument, valid_until: date) -> list[Chunk]:
    sections = _sections(document.body)
    return [
        Chunk.model_validate(
            {
                "chunk_id": str(uuid.uuid5(_CHUNK_NAMESPACE, f"{document.doc_id}:v{document.version}:{position}")),
                "doc_id": document.doc_id,
                "title": document.title,
                "section": heading,
                "text": f"{document.title} > {heading}\n\n{body}",
                "namespace": document.namespace,
                "audience": document.audience,
                "version": document.version,
                "effective_date": document.effective_date,
                "valid_until": valid_until,
                "position": position,
                "source": document.source,
            }
        )
        for position, (heading, body) in enumerate(sections)
    ]


def _sections(body: str) -> list[tuple[str, str]]:
    headings = list(_SECTION.finditer(body))
    intro = body[: headings[0].start()] if headings else body
    intro = _strip_title(intro).strip()
    sections: list[tuple[str, str]] = [("Overview", intro)] if intro else []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        text = body[heading.end() : end].strip()
        if text:
            sections.append((heading.group(1).strip(), text))
    return sections


def _strip_title(text: str) -> str:
    return re.sub(r"^# +.+$", "", text, count=1, flags=re.MULTILINE)
