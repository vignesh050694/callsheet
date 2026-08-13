"""Tests for the live Monid transport that fills the seam E03-S07 left refusing.

`HttpMonidTransport` (`app/services/collection/monid_transport.py`) is the one class in
the collection layer that leaves the process. Monid is a two-step API — `POST /v1/run`
starts and *bills* a run, `GET /v1/runs/{id}` is polled until it reaches a terminal
status — and that shape is what these tests are aimed at: does polling actually advance
past a non-terminal state, is the billed call ever repeated, and does a run Monid marks
COMPLETED but whose provider answered with an error get told apart from a real page of
posts. `CollectionSourcePreviewSearch` (`app/services/collection/preview_source.py`) and
the `app/api/deps.py` bindings that choose between the live and refusing implementations
are covered too, since both exist only to plug this transport into the rest of the app.

No test here makes a live network call. `HttpMonidTransport` accepts an injected
`http_transport: httpx.AsyncBaseTransport`, and every test hands it an `httpx.MockTransport`
backed by a small scripted wire (`_ScriptedMonidWire` below) or, for the preview mapping
test, a fake `CollectionSource` with no HTTP involved at all. `monid_run_timeout_seconds`
and `monid_poll_interval_seconds` are always set to small values (`_fast_settings`) so the
polling and timeout tests run in milliseconds rather than the real 120-second default.

One test reads the committed real capture at
`tests/fixtures/collection/x_tikhub_search_timeline.json` as `providerResponse.data`,
rather than a synthetic dict, because that is what actually proves the transport hands
the adapter a body the adapter can read — the same fixture Section 1 of
`test_provider_agnostic_collection_interface.py` reads through `FixtureTransport`, this
time carried through the real wire-parsing path instead of a hand-built double.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.api.deps import get_collection_source, get_monid_transport, get_preview_search
from app.core.collection_endpoints import get_endpoint
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.core.platforms import Platform
from app.services.collection.adapters import ProviderRequest
from app.services.collection.mention_shape import NormalizedMention
from app.services.collection.monid_source import MonidCollectionSource, UnconfiguredMonidTransport
from app.services.collection.monid_transport import (
    RUN_BLOCKED_MESSAGE,
    RUN_FAILED_MESSAGE,
    RUN_TIMED_OUT_MESSAGE,
    HttpMonidTransport,
)
from app.services.collection.preview_source import CollectionSourcePreviewSearch
from app.services.collection.source import CollectedItem, CollectionPage, CollectionSource
from app.services.preview_search import UnconfiguredPreviewSearch

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "collection"
TIKHUB_RESPONSE: dict[str, Any] = json.loads(
    (FIXTURES_DIR / "x_tikhub_search_timeline.json").read_text()
)["response"]

X_TIKHUB_ENDPOINT = get_endpoint("x.tikhub_search_timeline")
assert X_TIKHUB_ENDPOINT is not None

# ---------------------------------------------------------------------------
# The scripted wire: a MockTransport handler that answers POST /v1/run once and
# GET /v1/runs/{id} from a queue of poll bodies, recording every request so a test can
# assert on call counts and on exactly what was sent.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RunScript:
    """What the transport sees on the wire for one run.

    `start` answers the single POST /v1/run. `polls` answers GET /v1/runs/{id} calls in
    order; once exhausted, the last entry repeats — so a run that never leaves RUNNING
    only has to be scripted once, and a run that reaches COMPLETED after two polls only
    needs two entries.
    """

    start: dict[str, Any]
    polls: list[dict[str, Any]] = field(default_factory=list)


class _ScriptedMonidWire:
    """A fake Monid, answering exactly what `_RunScript` says and nothing more.

    Records the POST and GET counts separately because the sharpest thing under test in
    this file is that the POST — the billed call — never happens more than once, no
    matter how many times the GET side is asked.
    """

    def __init__(self, script: _RunScript) -> None:
        self._script = script
        self._next_poll = 0
        self.post_count = 0
        self.get_count = 0
        self.last_request: httpx.Request | None = None

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        if request.method == "POST":
            self.post_count += 1
            return httpx.Response(200, json=self._script.start)

        self.get_count += 1
        polls = self._script.polls
        if not polls:
            return httpx.Response(200, json=self._script.start)
        index = min(self._next_poll, len(polls) - 1)
        self._next_poll += 1
        return httpx.Response(200, json=polls[index])


def _fast_settings(
    *, api_key: str = "test-key", run_timeout: float = 1.0, poll_interval: float = 0.01
) -> Settings:
    """A poll interval and run timeout small enough that these tests run in
    milliseconds rather than the real 120-second/2-second defaults."""
    return Settings(
        monid_api_key=api_key,
        monid_run_timeout_seconds=run_timeout,
        monid_poll_interval_seconds=poll_interval,
        monid_request_timeout_seconds=5.0,
    )


def _http_transport(wire: _ScriptedMonidWire, **settings_kwargs: Any) -> HttpMonidTransport:
    return HttpMonidTransport(
        _fast_settings(**settings_kwargs), http_transport=httpx.MockTransport(wire)
    )


# ---------------------------------------------------------------------------
# Polling: the run genuinely has to leave RUNNING on its own, not just be already
# finished on the first check.
# ---------------------------------------------------------------------------


async def test_a_run_that_starts_running_reaches_completed_after_polling_and_returns_the_body() -> (
    None
):
    """The run reports RUNNING on the first poll and only turns COMPLETED on the
    second — proof that the wait loop actually advances rather than only handling the
    already-finished case."""
    wire = _ScriptedMonidWire(
        _RunScript(
            start={"runId": "run-1", "status": "RUNNING"},
            polls=[
                {"runId": "run-1", "status": "RUNNING"},
                {
                    "runId": "run-1",
                    "status": "COMPLETED",
                    "providerResponse": {"httpStatus": 200, "data": {"posts": ["a", "b"]}},
                },
            ],
        )
    )
    transport = _http_transport(wire)

    body = await transport.run(X_TIKHUB_ENDPOINT, ProviderRequest(query_params={"keyword": "x"}))

    assert body == {"posts": ["a", "b"]}
    assert wire.post_count == 1
    assert wire.get_count == 2


# ---------------------------------------------------------------------------
# providerResponse.data is preferred; output is the fallback when there is no
# providerResponse at all.
# ---------------------------------------------------------------------------


async def test_completed_run_reads_the_real_tikhub_fixture_from_provider_response_data() -> None:
    """Uses the committed capture as `providerResponse.data`, with a different `output`
    present alongside it, so this proves both that the transport hands the adapter a
    body it can actually read and that `data` wins over `output` when both are there —
    not just that the code takes the `data` branch when `output` happens to be absent."""
    wire = _ScriptedMonidWire(
        _RunScript(
            start={
                "runId": "run-2",
                "status": "COMPLETED",
                "providerResponse": {"httpStatus": 200, "data": TIKHUB_RESPONSE},
                "output": {"this": "must not be what gets read"},
            }
        )
    )
    transport = HttpMonidTransport(_fast_settings(), http_transport=httpx.MockTransport(wire))
    source = MonidCollectionSource(transport, _fast_settings())

    page = await source.fetch(Platform.X, "Lokesh Kanagaraj DC", limit=20)

    assert len(page.items) == 20
    assert len(page.readable_items) == 20
    assert all(isinstance(item.mention, NormalizedMention) for item in page.items)
    assert wire.post_count == 1


async def test_output_is_used_as_the_fallback_when_there_is_no_provider_response() -> None:
    wire = _ScriptedMonidWire(
        _RunScript(start={"runId": "run-3", "status": "COMPLETED", "output": {"posts": []}})
    )
    transport = _http_transport(wire)

    body = await transport.run(X_TIKHUB_ENDPOINT, ProviderRequest())

    assert body == {"posts": []}


# ---------------------------------------------------------------------------
# A COMPLETED run whose provider answered with an error must raise, not return the
# error document as if it were a page of posts.
# ---------------------------------------------------------------------------


async def test_completed_run_with_a_provider_rate_limit_raises_not_the_document() -> None:
    """Monid marks the *run* COMPLETED whenever it successfully made the call to the
    provider, even when the provider itself answered 429. Handing that document to the
    adapter would produce a page with zero readable items — reading as "nobody is
    talking about this film" rather than as a rate limit."""
    wire = _ScriptedMonidWire(
        _RunScript(
            start={
                "runId": "run-4",
                "status": "COMPLETED",
                "providerResponse": {
                    "httpStatus": 429,
                    "data": {"timeline": []},
                    "error": "rate limited",
                },
            }
        )
    )
    transport = _http_transport(wire)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await transport.run(X_TIKHUB_ENDPOINT, ProviderRequest())

    assert str(exc_info.value) == RUN_FAILED_MESSAGE


