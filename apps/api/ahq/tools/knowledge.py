from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence

from pydantic import BaseModel, Field

from ahq.domain import Effect, StrictModel, ToolResult
from ahq.domain.team import KbDraft
from ahq.retrieval import Audience, KbDocument, Namespace, Passage, SearchRequest, chunk_documents
from ahq.tools.types import Invocation, ToolDeps, ToolSpec


class Search(StrictModel):
    query: str = Field(min_length=1, description="What to look for, in plain words.")
    namespaces: list[Namespace] = Field(
        default_factory=list,
        description="Limit the search to these sections of the knowledge base; all sections when empty.",
    )


class DraftArticle(StrictModel):
    doc_id: str = Field(
        pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$",
        description="The article's id: an existing one for a new version, or a new one such as help-midwest-delays.",
    )
    title: str = Field(min_length=3, max_length=120)
    namespace: Namespace
    audience: Audience = Field(description="customer if Support may quote it to customers, internal otherwise.")
    body: str = Field(
        min_length=40,
        description="The article in markdown: a '# Title' line, a short introduction, then '## ' sections.",
    )


class ArticleRef(StrictModel):
    doc_id: str = Field(description="The article's doc_id, such as 'policy-returns'.")


def passages_json(passages: Sequence[Passage]) -> str:
    return json.dumps(
        [
            {
                "id": passage.passage_id,
                "title": passage.title,
                "section": passage.section,
                "version": passage.version,
                "effective_date": passage.effective_date.isoformat(),
                "valid_until": passage.valid_until.isoformat(),
                "text": passage.text,
            }
            for passage in passages
        ]
    )


async def _search(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, Search)
    request = SearchRequest(
        query=args.query,
        as_of=invocation.as_of(deps.clock),
        audience=invocation.principal.audience,
        namespaces=tuple(args.namespaces),
    )
    result = await deps.retriever.search(request)
    return ToolResult(output=passages_json(result.passages))


async def _article(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, ArticleRef)
    passages = await deps.retriever.article(args.doc_id, invocation.as_of(deps.clock), invocation.principal.audience)
    if not passages:
        return ToolResult.error(f"No article {args.doc_id!r} is in effect.")
    return ToolResult(output=passages_json(passages))


async def _draft(args: BaseModel, invocation: Invocation, deps: ToolDeps) -> ToolResult:
    assert isinstance(args, DraftArticle)
    if deps.knowledge is None or deps.records is None:
        return ToolResult.error("Drafting is not available here: it needs the database.")
    context = invocation.context
    key = context.idempotency_key if context is not None else f"{args.doc_id}:{args.title}:{args.body}"
    draft_id = "drf_" + hashlib.sha256(key.encode()).hexdigest()[:16]
    existing = await deps.records.draft(draft_id)
    version = existing.version if existing is not None else await deps.knowledge.next_version(args.doc_id)
    document = KbDocument(
        doc_id=args.doc_id,
        title=args.title,
        namespace=args.namespace,
        audience=args.audience,
        version=version,
        effective_date=invocation.as_of(deps.clock),
        source=f"draft:{draft_id}",
        body=args.body,
    )
    if not chunk_documents([document]):
        return ToolResult.error("The body has no sections; add '## ' headings.")
    draft = await deps.records.save_draft(
        KbDraft(
            draft_id=draft_id,
            doc_id=document.doc_id,
            version=document.version,
            document=document.model_dump(mode="json"),
            status="pending",
            created_at=deps.clock.now(),
        )
    )
    await deps.knowledge.stage(KbDocument.model_validate(draft.document))
    result = {"draft_id": draft.draft_id, "doc_id": draft.doc_id, "version": draft.version, "status": "pending"}
    return ToolResult(output=json.dumps(result))


KNOWLEDGE_TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="knowledge_search",
        server="knowledge",
        effect=Effect.READ,
        description=(
            "Search the store's knowledge base: policies, help articles, shipping information and product guides. "
            "Returns the best passages, each with an id to cite when you tell the customer about a policy. Search "
            "before stating a policy, and cite only passages you received."
        ),
        args=Search,
        handler=_search,
        cacheable=True,
    ),
    ToolSpec(
        name="knowledge_get_article",
        server="knowledge",
        effect=Effect.READ,
        description=(
            "Get a whole knowledge base article by its doc_id, in the version in effect today. Use it when a passage "
            "needs its surrounding sections. Returns every section with the id to cite it by."
        ),
        args=ArticleRef,
        handler=_article,
        cacheable=True,
    ),
    ToolSpec(
        name="knowledge_draft_article",
        server="knowledge",
        effect=Effect.DRAFT,
        description=(
            "Draft a new knowledge base article, or a new version of an existing one, for a person to approve. The "
            "draft is not searchable until it is approved and published. Returns the draft id to cite in a proposal."
        ),
        args=DraftArticle,
        handler=_draft,
    ),
)
