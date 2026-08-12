"""The HTTP client behind the collection port — the one thing here that leaves the process.

E03-S07 shipped `MonidTransport` as a seam whose only binding refused, on the stated
grounds that run polling belonged with the scheduler (E03-S01) and spend controls with
E09. The scheduler exists now, and this seam is the whole of what stands between a
configured deployment and a live setup preview, so this is the client that fills it.

**Monid bills at the start, not at the finish**, and that single fact drives the shape of
this class. `POST /v1/run` queues a run and charges for it; `GET /v1/runs/{id}` is then
polled until the run reaches a terminal state. So the start is never retried — a retried
start is a second invoice for a page nobody asked for twice — while polling is retried
freely, because a dropped GET costs nothing and the run it is asking about is already paid
for. For the same reason nothing here gives up early on a slow run: the money is spent
either way, and abandoning the wait throws away the result as well as the fee.

**Every failure raises.** There is no path through this class that returns an empty page.
An empty page is indistinguishable from "nobody is talking about this film", which is the
one wrong answer a collection layer must never give — the same rule the unconfigured
binding follows, held to on the configured path too.
"""

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import httpx
import structlog

from app.core.collection_endpoints import EndpointDescriptor
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError
from app.services.collection.adapters import ProviderRequest
from app.services.collection.monid_source import MonidTransport

_logger = structlog.get_logger(__name__)

_RUN_PATH = "/v1/run"

_COMPLETED_STATUS = "COMPLETED"
_BLOCKED_STATUS = "BLOCKED"
# READY and RUNNING are the two states a run can still leave on its own; everything else
# is final and polling stops. A status this client has never heard of is treated as
# non-terminal and eventually times out, which is the safe way round — the alternative is
# reading an unknown state as success and handing an adapter a body that is not there.
_TERMINAL_STATUSES = frozenset(
    {_COMPLETED_STATUS, "FAILED", _BLOCKED_STATUS, "STOPPED", "TIME_OUT"}
)

# Below this the provider answered; at or above it, it returned an error document. The
# distinction matters because an error document parses perfectly well as "no posts".
_FIRST_ERROR_HTTP_STATUS = 400

# Written for the studio, because the setup preview renders these verbatim. What went
# wrong operationally goes to the log instead, where the person who can act on it is.
UNREACHABLE_MESSAGE = (
    "The search provider could not be reached just now, so there are no posts to show. "
    "Nothing has been saved — try again in a moment."
)
RUN_FAILED_MESSAGE = (
    "The search provider returned an error instead of results, so there are no posts to "
    "show. This is not a problem with your title."
)
RUN_BLOCKED_MESSAGE = (
    "A spending limit on this deployment stopped the search before it ran, so there are "
    "no posts to show. An administrator can raise or pause that limit."
)
RUN_TIMED_OUT_MESSAGE = (
    "The search provider did not finish in time, so there are no posts to show. "
    "Try again in a moment."
)
EMPTY_RESPONSE_MESSAGE = (
    "The search provider finished without returning anything to read, so there are no "
    "posts to show. Try again in a moment."
)


