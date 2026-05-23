"""Web intake — FastAPI POST /support/web/messages.

A future chat widget calls this synchronously; the response carries
the agent's reply. The endpoint expects a JSON body:

    {
      "conversation_id": "conv_..." | null,  # null => new conversation
      "tenant_id": "..." | null,
      "customer_identifier": "user@example.com" | null,
      "text": "..."
    }

It returns:

    {
      "conversation_id": "...",
      "reply": "...",
      "status": "resolved_by_agent" | "escalated" | "open",
      "escalated": bool
    }
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..agent import SupportAgent
from ..conversation import Conversation


class WebMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    tenant_id: str | None = None
    customer_identifier: str | None = None
    text: str = Field(min_length=1, max_length=20_000)


class WebMessageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    reply: str
    status: str
    escalated: bool


# In-memory conversation map for v1. Production reads/writes via store.
_THREADS: dict[str, Conversation] = {}


def _resolve_conversation(payload: WebMessageIn) -> Conversation:
    if payload.conversation_id is not None:
        conv = _THREADS.get(payload.conversation_id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return conv
    conv = Conversation(
        channel="web",
        tenant_id=payload.tenant_id,
        customer_identifier=payload.customer_identifier,
    )
    _THREADS[conv.id] = conv
    return conv


def build_web_app(agent: SupportAgent) -> FastAPI:
    """Build a FastAPI app that exposes the web intake route."""
    router = APIRouter()

    @router.post("/support/web/messages", response_model=WebMessageOut)
    def post_message(payload: WebMessageIn) -> WebMessageOut:
        conv = _resolve_conversation(payload)
        response = agent.handle_customer_text(conv, payload.text)
        return WebMessageOut(
            conversation_id=conv.id,
            reply=response.reply_text,
            status=conv.status,
            escalated=response.escalated,
        )

    app = FastAPI(title="versawiki-support-web")
    app.include_router(router)
    return app


def _reset_threads_for_tests() -> None:
    """Test helper: clear the in-memory thread cache between tests."""
    _THREADS.clear()


__all__ = [
    "build_web_app",
    "WebMessageIn",
    "WebMessageOut",
    "_reset_threads_for_tests",
]
