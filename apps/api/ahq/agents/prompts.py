from __future__ import annotations

import hashlib
import re
import string
from dataclasses import dataclass
from pathlib import Path

from ahq.domain import SystemPrompt

CONTEXT_MARKER = "## Context"
_INCLUDE = re.compile(r"<<include:\s*([\w.-]+)\s*>>")


@dataclass(frozen=True)
class PromptTemplate:
    stable: str
    context: str

    @classmethod
    def load(cls, path: Path) -> PromptTemplate:
        text = _INCLUDE.sub(lambda match: (path.parent / match[1]).read_text().strip(), path.read_text())
        stable, marker, context = text.partition(CONTEXT_MARKER)
        if not marker:
            raise ValueError(f"{path.name} has no '{CONTEXT_MARKER}' section")
        if fields(stable):
            raise ValueError(f"{path.name} has placeholders before '{CONTEXT_MARKER}': {sorted(fields(stable))}")
        return cls(stable=stable.strip(), context=f"{marker}{context}".strip())

    @property
    def placeholders(self) -> frozenset[str]:
        return frozenset(fields(self.context))

    @property
    def digest(self) -> str:
        return hashlib.sha256(f"{self.stable}\x00{self.context}".encode()).hexdigest()

    def render(self, values: dict[str, str]) -> SystemPrompt:
        missing = self.placeholders - values.keys()
        if missing:
            raise KeyError(f"missing prompt values: {sorted(missing)}")
        return SystemPrompt(stable=self.stable, dynamic=self.context.format_map(values))


def fields(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}
