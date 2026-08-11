"""Tests for E02-S02 — Anchor the title to its release date so every chart reads as
before vs after.

Story: stories/E02-title-setup-identity-discovery/E02-S02-anchor-release-date-and-milestones.md

The story has one Gherkin scenario ("Owner records the release date and campaign
milestones during title setup"). Its Given/When/Then clauses map to sections below:

  - "Given: the setup form has a required release date and an optional repeatable list
    of campaign milestones, each with a name and a date" -> Section 1 (release date
    required on create, malformed values refused) and Section 2 (milestones are
    optional, each has a name and a date, stored and returned).
  - "and Given: the release date is used as the pre-release / post-release boundary
    everywhere" -> Section 3, both through the API (`phase` on each milestone) and as
    direct unit coverage of `app/core/release_phase.py`.
  - "and Given: I can add milestones later without disturbing already-collected data"
    -> Section 5 (the schedule PUT never touches the identity set) and Section 6
    (adding one milestone must not disturb the others' rows/ids).
  - "When: I save the title with a release date and three campaign milestones" / "Then:
    every time-series view ... renders a release-date divider and a marker per
    milestone" -> Section 2 (three milestones survive setup, each carries its own
    `phase`).

The story's Notes are their own testable requirements:

  - "Changing the release date after collection has started re-renders the split
    without re-collecting or re-analysing anything — the boundary is a read-time
    property." -> Section 4, the central proof: a `PUT .../schedule` that only moves
    the release date flips a milestone's `phase` with the milestone row (id, name,
    occurs_on) and the identity set (terms, collection_terms) byte-identical before and
    after.
  - "Milestone dates are the reference points spike detection explains itself against
    (E04-S05)" -> the practical consequence is that milestone identity (its id) must
    survive an edit that does not touch it; covered in Section 6.

Additional sections cover behaviour the task brief calls out explicitly: milestone-list
replacement semantics (Section 6), dedupe (Section 7), invisible-character milestone
names (Section 8), bounds (Section 9), and the access-control matrix on the new PUT
route (Section 10).

Every assertion that could be satisfied by two different rejection paths sharing a
status code asserts on the exact message or response shape, not just the status code —
mirroring the discipline `test_create_title_with_rich_identity.py` established for
E02-S01.

Sections 11-13 are regression tests added after a Stage 3 review round came back
`changes-requested` on two findings, both now fixed in the implementation:

  - Section 11 covers the high-severity finding: `max_length` was validated on the RAW
    client string, but every value stored is NFKC-normalised first, and NFKC can
    *expand* a string (ligatures and CJK compatibility characters are the common
    culprits — see `test_confirmed_nfkc_expanding_characters` for the exact expansion
    each test character undergoes). An oversized value cleared input validation, was
    written, and only then failed — on the way back out, when the read schema
    re-checked the same limit — a 500, not a 422, and on SQLite the row had already
    committed, so the title was permanently unreadable afterwards. This was not
    confined to milestones: title `name` and every identity term take the identical
    NFKC-then-store path. All four surfaces (title name, identity terms, milestone
    names on create, milestone names on the schedule PUT) are covered here, along with
    a check that a *legitimate* ligature is still accepted and normalised rather than
    rejected, and that a rejected create does not corrupt an unrelated, already-existing
    title's readability.
  - Section 12 is a static (non-executing) regression guard on the low-severity
    migration finding: the release-date backfill's `CAST(created_at AS DATE)` resolves
    in the session's timezone rather than UTC, so it was pinned to
    `(created_at AT TIME ZONE 'UTC')::date`. This is Postgres-only DDL and the suite
    runs on SQLite, so nothing here executes the migration — it only asserts on the
    migration file's own source text, which is the most this suite can honestly claim
    about it.
  - Section 13 is a single, explicitly-labelled characterisation test for a change that
    was deliberately *not* made: variation selectors (U+FE00-FE0F, Unicode category
    `Mn`) still pass as meaningful milestone names, so a milestone named with one
    renders as a blank marker. This is the same bug class already filed as E02-S06
    (found there for anchor terms; its scope now includes the milestone-name surface).
    It documents current, known-buggy behaviour — it is not a claim that this is
    correct, and it must never be "fixed" by making this test assert a 422.
"""

import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.release_phase import ReleasePhase, phase_for, phase_for_date
from app.models import Title, TitleMilestone, User
from app.models.title import MILESTONE_NAME_MAX_LENGTH, TITLE_NAME_MAX_LENGTH, TITLE_TERM_MAX_LENGTH
from app.schemas.title import MAX_MILESTONES_PER_TITLE

ORGANIZATIONS_URL = "/api/v1/organizations"
INVITATIONS_URL = "/api/v1/invitations"
ACCEPT_URL = f"{INVITATIONS_URL}/accept"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}

# Mirrors app/services/title_service.py's exact wording, so tests can tell this
# rejection apart from any other 422 that shares its status code.
EMPTY_MILESTONE_NAME_MESSAGE = "A campaign milestone needs a name"
NOT_AN_OWNER_SCHEDULE_MESSAGE = "Only an owner can change this title's release date or milestones"
TITLE_NOT_FOUND_PREFIX = "was not found"

# Mirrors TitleService.TOO_LONG_MESSAGE exactly, so tests can distinguish this
# NFKC-expansion rejection from any other 422 sharing the same status code (e.g. the
# raw-length Pydantic 422s from Section 9, whose body shape is `detail`, not `code`).
TOO_LONG_MESSAGE = (
    "{subject} is longer than {limit} characters once ligatures and compatibility "
    "characters are expanded to their standard form"
)


def _titles_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/titles"


def _title_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}"


def _schedule_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/schedule"


def _invite_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/invitations"


async def _create_organization(client: AsyncClient, payload: dict = SUN_PICTURES_PAYLOAD) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _invite(
    client: AsyncClient, organization_id: str, email: str, role: str = "viewer"
) -> dict:
    response = await client.post(_invite_url(organization_id), json={"email": email, "role": role})
    assert response.status_code == 201, response.text
    return response.json()


async def _accept(client: AsyncClient, token: str) -> None:
    response = await client.post(ACCEPT_URL, json={"token": token})
    assert response.status_code == 204, response.text


