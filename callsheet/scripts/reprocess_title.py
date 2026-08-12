"""Re-derive a title's corpus from stored payloads, without paying to collect it again.

The trigger for E03-S04. Data ops runs this after a mapping fix or a model upgrade:

    uv run python -m scripts.reprocess_title --title-id <uuid>
    uv run python -m scripts.reprocess_title --title-id <uuid> --from 2026-07-01 --until 2026-08-11

A command rather than an HTTP route on purpose. This is an internal operation with no
persona outside the team, it can run for a long time over a six-week corpus, and it takes
no request body worth modelling — the same reasoning that puts `seed_pilot_user` here.

It cannot spend money: `ReprocessService` is built without a collection source, so there
is no path from this command to a provider. Until E04 supplies an analysis pipeline the
bound analyzer refuses, and the command says so and exits non-zero rather than reporting
a run that did nothing.
"""

import argparse
import asyncio
import sys
import uuid
from datetime import UTC, datetime

from app.core.exceptions import DomainError
from app.db.session import session_factory
from app.services.analysis.mention_analyzer import MentionAnalyzer
from app.services.reprocess_service import ReprocessResult, ReprocessService


def _parse_day(value: str, *, end_of_day: bool) -> datetime:
    """A calendar day on the command line, as an instant in UTC.

    Bounds are inclusive at both ends, so `--until 2026-08-11` means the whole of the
    11th rather than midnight at its start — the reading anyone typing a date expects,
    and the one that stops a day's posts being silently excluded from their own window.
    """
    try:
        day = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"{value!r} is not a date in YYYY-MM-DD form") from error
    if end_of_day:
        return day.replace(hour=23, minute=59, second=59, microsecond=999999)
    return day


async def reprocess_title(
    title_id: uuid.UUID,
    analyzer: MentionAnalyzer,
    *,
    posted_from: datetime | None,
    posted_until: datetime | None,
) -> ReprocessResult:
    async with session_factory() as session:
        service = ReprocessService(session, analyzer)
        return await service.reprocess_title(
            title_id, posted_from=posted_from, posted_until=posted_until
        )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Recompute a title's derived fields from stored payloads."
    )
    parser.add_argument("--title-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--from",
        dest="posted_from",
        type=lambda value: _parse_day(value, end_of_day=False),
        help="Only posts published on or after this day (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--until",
        dest="posted_until",
        type=lambda value: _parse_day(value, end_of_day=True),
        help="Only posts published on or before this day (YYYY-MM-DD).",
    )
    return parser


def main() -> int:
    arguments = _build_parser().parse_args()

    # Resolved here rather than injected, because this process has no FastAPI request to
    # hang a dependency off. It is the same binding the application uses.
    from app.api.deps import get_mention_analyzer

    try:
        result = asyncio.run(
            reprocess_title(
                arguments.title_id,
                get_mention_analyzer(),
                posted_from=arguments.posted_from,
                posted_until=arguments.posted_until,
            )
        )
    except DomainError as error:
        print(f"Reprocess did not run: {error.message}", file=sys.stderr)
        return 1

    print(
        f"pipeline_version={result.pipeline_version} "
        f"examined={result.examined} analyzed={result.analyzed} "
        f"already_analyzed={result.already_analyzed} remapped={result.remapped} "
        f"unreadable={result.unreadable} unverifiable={result.unverifiable} "
        f"missing_payload={result.missing_payload} "
        f"collection_calls={result.collection_calls}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