# ---------------------------------------------------------------------------
# The other two terminal failure statuses, each with its own message.
# ---------------------------------------------------------------------------


async def test_blocked_run_raises_with_the_budget_specific_message() -> None:
    wire = _ScriptedMonidWire(_RunScript(start={"runId": "run-5", "status": "BLOCKED"}))
    transport = _http_transport(wire)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await transport.run(X_TIKHUB_ENDPOINT, ProviderRequest())

    assert str(exc_info.value) == RUN_BLOCKED_MESSAGE


async def test_failed_run_raises_with_the_generic_message() -> None:
    wire = _ScriptedMonidWire(_RunScript(start={"runId": "run-6", "status": "FAILED"}))
    transport = _http_transport(wire)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await transport.run(X_TIKHUB_ENDPOINT, ProviderRequest())

    assert str(exc_info.value) == RUN_FAILED_MESSAGE


# ---------------------------------------------------------------------------
# The billed call is made exactly once — across a run that needed several polls, and
# across a run that fails outright. A retried start would be a second invoice for a
# page nobody asked for twice.
# ---------------------------------------------------------------------------


async def test_the_billed_post_run_call_never_repeats_across_polling_or_across_failure() -> None:
    polling_wire = _ScriptedMonidWire(
        _RunScript(
            start={"runId": "run-7", "status": "RUNNING"},
            polls=[
                {"runId": "run-7", "status": "RUNNING"},
                {"runId": "run-7", "status": "RUNNING"},
                {"runId": "run-7", "status": "COMPLETED", "output": {"ok": True}},
            ],
        )
    )
    await _http_transport(polling_wire).run(X_TIKHUB_ENDPOINT, ProviderRequest())
    assert polling_wire.post_count == 1
    assert polling_wire.get_count == 3

    failing_wire = _ScriptedMonidWire(_RunScript(start={"runId": "run-8", "status": "BLOCKED"}))
    with pytest.raises(ServiceUnavailableError):
        await _http_transport(failing_wire).run(X_TIKHUB_ENDPOINT, ProviderRequest())
    assert failing_wire.post_count == 1


