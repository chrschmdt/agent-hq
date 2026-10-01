from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlsplit

from ahq.domain import ReplyFinding, mask
from ahq.ports import RetailRepo

type IdentifierKind = Literal["email", "order", "user"]

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ORDER = re.compile(r"#W\d{7}\b")
USER = re.compile(r"\b[a-z]+_[a-z]+_\d{4}\b")
LINK = re.compile(r"\b(?:https?://|www\.)[^\s<>()\"']+", re.IGNORECASE)
PATTERNS: tuple[tuple[IdentifierKind, re.Pattern[str]], ...] = (("email", EMAIL), ("order", ORDER), ("user", USER))


@dataclass(frozen=True)
class Identifier:
    kind: IdentifierKind
    value: str


def find_identifiers(text: str) -> list[Identifier]:
    found: dict[str, Identifier] = {}
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            found.setdefault(match[0].lower(), Identifier(kind, match[0]))
    return list(found.values())


def find_links(text: str) -> list[str]:
    return [match[0].rstrip(".,;:!?") for match in LINK.finditer(text)]


class Owners(Protocol):
    async def owners(self, identifiers: Sequence[Identifier]) -> dict[str, str | None]: ...


class StoreOwners:
    def __init__(self, retail: RetailRepo) -> None:
        self._retail = retail

    async def owners(self, identifiers: Sequence[Identifier]) -> dict[str, str | None]:
        found: dict[str, str | None] = {}
        async with self._retail.session() as session:
            for identifier in identifiers:
                match identifier.kind:
                    case "email":
                        found[identifier.value] = await session.user_id_by_email(identifier.value)
                    case "order":
                        order = await session.order(identifier.value)
                        found[identifier.value] = order.user_id if order is not None else None
                    case "user":
                        user = await session.user(identifier.value)
                        found[identifier.value] = user.user_id if user is not None else None
        return found


@dataclass(frozen=True)
class ReplyCheck:
    owners: Owners
    allowed_hosts: frozenset[str] = frozenset()

    async def check(self, reply: str, *, customer_id: str | None, customer_wrote: str) -> list[ReplyFinding]:
        wrote = customer_wrote.lower()
        candidates = [i for i in find_identifiers(reply) if i.value.lower() not in wrote]
        owners = await self.owners.owners(candidates) if candidates else {}
        findings = [
            ReplyFinding(kind=i.kind, value=mask(i.value))
            for i in candidates
            if owners.get(i.value) is not None and owners[i.value] != customer_id
        ]
        findings += [
            ReplyFinding(kind="link", value=mask(link)) for link in find_links(reply) if not self._allowed(link)
        ]
        return findings

    def _allowed(self, link: str) -> bool:
        host = urlsplit(link if "://" in link else f"https://{link}").hostname or ""
        return any(host == allowed or host.endswith(f".{allowed}") for allowed in self.allowed_hosts)
