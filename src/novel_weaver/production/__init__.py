# SPDX-FileCopyrightText: 2026 zcbacxc
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Runtime helpers: fingerprints, fake generation, invalidation, orchestration.

Note: engine is imported lazily via production.engine to avoid circular imports
with novel_weaver.ai (ai.base imports production.fingerprint).
"""

from novel_weaver.production.fingerprint import content_fingerprint, context_fingerprint
from novel_weaver.production.invalidation import ImpactAnalyzer, mark_stale
from novel_weaver.production.fake_gen import FakeGenerator
from novel_weaver.production.orchestrator import ProductionOrchestrator
from novel_weaver.production.context import ContextPack, build_context_pack
from novel_weaver.production.reconcile import DetectedEdit, ReconcileResult, ReconcileService


def __getattr__(name: str):
    if name in ("ProductionEngine", "EngineRunResult"):
        from novel_weaver.production import engine as _engine

        return getattr(_engine, name)
    raise AttributeError(name)


__all__ = [
    "ContextPack",
    "DetectedEdit",
    "EngineRunResult",
    "FakeGenerator",
    "ImpactAnalyzer",
    "ProductionEngine",
    "ProductionOrchestrator",
    "ReconcileResult",
    "ReconcileService",
    "build_context_pack",
    "content_fingerprint",
    "context_fingerprint",
    "mark_stale",
]