# ---------------------------------------------------------------------------
# A run that never leaves RUNNING must raise once the deadline passes, not hang.
# ---------------------------------------------------------------------------


async def test_a_run_that_never_leaves_running_raises_rather_than_hanging_forever() -> None:
    wire = _ScriptedMonidWire(_RunScript(start={"runId": "run-9", "status": "RUNNING"}))
    transport = _http_transport(wire, run_timeout=0.05, poll_interval=0.01)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await transport.run(X_TIKHUB_ENDPOINT, ProviderRequest())

    assert str(exc_info.value) == RUN_TIMED_OUT_MESSAGE
    assert wire.post_count == 1


# ---------------------------------------------------------------------------
# The outbound request: provider, endpoint, only the non-empty parts of `input`, and
# a bearer token built from the configured key.
# ---------------------------------------------------------------------------


async def test_the_run_request_carries_provider_endpoint_non_empty_input_and_bearer_auth() -> (
    None
):
    wire = _ScriptedMonidWire(
        _RunScript(start={"runId": "run-10", "status": "COMPLETED", "output": {}})
    )
    transport = _http_transport(wire, api_key="secret-key")
    request = ProviderRequest(
        query_params={"keyword": "Lokesh Kanagaraj DC", "search_type": "Latest"}
    )

    await transport.run(X_TIKHUB_ENDPOINT, request)

    assert wire.last_request is not None
    sent_body = json.loads(wire.last_request.content)
    assert sent_body == {
        "provider": "tikhub",
        "endpoint": "/api/v1/twitter/web/fetch_search_timeline",
        # No "body" or "pathParams" keys: this request carried neither, and an empty
        # section sent as `{}` reads as malformed to a provider expecting it absent.
        "input": {"queryParams": {"keyword": "Lokesh Kanagaraj DC", "search_type": "Latest"}},
    }
    assert wire.last_request.headers["authorization"] == "Bearer secret-key"


