"""Email intake test — mocked IMAP."""

from __future__ import annotations

from versawiki_support.agent import SupportAgent
from versawiki_support.intake.email import EmailPoller, FetchedEmail
from versawiki_support.llm import StubSupportLLM, SupportLLMResponse


class FakeImap:
    def __init__(self, emails: list[FetchedEmail]) -> None:
        self._queue = list(emails)
        self.marked: list[str] = []

    def fetch_unread(self):  # type: ignore[no-untyped-def]
        out = self._queue
        self._queue = []
        return out

    def mark_read(self, message_id: str) -> None:
        self.marked.append(message_id)


def test_one_email_creates_conversation_and_replies(
    agent: SupportAgent, stub_llm: StubSupportLLM
) -> None:
    stub_llm.queue(
        SupportLLMResponse(reply_text="Hi! Here's how to get an API key.", confidence=0.9)
    )
    email = FetchedEmail(
        message_id="msg-1",
        sender="user@example.com",
        subject="API key help",
        body="How do I get an API key?",
    )
    poller = EmailPoller(client=FakeImap([email]), agent=agent)
    responses = poller.poll_once()
    assert len(responses) == 1
    assert responses[0].escalated is False
    assert poller.sent_replies
    assert poller.sent_replies[0].to == "user@example.com"
    assert poller.sent_replies[0].in_reply_to == "msg-1"
    assert poller.sent_replies[0].subject.startswith("Re: ")
    assert poller.client.marked == ["msg-1"]  # type: ignore[attr-defined]


def test_two_emails_same_sender_thread_together(
    agent: SupportAgent, stub_llm: StubSupportLLM
) -> None:
    stub_llm.queue(SupportLLMResponse(reply_text="first reply", confidence=0.9))
    stub_llm.queue(SupportLLMResponse(reply_text="second reply", confidence=0.9))

    e1 = FetchedEmail(
        message_id="m1", sender="user@example.com", subject="hi", body="first"
    )
    e2 = FetchedEmail(
        message_id="m2", sender="user@example.com", subject="hi again", body="second"
    )
    poller = EmailPoller(client=FakeImap([e1]), agent=agent)
    poller.poll_once()
    # second poll with same sender
    poller.client = FakeImap([e2])  # type: ignore[assignment]
    poller.poll_once()

    # Only one Conversation exists for that sender
    assert len(poller._threads) == 1
    conv = next(iter(poller._threads.values()))
    # 2 customer messages + 2 agent replies
    assert len(conv.messages) == 4


def test_different_senders_separate_threads(
    agent: SupportAgent, stub_llm: StubSupportLLM
) -> None:
    stub_llm.queue(SupportLLMResponse(reply_text="r1", confidence=0.9))
    stub_llm.queue(SupportLLMResponse(reply_text="r2", confidence=0.9))
    e1 = FetchedEmail(message_id="a", sender="a@x.com", subject="s", body="hi")
    e2 = FetchedEmail(message_id="b", sender="b@x.com", subject="s", body="hi")
    poller = EmailPoller(client=FakeImap([e1, e2]), agent=agent)
    poller.poll_once()
    assert len(poller._threads) == 2


def test_empty_inbox_returns_nothing(agent: SupportAgent) -> None:
    poller = EmailPoller(client=FakeImap([]), agent=agent)
    assert poller.poll_once() == []