async def _make_viewer(
    owner_client: AsyncClient, viewer_client: AsyncClient, organization_id: str, email: str
) -> None:
    invitation = await _invite(owner_client, organization_id, email, "viewer")
    await _accept(viewer_client, invitation["token"])


def _create_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Vaaranam Aayiram",
        "release_date": "2026-09-11",
        "milestones": [],
        "aliases": [],
        "hashtags": [],
        "lead_cast": [],
        "directors": [],
        "music_directors": [],
    }
    payload.update(overrides)
    return payload


async def _create_title(client: AsyncClient, organization_id: str, **overrides: object) -> dict:
    response = await client.post(_titles_url(organization_id), json=_create_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _schedule_payload(release_date: str, milestones: list[dict]) -> dict:
    return {"release_date": release_date, "milestones": milestones}


async def _put_schedule(client: AsyncClient, title_id: str, **overrides: object) -> dict:
    payload = _schedule_payload("2026-09-11", [])
    payload.update(overrides)
    response = await client.put(_schedule_url(title_id), json=payload)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Section 1 — Given: the setup form has a required release date. Missing or malformed
# values are refused at create time.
# ---------------------------------------------------------------------------


async def test_release_date_is_required_on_create(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    payload = _create_payload()
    del payload["release_date"]

    response = await api_client.post(_titles_url(organization_id), json=payload)

    assert response.status_code == 422, response.text
    body = response.json()
    assert "detail" in body
    assert any(
        error["loc"][:2] == ["body", "release_date"] and error["type"] == "missing"
        for error in body["detail"]
    )


@pytest.mark.parametrize("malformed_value", ["not-a-date", "2026-13-45", "", "11-09-2026"], ids=str)
async def test_malformed_release_date_is_refused(
    api_client: AsyncClient, malformed_value: str
) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(release_date=malformed_value)
    )

    assert response.status_code == 422, response.text
    assert "detail" in response.json()


async def test_valid_release_date_is_stored_and_returned(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(api_client, organization_id, release_date="2027-01-15")

    assert body["release_date"] == "2027-01-15"


# ---------------------------------------------------------------------------
# Section 2 — Milestones are optional at create, each has a name and a date, and the
# story's own scenario (three milestones) survives a save with each carrying a phase.
# ---------------------------------------------------------------------------


async def test_title_can_be_created_with_no_milestones(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(api_client, organization_id)

    assert body["milestones"] == []


async def test_title_saved_with_three_campaign_milestones_returns_all_three(
    api_client: AsyncClient,
) -> None:
    """The story's own When/Then: save a title with a release date and three campaign
    milestones (teaser, trailer, audio launch); every one is returned, each carrying a
    marker (name + date) the UI can plot."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        release_date="2026-09-11",
        milestones=[
            {"name": "Teaser", "occurs_on": "2026-07-01"},
            {"name": "Trailer", "occurs_on": "2026-08-15"},
            {"name": "Audio Launch", "occurs_on": "2026-08-25"},
        ],
    )

    assert len(body["milestones"]) == 3
    names = {milestone["name"] for milestone in body["milestones"]}
    assert names == {"Teaser", "Trailer", "Audio Launch"}
    for milestone in body["milestones"]:
        assert milestone["phase"] in {"pre_release", "post_release"}
        assert "id" in milestone
        assert "occurs_on" in milestone


async def test_milestones_are_returned_ordered_by_date(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        release_date="2026-09-11",
        milestones=[
            {"name": "Audio Launch", "occurs_on": "2026-08-25"},
            {"name": "Teaser", "occurs_on": "2026-07-01"},
            {"name": "Trailer", "occurs_on": "2026-08-15"},
        ],
    )

    assert [m["name"] for m in body["milestones"]] == ["Teaser", "Trailer", "Audio Launch"]


async def test_same_day_milestones_have_a_deterministic_order(api_client: AsyncClient) -> None:
    """Two beats on one day must not swap places between reads.

    Date alone is not a total order. Without a tiebreaker the database is free to return
    same-day rows in whatever order it finds them, and an UPDATE that relocates a row —
    retyping one beat's label, say — can reorder the pair with no visible data change.

    NOTE: written by the implementer, not the independent tester, as the regression test
    for a round-2 review finding. Every other test in this file is the tester's.
    """
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        release_date="2026-09-11",
        milestones=[
            {"name": "trailer", "occurs_on": "2026-08-15"},
            {"name": "Bookings open", "occurs_on": "2026-08-15"},
            {"name": "Audio Launch", "occurs_on": "2026-08-15"},
        ],
    )
    expected = ["Audio Launch", "Bookings open", "trailer"]
    assert [milestone["name"] for milestone in body["milestones"]] == expected

    title_id = body["id"]
    for _ in range(3):
        response = await api_client.get(f"/api/v1/titles/{title_id}")
        assert [milestone["name"] for milestone in response.json()["milestones"]] == expected

    # Retyping one label is the operation that can move a row on disk. Ordering is on the
    # normalised name, so a case change must not move the marker.
    retyped = await api_client.put(
        f"/api/v1/titles/{title_id}/schedule",
        json={
            "release_date": "2026-09-11",
            "milestones": [
                {"name": "Trailer", "occurs_on": "2026-08-15"},
                {"name": "Bookings open", "occurs_on": "2026-08-15"},
                {"name": "Audio Launch", "occurs_on": "2026-08-15"},
            ],
        },
    )
    assert retyped.status_code == 200, retyped.text
    assert [milestone["name"] for milestone in retyped.json()["milestones"]] == [
        "Audio Launch",
        "Bookings open",
        "Trailer",
    ]


async def test_milestone_missing_name_or_date_is_refused(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(milestones=[{"occurs_on": "2026-08-15"}]),
    )

    assert response.status_code == 422, response.text
    assert "detail" in response.json()


# ---------------------------------------------------------------------------
# Section 3 — Given: the release date is used as the pre-release / post-release
# boundary everywhere. Direct unit coverage of `phase_for`/`phase_for_date`, plus
# API-level boundary checks from both sides of the release date, including release day
# itself.
# ---------------------------------------------------------------------------


def test_phase_for_date_day_before_release_is_pre_release() -> None:
    assert phase_for_date(date(2026, 9, 10), date(2026, 9, 11)) == ReleasePhase.PRE_RELEASE


def test_phase_for_date_release_day_itself_is_post_release() -> None:
    """The release is the event, not the boundary before it — a milestone ON the
    release date must be post_release, not pre_release."""
    assert phase_for_date(date(2026, 9, 11), date(2026, 9, 11)) == ReleasePhase.POST_RELEASE


def test_phase_for_date_day_after_release_is_post_release() -> None:
    assert phase_for_date(date(2026, 9, 12), date(2026, 9, 11)) == ReleasePhase.POST_RELEASE


def test_phase_for_naive_datetime_is_read_as_utc() -> None:
    release_date = date(2026, 9, 11)
    just_before_midnight_utc = datetime(2026, 9, 10, 23, 59)
    just_after_midnight_utc = datetime(2026, 9, 11, 0, 0)

    assert just_before_midnight_utc.tzinfo is None
    assert phase_for(just_before_midnight_utc, release_date) == ReleasePhase.PRE_RELEASE
    assert phase_for(just_after_midnight_utc, release_date) == ReleasePhase.POST_RELEASE


def test_phase_for_aware_utc_datetime_matches_naive_equivalent() -> None:
    release_date = date(2026, 9, 11)
    aware_midnight_utc = datetime(2026, 9, 11, 0, 0, tzinfo=UTC)

    assert phase_for(aware_midnight_utc, release_date) == ReleasePhase.POST_RELEASE


def test_phase_for_aware_datetime_whose_utc_date_differs_from_local_date() -> None:
    """A post made in IST (UTC+5:30) late on release eve, local calendar date already
    the release day, but still the day before in UTC — must land pre-release. This is
    the exact scenario `phase_for`'s own docstring describes."""
    ist = timezone(timedelta(hours=5, minutes=30))
    release_date = date(2026, 9, 12)
    # Local (IST) time: 2026-09-12T02:00 -- looks like release day locally.
    late_ist = datetime(2026, 9, 12, 2, 0, tzinfo=ist)
    # In UTC this is 2026-09-11T20:30 -- still the day before release.
    assert late_ist.astimezone(UTC).date() == date(2026, 9, 11)

    assert phase_for(late_ist, release_date) == ReleasePhase.PRE_RELEASE


def test_phase_for_aware_datetime_whose_utc_date_is_later_than_local_date() -> None:
    """Symmetric case: a US-Pacific (UTC-8) morning post, local date still the day
    before release, but already release day in UTC -- must land post_release."""
    pacific = timezone(timedelta(hours=-8))
    release_date = date(2026, 9, 12)
    # Local (Pacific) time: 2026-09-11T20:00 -- looks like the day before release.
    early_pacific = datetime(2026, 9, 11, 20, 0, tzinfo=pacific)
    # In UTC this is 2026-09-12T04:00 -- already release day.
    assert early_pacific.astimezone(UTC).date() == date(2026, 9, 12)

    assert phase_for(early_pacific, release_date) == ReleasePhase.POST_RELEASE


async def test_milestone_on_release_day_is_post_release_via_api(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        release_date="2026-09-11",
        milestones=[{"name": "Release Day", "occurs_on": "2026-09-11"}],
    )

    assert body["milestones"][0]["phase"] == "post_release"


async def test_milestone_day_before_release_is_pre_release_via_api(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        release_date="2026-09-11",
        milestones=[{"name": "Trailer", "occurs_on": "2026-09-10"}],
    )

    assert body["milestones"][0]["phase"] == "pre_release"


async def test_milestone_day_after_release_is_post_release_via_api(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        release_date="2026-09-11",
        milestones=[{"name": "Post-release Interview", "occurs_on": "2026-09-12"}],
    )

    assert body["milestones"][0]["phase"] == "post_release"


# ---------------------------------------------------------------------------
# Section 4 — The central read-time-boundary claim: changing the release date via PUT
# .../schedule re-splits every milestone WITHOUT re-collecting -- the milestone rows
# (id, name, occurs_on) and the identity set (terms, collection_terms) are
# byte-identical before and after; only `phase` moves.
# ---------------------------------------------------------------------------


async def test_moving_release_date_flips_milestone_phase_with_row_otherwise_unchanged(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        name="Vaaranam Aayiram",
        release_date="2026-09-11",
        aliases=["VA"],
        hashtags=["#VaaranamAayiram"],
        lead_cast=["Suriya"],
        milestones=[{"name": "Trailer", "occurs_on": "2026-09-10"}],
    )
    title_id = body["id"]
    milestone_before = body["milestones"][0]
    assert milestone_before["phase"] == "pre_release"

    terms_before = body["terms"]
    collection_terms_before = body["collection_terms"]

    # Push the release date a week earlier -- the trailer, unchanged, now falls after
    # the (new, earlier) release date.
    updated = await _put_schedule(
        api_client,
        title_id,
        release_date="2026-09-01",
        milestones=[{"name": "Trailer", "occurs_on": "2026-09-10"}],
    )

    milestone_after = updated["milestones"][0]
    assert milestone_after["phase"] == "post_release"
    # The row itself is untouched: same id, same name, same date -- only the derived
    # phase moved.
    assert milestone_after["id"] == milestone_before["id"]
    assert milestone_after["name"] == milestone_before["name"]
    assert milestone_after["occurs_on"] == milestone_before["occurs_on"]

    # Nothing was re-collected: the identity set is byte-identical.
    assert updated["terms"] == terms_before
    assert updated["collection_terms"] == collection_terms_before


async def test_moving_release_date_the_other_way_flips_phase_back(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        release_date="2026-09-01",
        milestones=[{"name": "Trailer", "occurs_on": "2026-09-10"}],
    )
    assert body["milestones"][0]["phase"] == "post_release"

    updated = await _put_schedule(
        api_client,
        body["id"],
        release_date="2026-09-15",
        milestones=[{"name": "Trailer", "occurs_on": "2026-09-10"}],
    )

    assert updated["milestones"][0]["phase"] == "pre_release"
    assert updated["milestones"][0]["id"] == body["milestones"][0]["id"]


async def test_schedule_update_persists_the_new_release_date(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id, release_date="2026-09-11")

    await _put_schedule(api_client, body["id"], release_date="2027-02-02", milestones=[])

    title_row = await db_session.get(Title, uuid.UUID(body["id"]))
    assert title_row.release_date == date(2027, 2, 2)


# ---------------------------------------------------------------------------
# Section 5 — The schedule update never touches the identity set: it carries no term
# fields, and the terms table is untouched by it.
# ---------------------------------------------------------------------------


async def test_schedule_endpoint_payload_has_no_identity_fields(api_client: AsyncClient) -> None:
    """A studio pushing a corrected release date cannot accidentally also edit the
    identity set -- the schedule payload shape has no such fields to send."""
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id, aliases=["VA"], lead_cast=["Suriya"])

    response = await api_client.put(
        _schedule_url(body["id"]),
        json={
            "release_date": "2027-01-01",
            "milestones": [],
            # Extra identity-shaped keys, if the schema accepted them, would corrupt
            # the setup story's guarantee. Pydantic ignores unknown fields by default,
            # so this proves nothing changes even when a client tries.
            "aliases": ["Sneaky Alias"],
            "name": "Renamed",
        },
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["name"] == "Vaaranam Aayiram"
    term_values = {t["value"] for t in updated["terms"]}
    assert "Sneaky Alias" not in term_values
    assert term_values == {"VA", "Suriya"}


async def test_schedule_update_does_not_change_terms_row_count_in_db(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models import TitleTerm

    organization_id = await _create_organization(api_client)
    body = await _create_title(
        api_client, organization_id, aliases=["VA"], hashtags=["#VA"], lead_cast=["Suriya"]
    )

    await _put_schedule(
        api_client,
        body["id"],
        release_date="2026-12-25",
        milestones=[{"name": "Teaser", "occurs_on": "2026-10-01"}],
    )

    term_rows = (
        (
            await db_session.execute(
                select(TitleTerm).where(TitleTerm.title_id == uuid.UUID(body["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert len(term_rows) == 3


# ---------------------------------------------------------------------------
# Section 6 — Milestone list replacement: the PUT replaces rather than appends.
# Removing a milestone and saving deletes it; adding one does not disturb the others;
# ids are preserved for beats that did not change.
# ---------------------------------------------------------------------------


async def test_omitting_a_milestone_on_put_deletes_it(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(
        api_client,
        organization_id,
        milestones=[
            {"name": "Teaser", "occurs_on": "2026-07-01"},
            {"name": "Trailer", "occurs_on": "2026-08-15"},
        ],
    )
    assert len(body["milestones"]) == 2

    updated = await _put_schedule(
        api_client,
        body["id"],
        milestones=[{"name": "Teaser", "occurs_on": "2026-07-01"}],
    )

    assert [m["name"] for m in updated["milestones"]] == ["Teaser"]

    rows = (
        (
            await db_session.execute(
                select(TitleMilestone).where(TitleMilestone.title_id == uuid.UUID(body["id"]))
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].name == "Teaser"


async def test_adding_a_milestone_does_not_disturb_existing_ones(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(
        api_client,
        organization_id,
        milestones=[{"name": "Teaser", "occurs_on": "2026-07-01"}],
    )
    teaser_id = body["milestones"][0]["id"]

    updated = await _put_schedule(
        api_client,
        body["id"],
        milestones=[
            {"name": "Teaser", "occurs_on": "2026-07-01"},
            {"name": "Trailer", "occurs_on": "2026-08-15"},
        ],
    )

    assert len(updated["milestones"]) == 2
    teaser_after = next(m for m in updated["milestones"] if m["name"] == "Teaser")
    assert teaser_after["id"] == teaser_id


async def test_unchanged_milestone_id_is_preserved_across_an_edit(
    api_client: AsyncClient,
) -> None:
    """The implementation's own claim: diffing against stored rows (rather than
    replace-the-collection) keeps an unchanged beat's id stable. This matters once
    spike explanations point at a milestone id (E04-S05) -- editing the schedule must
    not renumber beats that were not touched."""
    organization_id = await _create_organization(api_client)
    body = await _create_title(
        api_client,
        organization_id,
        milestones=[
            {"name": "Teaser", "occurs_on": "2026-07-01"},
            {"name": "Trailer", "occurs_on": "2026-08-15"},
            {"name": "Audio Launch", "occurs_on": "2026-08-25"},
        ],
    )
    ids_before = {m["name"]: m["id"] for m in body["milestones"]}

    # Remove "Trailer", keep the other two exactly as they were, add a new one.
    updated = await _put_schedule(
        api_client,
        body["id"],
        milestones=[
            {"name": "Teaser", "occurs_on": "2026-07-01"},
            {"name": "Audio Launch", "occurs_on": "2026-08-25"},
            {"name": "Bookings Open", "occurs_on": "2026-09-05"},
        ],
    )

    ids_after = {m["name"]: m["id"] for m in updated["milestones"]}
    assert ids_after["Teaser"] == ids_before["Teaser"]
    assert ids_after["Audio Launch"] == ids_before["Audio Launch"]
    assert "Trailer" not in ids_after
    assert "Bookings Open" in ids_after
    assert ids_after["Bookings Open"] not in ids_before.values()


async def test_retyping_a_milestones_label_updates_the_display_name_in_place(
    api_client: AsyncClient,
) -> None:
    """Same beat (same normalised name + date), tidier capitalisation -- the label
    updates rather than the beat being treated as removed-then-added."""
    organization_id = await _create_organization(api_client)
    body = await _create_title(
        api_client,
        organization_id,
        milestones=[{"name": "audio  launch", "occurs_on": "2026-08-25"}],
    )
    original_id = body["milestones"][0]["id"]

    updated = await _put_schedule(
        api_client,
        body["id"],
        milestones=[{"name": "Audio Launch", "occurs_on": "2026-08-25"}],
    )

    assert len(updated["milestones"]) == 1
    assert updated["milestones"][0]["id"] == original_id
    assert updated["milestones"][0]["name"] == "Audio Launch"


async def test_put_with_empty_milestone_list_deletes_all_milestones(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(
        api_client,
        organization_id,
        milestones=[{"name": "Teaser", "occurs_on": "2026-07-01"}],
    )

    updated = await _put_schedule(api_client, body["id"], milestones=[])

    assert updated["milestones"] == []


# ---------------------------------------------------------------------------
# Section 7 — Dedupe: same name + same date submitted twice collapses to one
# milestone; same name on different dates survives as two; case/whitespace variants of
# the same name on the same date are the same beat.
# ---------------------------------------------------------------------------


async def test_same_name_and_date_submitted_twice_on_create_collapses_to_one(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        milestones=[
            {"name": "Trailer", "occurs_on": "2026-08-15"},
            {"name": "Trailer", "occurs_on": "2026-08-15"},
        ],
    )

    assert len(body["milestones"]) == 1


async def test_same_name_on_different_dates_survives_as_two_milestones(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        milestones=[
            {"name": "Trailer", "occurs_on": "2026-08-15"},
            {"name": "Trailer", "occurs_on": "2026-08-20"},
        ],
    )

    assert len(body["milestones"]) == 2
    dates = {m["occurs_on"] for m in body["milestones"]}
    assert dates == {"2026-08-15", "2026-08-20"}


async def test_case_and_whitespace_variant_names_on_same_date_are_the_same_beat(
    api_client: AsyncClient,
) -> None:
    """ "Audio launch" vs "  audio   LAUNCH " normalise to the same comparable form
    (NFKC, whitespace-collapsed, casefolded) -- on the same date, they are one beat,
    not two."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        milestones=[
            {"name": "Audio launch", "occurs_on": "2026-08-25"},
            {"name": "  audio   LAUNCH ", "occurs_on": "2026-08-25"},
        ],
    )

    assert len(body["milestones"]) == 1


async def test_dedupe_also_applies_on_the_schedule_put(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id, milestones=[])

    updated = await _put_schedule(
        api_client,
        body["id"],
        milestones=[
            {"name": "Bookings Open", "occurs_on": "2026-09-01"},
            {"name": "bookings  OPEN", "occurs_on": "2026-09-01"},
        ],
    )

    assert len(updated["milestones"]) == 1


# ---------------------------------------------------------------------------
# Section 8 — Invisible-character milestone names must be refused (422), not stored as
# a blank marker. Mirrors the E02-S01 anchor-term bypasses, one code path over.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invisible_name",
    ["​", "ㅤ", "⠀", "　", "​​", "ㅤ⠀　"],
    ids=[
        "zwsp_u200b",
        "hangul_filler_u3164",
        "braille_blank_u2800",
        "ideographic_space_u3000",
        "zwsp_run",
        "mixed_blanks",
    ],
)
async def test_invisible_only_milestone_name_is_refused_on_create(
    api_client: AsyncClient, invisible_name: str
) -> None:
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(milestones=[{"name": invisible_name, "occurs_on": "2026-08-15"}]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == EMPTY_MILESTONE_NAME_MESSAGE

    # Nothing was created at all -- the whole title save is one unit.
    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 0


@pytest.mark.parametrize(
    "invisible_name",
    ["​", "ㅤ", "⠀", "　"],
    ids=["zwsp_u200b", "hangul_filler_u3164", "braille_blank_u2800", "ideographic_space_u3000"],
)
async def test_invisible_only_milestone_name_is_refused_on_schedule_put(
    api_client: AsyncClient, invisible_name: str
) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id)

    response = await api_client.put(
        _schedule_url(body["id"]),
        json=_schedule_payload("2026-09-11", [{"name": invisible_name, "occurs_on": "2026-08-15"}]),
    )

    assert response.status_code == 422, response.text
    resp_body = response.json()
    assert resp_body["code"] == "ValidationFailedError"
    assert resp_body["message"] == EMPTY_MILESTONE_NAME_MESSAGE

    # The PUT failed entirely -- the title's schedule (still zero milestones) is
    # untouched, not partially applied.
    unchanged = await api_client.get(_title_url(body["id"]))
    assert unchanged.json()["milestones"] == []


async def test_milestone_name_with_invisible_edges_is_cleaned_and_kept(
    api_client: AsyncClient,
) -> None:
    """Mirrors the identity-term edge-cleaning behaviour: invisible characters only at
    the edges are cleaned away, not treated as making the whole name meaningless."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(
        api_client,
        organization_id,
        milestones=[{"name": "​Teaser​", "occurs_on": "2026-07-01"}],
    )

    assert len(body["milestones"]) == 1
    assert body["milestones"][0]["name"] == "Teaser"


# ---------------------------------------------------------------------------
# Section 9 — Bounds: MAX_MILESTONES_PER_TITLE, and a milestone name over the max
# length is refused as 422 (not 500).
# ---------------------------------------------------------------------------


async def test_more_than_max_milestones_per_title_is_rejected_on_create(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    base_date = date(2026, 1, 1)
    too_many_milestones = [
        {"name": f"Beat {i}", "occurs_on": (base_date + timedelta(days=i)).isoformat()}
        for i in range(MAX_MILESTONES_PER_TITLE + 1)
    ]
    assert len(too_many_milestones) == 51

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(milestones=too_many_milestones)
    )

    assert response.status_code == 422, response.text
    errors = response.json()["detail"]
    assert any(
        error["type"] == "too_long" and error["loc"][:2] == ["body", "milestones"]
        for error in errors
    )


async def test_more_than_max_milestones_per_title_is_rejected_on_schedule_put(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id)
    base_date = date(2026, 1, 1)
    too_many_milestones = [
        {"name": f"Beat {i}", "occurs_on": (base_date + timedelta(days=i)).isoformat()}
        for i in range(MAX_MILESTONES_PER_TITLE + 1)
    ]

    response = await api_client.put(
        _schedule_url(body["id"]),
        json=_schedule_payload("2026-09-11", too_many_milestones),
    )

    assert response.status_code == 422, response.text
    assert "detail" in response.json()


async def test_exactly_max_milestones_per_title_is_accepted(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    base_date = date(2026, 1, 1)
    max_milestones = [
        {"name": f"Beat {i}", "occurs_on": (base_date + timedelta(days=i)).isoformat()}
        for i in range(MAX_MILESTONES_PER_TITLE)
    ]
    assert len(max_milestones) == 50

    body = await _create_title(api_client, organization_id, milestones=max_milestones)

    assert len(body["milestones"]) == 50


async def test_milestone_name_over_max_length_is_rejected_as_422_not_500(
    api_client: AsyncClient,
) -> None:
    """E02-S01 shipped a 500 for an over-long identity term because `Field(max_length)`
    on a bare `list[str]` bounds the list, not the strings. A milestone name over
    `MILESTONE_NAME_MAX_LENGTH` (120) must be a 422 from Pydantic, not a 500 from an
    unbounded VARCHAR column."""
    organization_id = await _create_organization(api_client)
    overlong_name = "a" * (MILESTONE_NAME_MAX_LENGTH + 1)
    assert len(overlong_name) == 121

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(milestones=[{"name": overlong_name, "occurs_on": "2026-08-15"}]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert "detail" in body
    assert "code" not in body
    errors = body["detail"]
    assert any(
        error["type"] == "string_too_long" and error["loc"][:2] == ["body", "milestones"]
        for error in errors
    )


async def test_milestone_name_at_exactly_max_length_is_accepted(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    boundary_name = "a" * MILESTONE_NAME_MAX_LENGTH
    assert len(boundary_name) == 120

    body = await _create_title(
        api_client,
        organization_id,
        milestones=[{"name": boundary_name, "occurs_on": "2026-08-15"}],
    )

    assert body["milestones"][0]["name"] == boundary_name


# ---------------------------------------------------------------------------
# Section 10 — Access-control matrix on PUT .../schedule: unauthenticated -> 401,
# non-member -> 404 (never 403, so the title's existence is never leaked), viewer ->
# 403 (they can already see it, so 404 would be a lie), owner -> 200.
#
# NOTE on the fixture trap: `api_client` mutates `anonymous_api_client` in place and
# yields the SAME object, so a test must never request both `api_client` and
# `anonymous_api_client` expecting two distinct identities. Genuinely anonymous probes
# use `unauthenticated_client`, which is an independent client built fresh. Distinct
# *authenticated* identities use `other_api_client` (a second, independently
# constructed client), never a second use of `api_client`.
# ---------------------------------------------------------------------------


async def test_unauthenticated_cannot_put_schedule(
    api_client: AsyncClient, unauthenticated_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id)

    response = await unauthenticated_client.put(
        _schedule_url(body["id"]), json=_schedule_payload("2027-01-01", [])
    )

    assert response.status_code == 401
    assert response.json()["code"] == "AuthenticationRequiredError"


async def test_non_member_gets_404_not_403_on_put_schedule(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    """A caller who is not a member at all must not be able to tell this title exists
    -- 404, indistinguishable from a genuinely missing title, never 403."""
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id)

    response = await other_api_client.put(
        _schedule_url(body["id"]), json=_schedule_payload("2027-01-01", [])
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


async def test_non_member_put_schedule_response_matches_a_genuinely_missing_title(
    api_client: AsyncClient, other_api_client: AsyncClient
) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id)

    not_your_title_response = await other_api_client.put(
        _schedule_url(body["id"]), json=_schedule_payload("2027-01-01", [])
    )
    genuinely_missing_response = await other_api_client.put(
        _schedule_url("00000000-0000-0000-0000-000000000000"),
        json=_schedule_payload("2027-01-01", []),
    )

    assert not_your_title_response.status_code == genuinely_missing_response.status_code == 404
    assert not_your_title_response.json()["code"] == genuinely_missing_response.json()["code"]


async def test_viewer_gets_403_not_404_on_put_schedule(
    api_client: AsyncClient, other_api_client: AsyncClient, other_pilot_user: User
) -> None:
    """A viewer is a member and can already see this title (GET succeeds for them), so
    a 404 here would be a lie they can disprove -- they must get an honest 403."""
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id)
    await _make_viewer(api_client, other_api_client, organization_id, other_pilot_user.email)

    # Confirm the viewer really can see the title -- otherwise a 403 vs 404 distinction
    # here would be meaningless.
    read_response = await other_api_client.get(_title_url(body["id"]))
    assert read_response.status_code == 200

    response = await other_api_client.put(
        _schedule_url(body["id"]), json=_schedule_payload("2027-01-01", [])
    )

    assert response.status_code == 403
    resp_body = response.json()
    assert resp_body["code"] == "PermissionDeniedError"
    assert resp_body["message"] == NOT_AN_OWNER_SCHEDULE_MESSAGE


async def test_owner_can_put_schedule(api_client: AsyncClient) -> None:
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id)

    response = await api_client.put(
        _schedule_url(body["id"]),
        json=_schedule_payload("2027-03-03", [{"name": "Teaser", "occurs_on": "2027-01-01"}]),
    )

    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["release_date"] == "2027-03-03"
    assert len(updated["milestones"]) == 1


async def test_malformed_title_id_is_not_found_not_a_server_error(
    api_client: AsyncClient,
) -> None:
    response = await api_client.put(
        "/api/v1/titles/00000000-0000-0000-0000-000000000000/schedule",
        json=_schedule_payload("2027-01-01", []),
    )

    assert response.status_code == 404
    assert response.json()["code"] == "ResourceNotFoundError"


# ---------------------------------------------------------------------------
# Section 11 — Regression: NFKC normalisation expands length, and `max_length` must be
# checked on the NORMALISED value, not the raw client string. `TitleService._ensure_fits`
# now guards all four write surfaces (title name, identity terms, milestone names on
# create, milestone names on the schedule PUT). Before the fix, a raw string that passed
# Pydantic's `max_length` could expand past the limit on normalisation, get written, and
# only fail on the way back out (the read schema re-checking the same limit) — a 500,
# not a 422, and the row had already committed on SQLite, so the title became
# permanently unreadable.
# ---------------------------------------------------------------------------


def test_confirmed_nfkc_expanding_characters() -> None:
    """Pins the premise the rest of this section relies on: these specific characters
    genuinely expand under NFKC, and by how much. Checked directly against
    `unicodedata.normalize`, not assumed — a test built on an unverified assumption
    about Unicode expansion would be worthless."""
    import unicodedata

    expansions = {
        "ﬁ": ("fi", 1, 2),  # LATIN SMALL LIGATURE FI
        "ﬄ": ("ffl", 1, 3),  # LATIN SMALL LIGATURE FFL
        "㍿": ("株式会社", 1, 4),  # SQUARE CORPORATION
        "…": ("...", 1, 3),  # HORIZONTAL ELLIPSIS
    }
    for raw_char, (expected_expansion, raw_len, expanded_len) in expansions.items():
        normalized = unicodedata.normalize("NFKC", raw_char)
        assert normalized == expected_expansion
        assert len(raw_char) == raw_len
        assert len(normalized) == expanded_len
        assert expanded_len > raw_len  # the whole point: it GROWS


async def test_title_name_exceeds_limit_only_after_nfkc_expansion_is_rejected(
    api_client: AsyncClient,
) -> None:
    """151 copies of the "fi" ligature (U+FB01) are 151 raw characters -- comfortably
    under `TITLE_NAME_MAX_LENGTH` (300), so Pydantic's `max_length` on the raw string
    lets it through. NFKC-normalised, each ligature becomes two ASCII characters, so the
    stored name is 302 characters -- past the limit. Before the fix this reached the
    database; now `_ensure_fits` must catch it before anything is written."""
    organization_id = await _create_organization(api_client)
    raw_name = "ﬁ" * 151
    assert len(raw_name) == 151
    assert len(raw_name) <= TITLE_NAME_MAX_LENGTH

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=raw_name)
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == TOO_LONG_MESSAGE.format(
        subject="This title name", limit=TITLE_NAME_MAX_LENGTH
    )


@pytest.mark.parametrize(
    "field_name", ["aliases", "hashtags", "lead_cast", "directors", "music_directors"]
)
async def test_identity_term_exceeds_limit_only_after_nfkc_expansion_is_rejected(
    api_client: AsyncClient, field_name: str
) -> None:
    """Same trap, every identity-term field: the reviewer only found this in
    milestones, but title `name` and every term field take the identical
    NFKC-then-store path through `TitleService._ensure_fits`."""
    organization_id = await _create_organization(api_client)
    raw_term = "ﬁ" * 151
    assert len(raw_term) <= TITLE_TERM_MAX_LENGTH

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="Ninety Six", **{field_name: [raw_term]}),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == TOO_LONG_MESSAGE.format(
        subject="An identity term", limit=TITLE_TERM_MAX_LENGTH
    )


async def test_milestone_name_exceeds_limit_only_after_nfkc_expansion_is_rejected_on_create(
    api_client: AsyncClient,
) -> None:
    """65 ligatures are 65 raw characters -- under `MILESTONE_NAME_MAX_LENGTH` (120) --
    but 130 once NFKC-expanded, past the limit."""
    organization_id = await _create_organization(api_client)
    raw_milestone_name = "ﬁ" * 65
    assert len(raw_milestone_name) <= MILESTONE_NAME_MAX_LENGTH

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(milestones=[{"name": raw_milestone_name, "occurs_on": "2026-08-15"}]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == TOO_LONG_MESSAGE.format(
        subject="A milestone name", limit=MILESTONE_NAME_MAX_LENGTH
    )


async def test_milestone_name_exceeds_limit_only_after_nfkc_expansion_is_rejected_on_schedule_put(
    api_client: AsyncClient,
) -> None:
    """The same milestone-name NFKC trap, exercised through `PUT .../schedule` rather
    than create -- both paths go through `_desired_milestones`/`_ensure_fits`, and both
    must be guarded, since a studio edits milestones after setup at least as often as at
    setup time."""
    organization_id = await _create_organization(api_client)
    body = await _create_title(api_client, organization_id)
    raw_milestone_name = "ﬁ" * 65
    assert len(raw_milestone_name) <= MILESTONE_NAME_MAX_LENGTH

    response = await api_client.put(
        _schedule_url(body["id"]),
        json=_schedule_payload(
            "2026-09-11", [{"name": raw_milestone_name, "occurs_on": "2026-08-15"}]
        ),
    )

    assert response.status_code == 422, response.text
    resp_body = response.json()
    assert resp_body["code"] == "ValidationFailedError"
    assert resp_body["message"] == TOO_LONG_MESSAGE.format(
        subject="A milestone name", limit=MILESTONE_NAME_MAX_LENGTH
    )


@pytest.mark.parametrize(
    "expanding_character,repeat_count",
    [
        ("ﬄ", 41),  # "ffl" ligature, 1 -> 3: 41 raw, 123 expanded
        ("…", 41),  # horizontal ellipsis, 1 -> 3: 41 raw, 123 expanded
        ("㍿", 31),  # SQUARE CORPORATION, 1 -> 4: 31 raw, 124 expanded
    ],
    ids=["ffl_ligature", "horizontal_ellipsis", "square_corporation"],
)
async def test_other_nfkc_expanding_characters_also_trigger_the_milestone_length_guard(
    api_client: AsyncClient, expanding_character: str, repeat_count: int
) -> None:
    """The fix is not special-cased to the "fi" ligature from the reviewer's example --
    any NFKC-expanding character must be caught the same way, on the normalised
    length."""
    organization_id = await _create_organization(api_client)
    raw_milestone_name = expanding_character * repeat_count
    assert len(raw_milestone_name) <= MILESTONE_NAME_MAX_LENGTH

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(milestones=[{"name": raw_milestone_name, "occurs_on": "2026-08-15"}]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == TOO_LONG_MESSAGE.format(
        subject="A milestone name", limit=MILESTONE_NAME_MAX_LENGTH
    )


async def test_legitimate_ligature_name_is_accepted_and_normalised_not_rejected(
    api_client: AsyncClient,
) -> None:
    """The fix must not turn NFKC normalisation itself into a rejection: a short,
    ordinary name that happens to contain a ligature is nowhere near the length limit
    either way, and must be accepted, with the ligature normalised to its expanded
    ASCII form -- exactly as every other identity term and name is normalised
    elsewhere in this suite."""
    organization_id = await _create_organization(api_client)

    body = await _create_title(api_client, organization_id, name="ﬁlm noir")

    assert body["name"] == "film noir"


async def test_rejected_create_due_to_oversized_title_name_leaves_existing_title_readable(
    api_client: AsyncClient,
) -> None:
    """The property that was actually broken: before the fix, an oversized value could
    reach the database and commit, and the title it belonged to became permanently
    unreadable (every later GET 500'd, because the read schema re-checked the same
    limit against the now-persisted, over-length value). With the fix, the oversized
    request must never reach the database at all -- proven here by showing an
    unrelated, already-existing title is completely unaffected by the rejected
    request, and that no phantom row was created."""
    organization_id = await _create_organization(api_client)
    existing_title = await _create_title(api_client, organization_id, name="Vaaranam Aayiram")

    oversized_response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name="ﬁ" * 151)
    )
    assert oversized_response.status_code == 422, oversized_response.text

    read_response = await api_client.get(_title_url(existing_title["id"]))
    assert read_response.status_code == 200
    assert read_response.json()["id"] == existing_title["id"]

    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 1


async def test_rejected_create_due_to_oversized_identity_term_leaves_existing_title_readable(
    api_client: AsyncClient,
) -> None:
    organization_id = await _create_organization(api_client)
    existing_title = await _create_title(api_client, organization_id, name="Vaaranam Aayiram")

    oversized_response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="Ninety Six", aliases=["ﬁ" * 151]),
    )
    assert oversized_response.status_code == 422, oversized_response.text

    read_response = await api_client.get(_title_url(existing_title["id"]))
    assert read_response.status_code == 200
    assert read_response.json()["id"] == existing_title["id"]

    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 1


async def test_rejected_create_due_to_oversized_milestone_name_leaves_existing_title_readable(
    api_client: AsyncClient,
) -> None:
    """This is the reviewer's own example: the bug was found in milestones
    specifically -- a title whose milestone name was oversized became permanently
    unreadable. Proven here from the other side, since the reproducing title no longer
    exists to read after the fix: an unrelated title stays perfectly readable across
    the rejected request."""
    organization_id = await _create_organization(api_client)
    existing_title = await _create_title(
        api_client,
        organization_id,
        name="Vaaranam Aayiram",
        milestones=[{"name": "Teaser", "occurs_on": "2026-07-01"}],
    )

    oversized_response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(
            name="Ninety Six",
            milestones=[{"name": "ﬁ" * 65, "occurs_on": "2026-08-15"}],
        ),
    )
    assert oversized_response.status_code == 422, oversized_response.text

    read_response = await api_client.get(_title_url(existing_title["id"]))
    assert read_response.status_code == 200
    assert read_response.json()["milestones"][0]["name"] == "Teaser"

    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 1


# ---------------------------------------------------------------------------
# Section 12 — Regression: the release_date backfill in the E02-S02 migration must
# resolve the backfilled date in UTC, not the session's timezone. This is Postgres-only
# DDL (`AT TIME ZONE`, `::date`) and this suite runs on SQLite -- nothing here executes
# the migration (per the hard rule against running Alembic against any database). This
# is a static assertion on the migration file's own source text: the most this suite can
# honestly claim about DDL it cannot run.
# ---------------------------------------------------------------------------


def test_migration_backfills_release_date_pinned_to_utc_not_session_timezone() -> None:
    """`CAST(created_at AS DATE)` resolves in whatever timezone the connection happens
    to be configured with, so the same row could backfill to different calendar days
    depending on session state -- silently wrong data, not an error. The fix pins the
    cast to UTC explicitly. Guards the migration's source text against a regression
    back to the plain, timezone-dependent cast."""
    migration_path = (
        Path(__file__).resolve().parent.parent
        / "alembic"
        / "versions"
        / "5f1c8d3b6e29_add_title_release_date_and_milestones.py"
    )
    assert migration_path.is_file(), f"migration file not found at {migration_path}"
    migration_source = migration_path.read_text()

    # Isolate the actual executed SQL (the `op.execute("...")` call), not the file's
    # prose -- the surrounding comment legitimately *names* the old, buggy expression
    # while explaining why it was replaced, so a whole-file substring check for that
    # expression would false-positive on the comment itself. Only the executed
    # statement is what actually runs against the database.
    execute_call_start = migration_source.index("op.execute(")
    execute_call_end = migration_source.index(")\n", execute_call_start)
    executed_sql = migration_source[execute_call_start:execute_call_end]

    assert "AT TIME ZONE 'UTC'" in executed_sql
    assert "(created_at AT TIME ZONE 'UTC')::date" in executed_sql
    # The old, timezone-dependent form must not have crept back into the SQL that
    # actually runs -- it is fine for the comment above to keep naming it as the
    # rejected alternative.
    assert "CAST(created_at AS DATE)" not in executed_sql
    # The backfill must still be guarded to existing NULLs only, not every row on
    # every future run of this migration.
    assert "WHERE release_date IS NULL" in executed_sql


# ---------------------------------------------------------------------------
# Section 13 — Characterisation of a KNOWN, OPEN defect (E02-S06), deliberately not
# fixed here. Variation selectors (U+FE00-FE0F, Unicode category `Mn`) are not in
# `_INVISIBLE_CATEGORIES` (Cc/Cf/Zl/Zp/Zs) and are not in the explicit
# `_BLANK_RENDERING_CHARACTERS` set, so `has_meaningful_content` currently treats a
# milestone name made of nothing but a variation selector as real content. This test
# documents the CURRENT (buggy) behaviour -- it is not a claim that a blank-rendering
# marker on a chart is correct, and it must never be changed to assert the fixed (422)
# behaviour without the underlying fix landing first, or it will fail.
# ---------------------------------------------------------------------------


async def test_known_defect_variation_selector_milestone_name_is_still_accepted(
    api_client: AsyncClient,
) -> None:
    """KNOWN OPEN DEFECT, tracked by E02-S06 (scope widened to the milestone-name
    surface): a milestone named with only U+FE0F (VARIATION SELECTOR-16) is currently
    accepted and stored, and would render as a blank marker with no visible label. This
    pins today's actual behaviour so a future, unrelated refactor does not silently
    change it in either direction without someone noticing -- it is a characterisation
    test, not an approval of the outcome. When E02-S06 lands a fix for this surface,
    this test should be rewritten to assert 422, not deleted silently."""
    organization_id = await _create_organization(api_client)
    variation_selector_only_name = "️"

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(
            milestones=[{"name": variation_selector_only_name, "occurs_on": "2026-08-15"}]
        ),
    )

    # This is the bug: today, this is 201, not 422.
    assert response.status_code == 201, response.text
    stored_name = response.json()["milestones"][0]["name"]
    assert stored_name == variation_selector_only_name
    # The stored name renders as nothing -- there is no visible character in it at all.
    import unicodedata

    assert unicodedata.category(stored_name) == "Mn"
