# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Artifact store: persist generation evidence (candidates, context, reviews)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from novel_weaver.domain.models import new_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ArtifactRef:
    artifact_id: str
    kind: str
    story_id: str
    path: str
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactStore:
    """Filesystem evidence store. Never a source of Canonical truth (§17.3).

    Decision: directory layout under workspace/artifacts/<story>/<kind>/.
    Alternative: BLOB columns in SQLite — rejected for large prose/context dumps.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, story_id: str, kind: str) -> Path:
        d = self.root / story_id / kind
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write(
        self,
        story_id: str,
        kind: str,
        payload: dict[str, Any] | list[Any] | str,
        *,
        artifact_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        aid = artifact_id or new_id("art")
        path = self._dir(story_id, kind) / f"{aid}.json"
        body: Any
        if isinstance(payload, str):
            body = {"text": payload}
        else:
            body = payload
        envelope = {
            "artifact_id": aid,
            "kind": kind,
            "story_id": story_id,
            "created_at": _now().isoformat(),
            "metadata": metadata or {},
            "payload": body,
        }
        path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return ArtifactRef(
            artifact_id=aid,
            kind=kind,
            story_id=story_id,
            path=str(path),
            created_at=envelope["created_at"],
            metadata=metadata or {},
        )

    def read(self, path: Path | str) -> dict[str, Any]:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def list(self, story_id: str, kind: str | None = None) -> list[ArtifactRef]:
        base = self.root / story_id
        if not base.exists():
            return []
        kinds = [kind] if kind else [p.name for p in base.iterdir() if p.is_dir()]
        out: list[ArtifactRef] = []
        for k in kinds:
            d = base / k
            if not d.exists():
                continue
            for f in sorted(d.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                out.append(
                    ArtifactRef(
                        artifact_id=data.get("artifact_id", f.stem),
                        kind=data.get("kind", k),
                        story_id=data.get("story_id", story_id),
                        path=str(f),
                        created_at=data.get("created_at", ""),
                        metadata=data.get("metadata") or {},
                    )
                )
        return out

    def write_candidate(
        self,
        story_id: str,
        *,
        candidate_id: str,
        chapter_id: str,
        content: str,
        quality: dict[str, Any] | None = None,
        context_fingerprint: str = "",
    ) -> ArtifactRef:
        return self.write(
            story_id,
            "candidate",
            {
                "candidate_id": candidate_id,
                "chapter_id": chapter_id,
                "content": content,
                "quality": quality or {},
                "context_fingerprint": context_fingerprint,
            },
            artifact_id=candidate_id,
        )

    def write_context_snapshot(
        self, story_id: str, *, session_id: str, pack: dict[str, Any]
    ) -> ArtifactRef:
        return self.write(
            story_id,
            "context",
            pack,
            artifact_id=session_id,
            metadata={"session_id": session_id},
        )

    def write_review(
        self,
        story_id: str,
        *,
        review_id: str,
        decision: str,
        issues: list[dict[str, Any]],
        manifest_id: str = "",
    ) -> ArtifactRef:
        return self.write(
            story_id,
            "review",
            {
                "review_id": review_id,
                "decision": decision,
                "issues": issues,
                "manifest_id": manifest_id,
            },
            artifact_id=review_id,
        )
