"""Auto-merger: evaluate the orchestrator's own PRs and merge when safe."""

from .merger import (
    AutoMerger,
    MergeDecision,
    PRIVACY_CRITICAL_PATHS,
)

__all__ = ["AutoMerger", "MergeDecision", "PRIVACY_CRITICAL_PATHS"]
