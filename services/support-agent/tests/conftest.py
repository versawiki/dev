"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from versawiki_support.agent import SupportAgent
from versawiki_support.escalation.queue import EscalationQueue
from versawiki_support.escalation.notify import StubNotifier
from versawiki_support.knowledge_base import KnowledgeBase
from versawiki_support.llm import StubSupportLLM
from versawiki_support.storage import ConversationStore


REPO_ROOT = Path(__file__).resolve().parents[1]
KB_ROOT = REPO_ROOT / "kb"


@pytest.fixture
def stub_llm() -> StubSupportLLM:
    return StubSupportLLM()


@pytest.fixture
def kb() -> KnowledgeBase:
    return KnowledgeBase.load(KB_ROOT)


@pytest.fixture
def tmp_store(tmp_path: Path) -> ConversationStore:
    return ConversationStore(tmp_path / "conversations")


@pytest.fixture
def tmp_queue(tmp_path: Path) -> EscalationQueue:
    return EscalationQueue(tmp_path / "escalations")


@pytest.fixture
def stub_notifier() -> StubNotifier:
    return StubNotifier()


@pytest.fixture
def agent(
    stub_llm: StubSupportLLM,
    kb: KnowledgeBase,
    tmp_store: ConversationStore,
    tmp_queue: EscalationQueue,
    stub_notifier: StubNotifier,
) -> SupportAgent:
    return SupportAgent(
        llm=stub_llm,
        kb=kb,
        store=tmp_store,
        queue=tmp_queue,
        notifier=stub_notifier,
    )
