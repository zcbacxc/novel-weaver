# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TemplateProvider: readable chapter draft assembled from a context pack dict."""

from __future__ import annotations

import time
from typing import Any

from novel_weaver.ai.base import (
    GenerationRequest,
    GenerationResult,
    Provider,
    TokenUsage,
    estimate_tokens,
)

_DEFAULT_TEMPLATE = """\
# {title}

{opening}

{plan_section}

{facts_section}

{threads_section}

{closing}
"""


class TemplateProvider(Provider):
    """Offline ``Provider`` that renders a structured chapter-style draft.

    Assembles title, plan, canonical facts, open threads, and quality feedback
    from ``request.context`` into a human-readable template string.
    """

    name = "template"

    def __init__(self, *, model: str = "template-v1", template: str | None = None) -> None:
        """Create a template provider.

        Args:
            model: Model label reported when the request uses the default model.
            template: Optional format template with title/opening/plan/facts/
                threads/closing placeholders.
        """
        self.model = model
        self.template = template or _DEFAULT_TEMPLATE

    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Render the template draft for this request.

        Args:
            request: Generation inputs; context pack supplies plan/facts/threads.

        Returns:
            A ``GenerationResult`` whose text is the formatted draft.
        """
        started = time.perf_counter()
        fingerprint = request.fingerprint()
        text = self._render(request)
        latency_ms = (time.perf_counter() - started) * 1000.0
        prompt_tokens = estimate_tokens(request.prompt) + estimate_tokens(str(request.context))
        completion_tokens = estimate_tokens(text)
        return GenerationResult(
            text=text,
            model=request.model if request.model != "default" else self.model,
            provider=self.name,
            usage=TokenUsage.of(prompt_tokens, completion_tokens),
            latency_ms=latency_ms,
            task=request.task,
            story_id=request.story_id,
            chapter_id=request.chapter_id,
            fingerprint=fingerprint,
            raw={"template": True},
        )

    def _render(self, request: GenerationRequest) -> str:
        ctx = request.context
        title = self._title(request, ctx)
        intent = str(ctx.get("creative_intent") or "").strip()
        plan = str(ctx.get("current_plan") or request.prompt or "").strip()
        opening = self._opening(title, intent)
        plan_section = self._plan_section(plan)
        facts_section = self._facts_section(ctx.get("selected_facts"))
        threads_section = self._threads_section(ctx.get("active_threads"))
        closing = self._closing(ctx.get("quality_feedback"))
        return self.template.format(
            title=title,
            opening=opening,
            plan_section=plan_section,
            facts_section=facts_section,
            threads_section=threads_section,
            closing=closing,
        )

    def _title(self, request: GenerationRequest, ctx: dict[str, Any]) -> str:
        if ctx.get("chapter_title"):
            return str(ctx["chapter_title"])
        unit = request.chapter_id or str(ctx.get("production_unit") or "")
        if unit:
            return f"Draft · {unit}"
        return "Untitled Chapter Draft"

    def _opening(self, title: str, intent: str) -> str:
        if intent:
            return (
                f"The narrative continues under the stated intent: {intent}. "
                f"This draft for “{title}” respects current canonical constraints."
            )
        return (
            f"This draft for “{title}” follows the active plan and canonical "
            f"facts below without inventing new world truths."
        )

    def _plan_section(self, plan: str) -> str:
        if not plan:
            return "## Plan\n\n(No explicit plan provided.)"
        return f"## Plan\n\n{plan}"

    def _facts_section(self, facts: Any) -> str:
        if not facts:
            return "## Canonical facts\n\n(No canonical facts selected.)"
        lines: list[str] = []
        for fact in facts:
            if isinstance(fact, dict):
                key = fact.get("key", "?")
                value = fact.get("value")
                source = fact.get("source") or ""
                suffix = f" ({source})" if source else ""
                lines.append(f"- **{key}**: {value}{suffix}")
            else:
                lines.append(f"- {fact}")
        return "## Canonical facts\n\n" + "\n".join(lines)

    def _threads_section(self, threads: Any) -> str:
        if not threads:
            return "## Open threads\n\n(None surfaced in this pack.)"
        lines: list[str] = []
        for thread in threads:
            if isinstance(thread, dict):
                lines.append(
                    f"- **{thread.get('key', '?')}**: {thread.get('value')} "
                    f"[{thread.get('status', 'PENDING')}]"
                )
            else:
                lines.append(f"- {thread}")
        return "## Open threads\n\n" + "\n".join(lines)

    def _closing(self, feedback: Any) -> str:
        if not feedback:
            return "End of template draft. Candidate only — not Canon until Commit."
        issues: list[str] = []
        for item in feedback:
            if isinstance(item, dict) and item.get("issue") and item.get("issue") != "none":
                issues.append(str(item["issue"]))
        if not issues:
            return "End of template draft. Prior quality feedback: continue."
        return "End of template draft. Address prior feedback:\n" + "\n".join(
            f"- {issue}" for issue in issues
        )