class HttpMonidTransport(MonidTransport):
    """One call to Monid, waited out, returned as the provider's own response body.

    Holds no knowledge of platforms, queries or mentions — the adapter built the request
    and the adapter will read the reply. This knows only how to get one across the wire
    and how to tell "the provider answered" apart from the four ways that can fail.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        # Stripped for the same reason `is_collection_configured` strips before deciding
        # this transport should exist at all. A key pasted with a trailing newline — the
        # commonest thing to happen to a secret between a dashboard and a `.env` — would
        # otherwise pass the "configured" test and then be sent as `Bearer <key>\n`, so the
        # deployment would look wired up while every call failed auth. The two must agree
        # about what the key is, not just about whether there is one.
        self._api_key = settings.monid_api_key.strip()
        self._base_url = settings.monid_base_url.rstrip("/")
        self._request_timeout = settings.monid_request_timeout_seconds
        self._run_timeout = settings.monid_run_timeout_seconds
        self._poll_interval = settings.monid_poll_interval_seconds
        # The wire, injectable. A test can hand this an `httpx.MockTransport` and exercise
        # every branch below — a blocked run, a provider 429, a run that never finishes —
        # none of which can be reached by paying for a call that succeeds. Left as None in
        # every real binding, where httpx supplies its own.
        self._http_transport = http_transport

    async def run(self, endpoint: EndpointDescriptor, request: ProviderRequest) -> Any:
        started_at = time.perf_counter()
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=self._request_timeout,
            transport=self._http_transport,
        ) as client:
            started = await self._start_run(client, endpoint, request)
            run_id = _read_run_id(started)
            finished = await self._wait_for_terminal_state(client, started, run_id, endpoint)

        self._log_outcome(finished, endpoint, run_id, started_at)
        return _read_provider_body(finished, endpoint, run_id)

    def _headers(self) -> dict[str, str]:
        """`X-Monid-Client` names this application, so a run can be traced to what made it."""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Monid-Client": "callsheet",
        }

    async def _start_run(
        self,
        client: httpx.AsyncClient,
        endpoint: EndpointDescriptor,
        request: ProviderRequest,
    ) -> Mapping[str, Any]:
        """Queues the run. **This is the billed call**, and it is made exactly once."""
        try:
            response = await client.post(_RUN_PATH, json=_build_run_payload(endpoint, request))
        except httpx.HTTPError as error:
            _logger.exception(
                "collection.transport.unreachable",
                endpoint=endpoint.key,
                provider=endpoint.provider,
                reason=str(error),
            )
            raise ServiceUnavailableError(UNREACHABLE_MESSAGE) from error
        return _require_ok(response, endpoint, action="start")

    async def _wait_for_terminal_state(
        self,
        client: httpx.AsyncClient,
        started: Mapping[str, Any],
        run_id: str,
        endpoint: EndpointDescriptor,
    ) -> Mapping[str, Any]:
        """Polls until the run stops moving, or until the deadline.

        The deadline is a ceiling on waiting, not a retry budget — hitting it raises
        rather than starting a second run, because the first one has been paid for and may
        still be on its way. An operator who sees this in the log is looking at a provider
        that has gone slow, and the fix is patience or a different endpoint, never another
        call.
        """
        run = started
        deadline = time.monotonic() + self._run_timeout
        polls = 0

        while str(run.get("status", "")) not in _TERMINAL_STATUSES:
            if time.monotonic() >= deadline:
                _logger.error(
                    "collection.transport.run_timed_out",
                    endpoint=endpoint.key,
                    run_id=run_id,
                    status=str(run.get("status", "")),
                    waited_seconds=round(self._run_timeout, 1),
                    polls=polls,
                )
                raise ServiceUnavailableError(RUN_TIMED_OUT_MESSAGE)
            await asyncio.sleep(self._poll_interval)
            polls += 1
            run = await self._read_run(client, run_id, endpoint)

        return run

    async def _read_run(
        self, client: httpx.AsyncClient, run_id: str, endpoint: EndpointDescriptor
    ) -> Mapping[str, Any]:
        """One status check. Safe to repeat — it neither starts nor bills anything."""
        try:
            response = await client.get(f"/v1/runs/{run_id}")
        except httpx.HTTPError as error:
            _logger.exception(
                "collection.transport.poll_failed",
                endpoint=endpoint.key,
                run_id=run_id,
                reason=str(error),
            )
            raise ServiceUnavailableError(UNREACHABLE_MESSAGE) from error
        return _require_ok(response, endpoint, action="poll")

    @staticmethod
    def _log_outcome(
        run: Mapping[str, Any],
        endpoint: EndpointDescriptor,
        run_id: str,
        started_at: float,
    ) -> None:
        """Info, with the cost on it, because this line is what an invoice reconciles to.

        The run id is Monid's own, so a charge queried months later can be traced back to
        the title that caused it — which is the record E09 needs and cannot reconstruct.
        """
        cost = run.get("cost")
        cost_usd = cost.get("value") if isinstance(cost, Mapping) else None
        _logger.info(
            "collection.transport.run_completed",
            endpoint=endpoint.key,
            provider=endpoint.provider,
            run_id=run_id,
            status=str(run.get("status", "")),
            price_model=str(endpoint.price_model),
            cost_usd=cost_usd,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 1),
        )


def _build_run_payload(endpoint: EndpointDescriptor, request: ProviderRequest) -> dict[str, Any]:
    """The three parts of a provider call, in the envelope Monid's runner takes them in.

    Empty sections are omitted rather than sent as `{}` — tikhub pages on a query string
    and apify on a JSON body, and a call carrying an empty half of the other one is a call
    that reads as malformed to whichever provider is serving the platform this week.
    """
    call_input: dict[str, Any] = {}
    if request.body:
        call_input["body"] = dict(request.body)
    if request.query_params:
        call_input["queryParams"] = dict(request.query_params)
    if request.path_params:
        call_input["pathParams"] = dict(request.path_params)

    payload: dict[str, Any] = {"provider": endpoint.provider, "endpoint": endpoint.path}
    if call_input:
        payload["input"] = call_input
    return payload


def _require_ok(
    response: httpx.Response, endpoint: EndpointDescriptor, *, action: str
) -> Mapping[str, Any]:
    """Monid's own HTTP layer — auth, quota, malformed request — before the provider's."""
    if response.is_success:
        body = _read_json(response, endpoint, action=action)
        if isinstance(body, Mapping):
            return body
        _logger.error(
            "collection.transport.unexpected_body",
            endpoint=endpoint.key,
            action=action,
            body_type=type(body).__name__,
        )
        raise ServiceUnavailableError(UNREACHABLE_MESSAGE)

    _logger.error(
        "collection.transport.rejected",
        endpoint=endpoint.key,
        provider=endpoint.provider,
        action=action,
        http_status=response.status_code,
        # Truncated: a provider's error page can be a whole HTML document, and this line
        # is meant to be readable in a log tail.
        detail=response.text[:500],
    )
    raise ServiceUnavailableError(UNREACHABLE_MESSAGE)


def _read_json(response: httpx.Response, endpoint: EndpointDescriptor, *, action: str) -> Any:
    try:
        return response.json()
    except ValueError as error:
        _logger.error(
            "collection.transport.unreadable_body",
            endpoint=endpoint.key,
            action=action,
            reason=str(error),
        )
        raise ServiceUnavailableError(UNREACHABLE_MESSAGE) from error


def _read_run_id(started: Mapping[str, Any]) -> str:
    """A run with no id cannot be polled, so this fails immediately rather than at the wait."""
    run_id = started.get("runId")
    if isinstance(run_id, str) and run_id:
        return run_id
    _logger.error("collection.transport.missing_run_id", keys=sorted(started))
    raise ServiceUnavailableError(UNREACHABLE_MESSAGE)


def _read_provider_body(run: Mapping[str, Any], endpoint: EndpointDescriptor, run_id: str) -> Any:
    """The provider's response, verbatim, or a refusal explaining which way this went wrong.

    Four terminal states are not success and each needs different words. `BLOCKED` gets
    its own message because it is the only one somebody can fix from a dashboard rather
    than by waiting: a workspace budget or run cap stopped the call before it happened.
    """
    status = str(run.get("status", ""))
    if status != _COMPLETED_STATUS:
        _logger.error(
            "collection.transport.run_unsuccessful",
            endpoint=endpoint.key,
            provider=endpoint.provider,
            run_id=run_id,
            status=status,
            error=run.get("error"),
            controls=run.get("controls"),
        )
        raise ServiceUnavailableError(
            RUN_BLOCKED_MESSAGE if status == _BLOCKED_STATUS else RUN_FAILED_MESSAGE
        )

    provider_response = run.get("providerResponse")
    if isinstance(provider_response, Mapping):
        _ensure_provider_answered(provider_response, endpoint, run_id)
        data = provider_response.get("data")
        if data is not None:
            return data

    # Older shapes, and endpoints Monid serves itself, put the body here instead.
    output = run.get("output")
    if output is None:
        _logger.error(
            "collection.transport.empty_output",
            endpoint=endpoint.key,
            run_id=run_id,
            keys=sorted(run),
        )
        raise ServiceUnavailableError(EMPTY_RESPONSE_MESSAGE)
    return output


def _ensure_provider_answered(
    provider_response: Mapping[str, Any], endpoint: EndpointDescriptor, run_id: str
) -> None:
    """A completed run can still carry the provider's 4xx, and that is not a page of posts.

    Monid reports the *run* as COMPLETED whenever it successfully made the call, including
    when the provider answered with a rate limit or an authentication failure. Handing
    that document to the adapter would produce zero readable items and a page reading as
    silence, which is the exact failure this whole layer refuses to have.
    """
    http_status = provider_response.get("httpStatus")
    if isinstance(http_status, int) and http_status >= _FIRST_ERROR_HTTP_STATUS:
        _logger.error(
            "collection.transport.provider_error",
            endpoint=endpoint.key,
            provider=endpoint.provider,
            run_id=run_id,
            provider_http_status=http_status,
            detail=str(provider_response.get("error"))[:500],
        )
        raise ServiceUnavailableError(RUN_FAILED_MESSAGE)
