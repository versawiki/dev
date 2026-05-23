"""Daily / weekly / monthly spend caps.

The orchestrator records `spend_recorded` audit entries with a numeric
`amount_usd` field every time a Claude run finishes. This module reads
back from the audit log to compute aggregates and decides whether the
next run is allowed to start.

The decision is intentionally `should_pause: bool` + a structured reason
rather than just a bool so the control API can render the reason and the
escalation email can include the same line verbatim.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from ..audit import AuditLog
from ..config import Settings


_NS_PER_SECOND = 1_000_000_000
_SECONDS_PER_DAY = 24 * 60 * 60


@dataclass(frozen=True)
class SpendDecision:
    """The result of asking 'can I spend more right now?'"""

    allowed: bool
    reason: str
    # Human-readable line for emails / status responses.
    summary: str
    # Which window tripped, if any.
    window_tripped: Literal["daily", "weekly", "monthly", "none"] = "none"
    spent_today_usd: float = 0.0
    spent_this_week_usd: float = 0.0
    spent_this_month_usd: float = 0.0


class SpendingTracker:
    """Aggregates spend from the audit log and answers cap questions."""

    SPEND_EVENT = "spend_recorded"

    def __init__(self, audit: AuditLog, settings: Settings) -> None:
        self._audit = audit
        self._settings = settings

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record(
        self,
        *,
        amount_usd: float,
        model: str,
        input_tokens: int,
        output_tokens: int,
        run_id: str,
        event_id: str | None = None,
    ) -> None:
        """Add a spend row. Keep the payload narrow so json_extract is fast."""
        self._audit.append(
            self.SPEND_EVENT,
            {
                "amount_usd": float(amount_usd),
                "model": model,
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "run_id": run_id,
                "event_id": event_id,
            },
        )

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _since_ns(self, days: int) -> int:
        return time.time_ns() - days * _SECONDS_PER_DAY * _NS_PER_SECOND

    def spent_in_window(self, days: int) -> float:
        return self._audit.sum_payload_numeric(
            self.SPEND_EVENT, "amount_usd", since_ns=self._since_ns(days)
        )

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------

    def evaluate(self) -> SpendDecision:
        """Should the orchestrator be allowed to start another run right now?"""
        s = self._settings
        spent_today = self.spent_in_window(1)
        spent_week = self.spent_in_window(7)
        spent_month = self.spent_in_window(30)

        common = {
            "spent_today_usd": round(spent_today, 4),
            "spent_this_week_usd": round(spent_week, 4),
            "spent_this_month_usd": round(spent_month, 4),
        }

        # Daily takes precedence — it's the most likely to trip and the
        # quickest signal that something is misbehaving.
        if spent_today >= s.daily_spend_cap_usd:
            return SpendDecision(
                allowed=False,
                reason="daily_cap_hit",
                window_tripped="daily",
                summary=(
                    f"Daily cap reached: ${spent_today:.2f} of "
                    f"${s.daily_spend_cap_usd:.2f}. Pausing."
                ),
                **common,
            )
        if spent_week >= s.weekly_spend_cap_usd:
            return SpendDecision(
                allowed=False,
                reason="weekly_cap_hit",
                window_tripped="weekly",
                summary=(
                    f"Weekly cap reached: ${spent_week:.2f} of "
                    f"${s.weekly_spend_cap_usd:.2f}. Pausing."
                ),
                **common,
            )
        if spent_month >= s.monthly_spend_cap_usd:
            return SpendDecision(
                allowed=False,
                reason="monthly_cap_hit",
                window_tripped="monthly",
                summary=(
                    f"Monthly cap reached: ${spent_month:.2f} of "
                    f"${s.monthly_spend_cap_usd:.2f}. Pausing."
                ),
                **common,
            )

        return SpendDecision(
            allowed=True,
            reason="under_caps",
            window_tripped="none",
            summary=(
                f"Spend OK — today ${spent_today:.2f}/${s.daily_spend_cap_usd:.2f}, "
                f"week ${spent_week:.2f}/${s.weekly_spend_cap_usd:.2f}, "
                f"month ${spent_month:.2f}/${s.monthly_spend_cap_usd:.2f}."
            ),
            **common,
        )

    # ------------------------------------------------------------------
    # Pricing helpers
    # ------------------------------------------------------------------

    def estimate_usd(
        self, model: str, input_tokens: int, output_tokens: int
    ) -> float:
        """Best-effort token→USD estimate.

        We classify by model-name substring rather than an exact match so
        a minor revision (e.g. "claude-sonnet-4-6-2026-XX-XX") still
        routes to the sonnet price card. Unknown models fall back to
        sonnet rates, which is the conservative direction.
        """
        s = self._settings
        m = model.lower()
        if "opus" in m:
            return self._mtok(input_tokens, s.price_opus_input_per_mtok) + self._mtok(
                output_tokens, s.price_opus_output_per_mtok
            )
        if "haiku" in m:
            return self._mtok(input_tokens, s.price_haiku_input_per_mtok) + self._mtok(
                output_tokens, s.price_haiku_output_per_mtok
            )
        # Sonnet (and unknown — sonnet rates as default).
        return self._mtok(input_tokens, s.price_sonnet_input_per_mtok) + self._mtok(
            output_tokens, s.price_sonnet_output_per_mtok
        )

    @staticmethod
    def _mtok(tokens: int, per_mtok_usd: float) -> float:
        return (tokens / 1_000_000.0) * per_mtok_usd