# ---------------------------------------------------------------------------
# CollectionSourcePreviewSearch: maps a page to SamplePosts, skipping unreadable
# items rather than failing the whole preview. No HTTP involved — a fake
# CollectionSource stands in directly.
# ---------------------------------------------------------------------------


class _FakeCollectionSource(CollectionSource):
    """Hands back one fixed page and records what it was asked for."""

    def __init__(self, page: CollectionPage) -> None:
        self._page = page
        self.calls: list[tuple[Platform, str, str | None, int]] = []

    async def fetch(
        self, platform: Platform, query: str, *, page: str | None = None, limit: int
    ) -> CollectionPage:
        self.calls.append((platform, query, page, limit))
        return self._page


def _normalized_mention(external_id: str) -> NormalizedMention:
    return NormalizedMention(
        platform=Platform.X,
        external_id=external_id,
        text="A post about the film.",
        posted_at=datetime(2026, 8, 12, tzinfo=UTC),
        author_handle="handle",
        author_display_name="Display Name",
        platform_reported_language="en",
    )


async def test_collection_source_preview_search_maps_readable_items_and_skips_the_rest() -> None:
    page = CollectionPage(
        platform=Platform.X,
        endpoint=X_TIKHUB_ENDPOINT,
        adapter_version="test",
        items=[
            CollectedItem(
                raw_payload={"id": "1"}, external_id="1", mention=_normalized_mention("1")
            ),
            CollectedItem(raw_payload={"id": "2"}, external_id="2", normalization_error="boom"),
        ],
    )
    source = _FakeCollectionSource(page)
    preview = CollectionSourcePreviewSearch(source)

    posts = await preview.search_recent("Lokesh Kanagaraj DC", limit=20)

    assert len(posts) == 1
    assert posts[0].external_id == "1"
    assert posts[0].platform_reported_language == "en"
    # The preview search's own platform (X), not anything the caller passed — there is
    # no platform parameter on the port at all.
    assert source.calls == [(Platform.X, "Lokesh Kanagaraj DC", None, 20)]


# ---------------------------------------------------------------------------
# app/api/deps.py bindings: bound on whether a key is configured, and on nothing else.
# ---------------------------------------------------------------------------


def test_deps_bindings_refuse_without_a_configured_key() -> None:
    settings = Settings(monid_api_key="", environment="local")

    transport = get_monid_transport(settings)
    source = get_collection_source(transport, settings)
    preview = get_preview_search(source, settings)

    assert isinstance(transport, UnconfiguredMonidTransport)
    assert isinstance(preview, UnconfiguredPreviewSearch)


def test_deps_bindings_return_the_live_implementations_when_a_key_is_configured() -> None:
    settings = Settings(monid_api_key="live-key", environment="local")

    transport = get_monid_transport(settings)
    source = get_collection_source(transport, settings)
    preview = get_preview_search(source, settings)

    assert isinstance(transport, HttpMonidTransport)
    assert isinstance(preview, CollectionSourcePreviewSearch)
