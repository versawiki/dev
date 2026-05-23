"""SupportAgent — the main loop.

handle_message():
    1. Append the (already-redacted) customer message to the conversation.
    2. Hydrate context: KB matches (top-N) + tenant state where known.
    3. Render the system prompt with the safe/forbidden action lists.
    4. Call the LLM.
    5. Vet any tool calls:
       a. Reject anything whose intent matches a forbidden action.
       b. Reject anything not in SAFE_ACTIONS.
       c. Run the per-action gate; deny / verify / allow.
    6. Execute allowed actions; collect results.
    7. Append the agent's reply to the conversation.
    8. If escalate (explicit, or confidence < 0.7, or any forbidden
       attempt with severity != low, or any cross-tenant attempt),
       write an escalation entry and mark the conversation escalated.
       Otherwise mark resolved_by_agent.
    9. Persist via the ConversationStore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .conversation import Conversation
from .escalation.notify import Notifier
from .escalation.queue import EscalationEntry, EscalationQueue
from .forbidden_actions import find_forbidden
from .knowledge_base import KnowledgeBase
from .llm import SYSTEM_PROMPT_TEMPLATE, SupportLLM
from .messages import Message, new_customer_message
from .safe_actions import (
    SAFE_ACTIONS,
    ActionExecution,
    execute_action,
)
from .storage import ConversationStore


CONFIDENCE_THRESHOLD = 0.7


@dataclass
class AgentResponse:
    """What handle_message returns to the channel adapter."""

    conversation: Conversation
    reply_text: str
    actions_executed: list[ActionExecution] = field(default_factory=list)
    escalated: bool = False
    escalation_reason: str | None = None
    audited: list[str] = field(default_factory=list)


def _render_safe_action_list() -> str:
    return "\n".join(
        f"- {a.name}: {a.description}" for a in SAFE_ACTIONS.values()
    )


def _render_forbidden_action_list() -> str:
    from .forbidden_actions import FORBIDDEN_ACTIONS

    return "\n".join(f"- {a.name}: {a.description}" for a in FORBIDDEN_ACTIONS)


def render_system_prompt() -> str:
    return SYSTEM_PROMPT_TEMPLATE.format(
        safe_actions=_render_safe_action_list(),
        forbidden_actions=_render_forbidden_action_list(),
    )


@dataclass
class SupportAgent:
    """Drives the support loop."""

    llm: SupportLLM
    kb: KnowledgeBase
    store: ConversationStore
    queue: EscalationQueue
    notifier: Notifier | None = None
    confidence_threshold: float = CONFIDENCE_THRESHOLD

    # ----- public surface -----

    def handle_customer_text(
        self,
        conversation: Conversation,
        text: str,
    ) -> AgentResponse:
        msg = new_customer_message(text)
        return self.handle_message(conversation, msg)

    def handle_message(
        self,
        conversation: Conversation,
        message: Message,
    ) -> AgentResponse:
        # 1. Append customer message
        conversation.append(message)

        # 2. Hydrate context
        self.kb.maybe_reload()
        kb_matches = self.kb.search(message.text, limit=3)

        # 3. System prompt
        system_prompt = render_system_prompt()

        # 4. Call the LLM
        try:
            llm_resp = self.llm.reply(conversation, kb_matches, system_prompt)
        except Exception as exc:  # noqa: BLE001
            return self._escalate(
                conversation,
                reply_text=(
                    "Something went wrong on our side. I've passed this "
                    "to a teammate who will follow up."
                ),
                reason=f"LLM error: {exc.__class__.__name__}",
                severity="medium",
                actions_executed=[],
                audited=[f"llm exception: {exc.__class__.__name__}: {exc}"],
            )

        # 5. Vet tool calls
        actions_executed: list[ActionExecution] = []
        audited: list[str] = []
        forced_escalation: tuple[str, str] | None = None
        had_denied_action = False

        for call in llm_resp.tool_calls:
            forbidden = find_forbidden(call.name) or find_forbidden(
                _stringify_args(call.args)
            )
            if forbidden is not None:
                audited.append(
                    f"refused forbidden action {forbidden.name!r} (severity={forbidden.severity})"
                )
                if forbidden.severity != "low":
                    forced_escalation = (
                        f"forbidden action attempted: {forbidden.name}",
                        forbidden.severity,
                    )
                continue
            execution = execute_action(conversation, call.name, call.args)
            actions_executed.append(execution)
            if execution.audited:
                audited.extend(execution.audited)
            if execution.decision.status != "allow":
                had_denied_action = True

        # 6. Decide outcome
        escalate_explicit = llm_resp.escalate
        low_confidence = llm_resp.confidence < self.confidence_threshold

        if forced_escalation is not None:
            return self._escalate(
                conversation,
                reply_text=_safe_refusal(llm_resp.reply_text),
                reason=forced_escalation[0],
                severity=forced_escalation[1],
                actions_executed=actions_executed,
                audited=audited,
            )

        if escalate_explicit or low_confidence:
            return self._escalate(
                conversation,
                reply_text=llm_resp.reply_text,
                reason=(
                    llm_resp.escalation_reason
                    or ("low confidence" if low_confidence else "agent requested")
                ),
                severity=llm_resp.escalation_severity or "low",
                actions_executed=actions_executed,
                audited=audited,
            )

        # 7. Resolved by agent (or refused-action quiet path)
        reply_text = llm_resp.reply_text
        if had_denied_action:
            # The LLM may have already started narrating a denied action
            # (e.g. "Looking up tenant-b for you..."). Override the
            # reply with a safe refusal that does NOT echo the denied
            # arguments. This is the load-bearing privacy guard for
            # the cross-tenant case where we intentionally do NOT
            # escalate.
            reply_text = (
                "I can't help with that - that's outside what I'm "
                "allowed to look up for this account."
            )
        agent_msg = Message(role="agent", text=reply_text)
        conversation.append(agent_msg)
        conversation.mark_resolved()
        self.store.save(conversation)
        return AgentResponse(
            conversation=conversation,
            reply_text=reply_text,
            actions_executed=actions_executed,
            escalated=False,
            audited=audited,
        )

    # ----- internals -----

    def _escalate(
        self,
        conversation: Conversation,
        *,
        reply_text: str,
        reason: str,
        severity: str,
        actions_executed: list[ActionExecution],
        audited: list[str],
    ) -> AgentResponse:
        agent_msg = Message(role="agent", text=reply_text)
        conversation.append(agent_msg)
        conversation.mark_escalated(reason)
        # Snapshot last few messages for the reviewer's context
        tail = conversation.messages[-5:]
        entry = EscalationEntry(
            conversation_id=conversation.id,
            tenant_id=conversation.tenant_id,
            channel=conversation.channel,
            reason=reason,
            severity=severity,  # type: ignore[arg-type]
            customer_identifier=conversation.customer_identifier,
            last_messages=[m.model_dump(mode="json") for m in tail],
        )
        self.queue.append(entry)
        if self.notifier is not None:
            self.notifier.notify(entry)
        self.store.save(conversation)
        return AgentResponse(
            conversation=conversation,
            reply_text=reply_text,
            actions_executed=actions_executed,
            escalated=True,
            escalation_reason=reason,
            audited=audited,
        )


def _stringify_args(args: dict[str, Any]) -> str:
    return " ".join(f"{k}={v}" for k, v in args.items())


def _safe_refusal(maybe_reply: str) -> str:
    """Replace an LLM reply that promised a forbidden action with a refusal.

    Conservative: if the LLM reply already reads like a refusal, keep
    it; otherwise prepend the standard refusal sentence. The check is
    intentionally loose - false positives here only make the reply
    slightly redundant.
    """
    lowered = maybe_reply.lower()
    if any(
        phrase in lowered
        for phrase in (
            "i can't",
            "i cannot",
            "i'm not able",
            "i am not able",
            "i'll have to escalate",
            "i'll pass this",
            "i will have to escalate",
            "passing this to",
            "let me pass",
        )
    ):
        return maybe_reply
    return (
        "I'm not able to do that myself, so I'm passing this to a "
        "teammate who will follow up. " + maybe_reply
    )


__all__ = ["SupportAgent", "AgentResponse", "render_system_prompt", "CONFIDENCE_THRESHOLD"]
