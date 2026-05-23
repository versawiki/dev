"""Programmatic-API intake.

Same shape as the web intake but mounted at ``/support/api/messages``
and (in production) authenticated via the customer's API key so the
``tenant_id`` doesn't need to be supplied in the body. v1 accepts the
``tenant_id`` in the body for parity with the web endpoint; M1-CS-02
wires the auth dependency.
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..agent import SupportAgent
from ..conversation import Conversation


class ApiMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str | None = None
    tenant_id: str | None = None
    customer_identifier: str | None = None
    text: str = Field(min_length=1, max_length=20_000)


class ApiMessageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: str
    reply: str
    status: str
    escalated: bool


_THREADS: dict[str, Conversation] = {}


def build_api_app(agent: SupportAgent) -> FastAPI:
    router = APIRouter()

    @router.post("/support/api/messages", response_model=ApiMessageOut)
    def post_message(payload: ApiMessageIn) -> ApiMessageOut:
        if payload.conversation_id is not None:
            conv = _THREADS.get(payload.conversation_id)
            if conv is None:
                raise HTTPException(status_code=404, detail="conversation not found")
        else:
            conv = Conversation(
                channel="api",
                tenant_id=payload.tenant_id,
                customer_identifier=payload.customer_identifier,
            )
            _THREADS[conv.id] = conv
        response = agent.handle_customer_text(conv, payload.text)
        return ApiMessageOut(
            conversation_id=conv.id,
            reply=response.reply_text,
            status=conv.status,
            escalated=response.escalated,
        )

    app = FastAPI(title="versawiki-support-api")
    app.include_router(router)
    return app


def _reset_threads_for_tests() -> None:
    _THREADS.clear()


__all__ = ["build_api_app", "ApiMessageIn", "ApiMessageOut", "_reset_threads_for_tests"]
