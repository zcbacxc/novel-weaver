# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Rebuildable Memory Projection over Canonical Story (§18.3)."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any

from novel_weaver.domain.models import FactStatus, ProductionUnitStatus
from novel_weaver.production.fingerprint import context_fingerprint
from novel_weaver.storage.repositories import StoryRepository

_TOKEN = re.compile(r"[\w一-鿿]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN.findall(text or "")]


@dataclass
class MemoryHit:
    """One retrieval hit from the memory index.

    Attributes:
        kind: chapter | event | fact.
        ref_id: Document identity in the index.
        score: Relevance score.
        snippet: Short snippet or doc id preview.
        metadata: Source metadata (chapter number, fact key, ...).
    """

    kind: str  # chapter | event | fact
    ref_id: str
    score: float
    snippet: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryProjection:
    """Inverted index projection. Always rebuildable from Canonical (§6/§18)."""

    story_id: str
    fingerprint: str
    doc_count: int
    hits_preview: list[MemoryHit] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the projection summary for observability.

        Returns:
            Dict with story_id, fingerprint, doc_count, and hit previews.
        """
        return {
            "story_id": self.story_id,
            "fingerprint": self.fingerprint,
            "doc_count": self.doc_count,
            "hits_preview": [
                {
                    "kind": h.kind,
                    "ref_id": h.ref_id,
                    "score": h.score,
                    "snippet": h.snippet[:120],
                }
                for h in self.hits_preview
            ],
        }


class MemoryIndex:
    """Keyword/BM25-lite memory over chapters, events, and facts.

    Decision: pure-Python inverted index (no vector DB dependency).
    Alternative: embedding store — deferred; plan allows rebuildable projection.
    """

    def __init__(self) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._df: Counter[str] = Counter()
        self._postings: dict[str, set[str]] = defaultdict(set)
        self._tf: dict[str, Counter[str]] = {}
        self.story_id = ""
        self.fingerprint = ""

    def rebuild(self, repo: StoryRepository, story_id: str) -> MemoryProjection:
        """Rebuild the inverted index from Canonical chapters/events/facts.

        Args:
            repo: Story repository to read from.
            story_id: Story to index.

        Returns:
            MemoryProjection summary (fingerprint, doc_count, preview hits).
        """
        self._docs.clear()
        self._df.clear()
        self._postings.clear()
        self._tf.clear()
        self.story_id = story_id

        for ch in repo.list_chapters(story_id):
            if ch.status is not ProductionUnitStatus.COMMITTED:
                continue
            text = f"{ch.title}\n{ch.plan}\n{ch.content}"
            self._add_doc(
                f"chapter:{ch.chapter_id}",
                text,
                {"kind": "chapter", "number": ch.number, "title": ch.title},
            )

        for ev in repo.list_events(story_id):
            if ev.status == "INVALIDATED":
                continue
            self._add_doc(
                f"event:{ev.event_id}",
                f"{ev.time_ref} {ev.summary}",
                {"kind": "event", "time_ref": ev.time_ref},
            )

        for item in repo.list_state_items(story_id):
            if item.status not in (FactStatus.CANONICAL, FactStatus.PENDING):
                continue
            self._add_doc(
                f"fact:{item.item_id}",
                f"{item.key} {item.value}",
                {"kind": "fact", "key": item.key, "status": item.status.value},
            )

        self.fingerprint = context_fingerprint(
            {
                "story_id": story_id,
                "docs": sorted(self._docs),
                "sizes": {k: len(v) for k, v in self._tf.items()},
            }
        )
        # Seed preview with top chapter by length for observability.
        preview = self.search("故事", k=3)
        return MemoryProjection(
            story_id=story_id,
            fingerprint=self.fingerprint,
            doc_count=len(self._docs),
            hits_preview=preview,
        )

    def _add_doc(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        tf = Counter(_tokens(text))
        if not tf:
            return
        self._docs[doc_id] = {"metadata": metadata, "len": sum(tf.values())}
        self._tf[doc_id] = tf
        for term in tf:
            self._df[term] += 1
            self._postings[term].add(doc_id)

    def search(self, query: str, *, k: int = 5, kinds: set[str] | None = None) -> list[MemoryHit]:
        """BM25-lite keyword search over indexed documents.

        Args:
            query: Free-text query.
            k: Maximum hits to return.
            kinds: Optional kind filter (chapter/event/fact).

        Returns:
            Top-k MemoryHit list ordered by score.
        """
        qterms = _tokens(query)
        if not qterms or not self._docs:
            return []
        n = len(self._docs)
        scores: defaultdict[str, float] = defaultdict(float)
        for term in qterms:
            docs = self._postings.get(term)
            if not docs:
                continue
            idf = 1.0 + (n / (1 + self._df[term]))
            for doc_id in docs:
                tf = self._tf[doc_id][term]
                scores[doc_id] += idf * tf

        hits: list[MemoryHit] = []
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[: k * 3]
        for doc_id, score in ranked:
            meta = self._docs[doc_id]["metadata"]
            if kinds and meta.get("kind") not in kinds:
                continue
            hits.append(
                MemoryHit(
                    kind=str(meta.get("kind", "?")),
                    ref_id=doc_id,
                    score=round(score, 4),
                    snippet=doc_id,
                    metadata=meta,
                )
            )
            if len(hits) >= k:
                break
        return hits

    def context_snippets(self, query: str, *, k: int = 3) -> list[str]:
        """Short snippets for injection into Context Pack quality/continuity hints.

        Args:
            query: Free-text query.
            k: Maximum snippets to return.

        Returns:
            Short human-readable snippet strings.
        """
        out: list[str] = []
        for hit in self.search(query, k=k):
            meta = hit.metadata
            if hit.kind == "chapter":
                out.append(f"ch{meta.get('number')}: {meta.get('title')}")
            elif hit.kind == "event":
                out.append(f"evt@{meta.get('time_ref')}")
            else:
                out.append(f"fact:{meta.get('key')}")
        return out
