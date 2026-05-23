"""Pre-emit static checkers — the operational privacy boundary.

Public surface:

- `CheckerPipeline` — orchestrates the 5+1 stages.
- `CheckResult`, `ChainResult`, `ReasonCode` — result types.
- Individual stage modules (`forbidden_fields`, `pii`, `numeric`, `quotes`)
  for unit testing.
"""

from .pipeline import CheckerPipeline, run_static_checkers
from .results import ChainResult, CheckResult, ReasonCode, Stage

__all__ = [
    "ChainResult",
    "CheckResult",
    "CheckerPipeline",
    "ReasonCode",
    "Stage",
    "run_static_checkers",
]
