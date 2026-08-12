"""Tests for E02-S04 — Approve hashtags the audience invented, so tracking follows the
conversation as it mutates.

Story: stories/E02-title-setup-identity-discovery/E02-S04-approve-discovered-alias-suggestions.md

The story has ONE Gherkin scenario ("Owner reviews organically-emerged hashtags after a
review wave"). It has several Given clauses and a compound Then, and it maps to exactly
ONE test — `test_owner_reviews_organically_emerged_hashtags_after_a_review_wave` — which
walks every clause in order, each one commented where it is exercised:

  - Given: my title has been collecting for at least one polling cycle -> a title is
    created and a corpus of mentions is written directly to the database, standing in
    for what a poll run leaves behind (mirroring the pattern other collection-adjacent
    suites use for corpora that don't need a live provider).
  - and Given: the corpus contains hashtags and name spellings not in my declared
    identity set -> the corpus carries an organic hashtag (#DCFDFS) and the story's own
    worked misspelling of a declared director's surname ("Kankaraj" for "Kanagaraj"),
    alongside a mention that only repeats an already-declared hashtag.
  - and Given: the "Alias suggestions" list shows each candidate with its mention count,
    a sample post, and Approve/Reject actions -> asserted directly on the
    `GET .../alias-suggestions` response shape, and exercised functionally by actually
    calling the approve and reject actions later in the same test.
  - and Given: rejected candidates are remembered and never re-suggested -> the
    misspelling is rejected, then the list is re-read and the rejection sticks and is
    reported back.
  - When: I approve a suggested hashtag -> `#DCFDFS` is approved.
  - Then: it joins the title's identity set, is used by the next collection run, and
    previously collected posts carrying it are re-matched to the title without paying to
    re-collect them -> asserted three ways: the title's `terms`/`collection_terms` (what
    the next collection cycle's query plan is built from) carry the new term; the stored
    mentions that already carried `#DCFDFS` gained `MentionQueryMatch` rows; and the
    approval response's `collection_calls` is 0.

BUDGET: the scenario test above, plus five more, chosen from this codebase's own defect
history and the story's own stated risk areas:

  - Section A: a hashtag in Tamil script is mined whole, not truncated at a vowel sign —
    the exact class of bug (`\\w`/code-point counting) that has broken this corpus's
    word-boundary handling four times before (see `app/core/post_matching.py`'s own
    docstring).
  - Section B: a misspelling of a declared Devanagari name is offered as a name-variant
    candidate with the right `resembles` — the same defect class, on the edit-distance
    path rather than the hashtag path.
  - Section C: an approval value that clears the request schema's raw `max_length` but
    expands past the `TITLE_TERM_MAX_LENGTH` column bound under NFKC must be refused as
    a 422, not allowed to reach SQLite (which does not enforce VARCHAR limits) and blow
    up as a 500 on Postgres.
  - Section D: two candidates tied on mention count are ordered by their folded value,
    and that order is identical across two independent reads of an unchanged corpus.
  - Section E: retroactive re-matching must find an approved term in a mention's
    `hashtags` column even when the term never appears in the post's own text (some
    providers strip hashtags out of the body) — and the resulting rows are recorded as
    `MatchSource.RETROACTIVE`, never `COLLECTION`.

Frontend: `callsheet-ui` has no test runner configured (no `vitest`/`jest`/test script in
package.json) — no frontend tests are included, per the run brief.
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.platforms import Platform
from app.models.mention import Mention
from app.models.mention_query_match import MatchSource, MentionQueryMatch
from app.models.title import TITLE_TERM_MAX_LENGTH
from app.models.title_alias_rejection import TitleAliasRejection
from app.services.identity_rules import TOO_LONG_MESSAGE

ORGANIZATIONS_URL = "/api/v1/organizations"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _titles_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/titles"


def _alias_suggestions_url(title_id: str) -> str:
    return f"/api/v1/titles/{title_id}/alias-suggestions"


def _alias_approvals_url(title_id: str) -> str:
    return f"{_alias_suggestions_url(title_id)}/approvals"


def _alias_rejections_url(title_id: str) -> str:
    return f"{_alias_suggestions_url(title_id)}/rejections"


async def _create_organization(client: AsyncClient, payload: dict = SUN_PICTURES_PAYLOAD) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _title_create_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Vaaranam",
        "release_date": "2026-09-11",
        "aliases": [],
        "hashtags": [],
        "lead_cast": [],
        "directors": [],
        "music_directors": [],
        "exclusions": [],
    }
    payload.update(overrides)
    return payload


async def _create_title(client: AsyncClient, organization_id: str, **overrides: object) -> dict:
    response = await client.post(
        _titles_url(organization_id), json=_title_create_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


_POST_COUNTER = 0


async def _add_mention(
    session: AsyncSession,
    title_id: uuid.UUID | str,
    *,
    text: str,
    hashtags: list[str] | None = None,
    author_handle: str | None = None,
    author_display_name: str = "Fan",
    posted_at: datetime | None = None,
    permalink: str | None = "https://x.com/fan/status/1",
    platform_reported_language: str | None = "en",
) -> Mention:
    """One stored mention, standing in for what a poll run already collected.

    Every call gets a fresh `external_id` and, unless a test cares, a distinct
    `posted_at`/`collected_at` a second apart so ordering never ties by accident.
    """
    global _POST_COUNTER
    _POST_COUNTER += 1
    index = _POST_COUNTER
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC) + timedelta(seconds=index)
    mention = Mention(
        title_id=uuid.UUID(str(title_id)),
        platform=Platform.X,
        external_id=f"post-{index:06d}",
        author_handle=author_handle or f"@fan{index}",
        author_display_name=author_display_name,
        text=text,
        hashtags=list(hashtags or []),
        posted_at=posted_at or now,
        permalink=permalink,
        platform_reported_language=platform_reported_language,
        collected_at=now,
    )
    session.add(mention)
    await session.flush()
    return mention


async def _list_suggestions(client: AsyncClient, title_id: str) -> dict:
    response = await client.get(_alias_suggestions_url(title_id))
    assert response.status_code == 200, response.text
    return response.json()


def _candidate(suggestions: dict, value: str) -> dict | None:
    return next((c for c in suggestions["candidates"] if c["value"] == value), None)


async def _approve(client: AsyncClient, title_id: str, value: str, term_type: str) -> dict:
    response = await client.post(
        _alias_approvals_url(title_id), json={"value": value, "term_type": term_type}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _reject(client: AsyncClient, title_id: str, value: str, kind: str) -> dict:
    response = await client.post(
        _alias_rejections_url(title_id), json={"value": value, "kind": kind}
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# The scenario: "Owner reviews organically-emerged hashtags after a review wave"
# ---------------------------------------------------------------------------


async def test_owner_reviews_organically_emerged_hashtags_after_a_review_wave(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    title = await _create_title(
        api_client,
        organization_id,
        name="Vaaranam",
        hashtags=["#Vaaranam"],
        directors=["Lokesh Kanagaraj"],
    )
    title_id = title["id"]

    # --- Given: the title has been collecting for at least one polling cycle, and the
    # corpus contains hashtags and name spellings not in the declared identity set. ---
    dcfdfs_mentions = [
        await _add_mention(
            db_session, title_id, text=f"FDFS mass!! #DCFDFS review incoming ({i})",
            hashtags=["DCFDFS"],
        )
        for i in range(3)
    ]
    misspelling_mentions = [
        await _add_mention(
            db_session, title_id, text="Kankaraj sir never disappoints, what a director",
        )
        for _ in range(2)
    ]
    already_declared = await _add_mention(
        db_session, title_id, text="So hyped for #Vaaranam this Friday",
        hashtags=["Vaaranam"],
    )
    corpus_size = len(dcfdfs_mentions) + len(misspelling_mentions) + 1

    # --- and Given: the Alias suggestions list shows each candidate with its mention
    # count, a sample post, and Approve/Reject actions. ---
    suggestions = await _list_suggestions(api_client, title_id)
    assert suggestions["scanned_mentions"] == corpus_size
    assert suggestions["corpus_size"] == corpus_size
    assert suggestions["rejections"] == []

    hashtag_candidate = _candidate(suggestions, "#DCFDFS")
    assert hashtag_candidate is not None
    assert hashtag_candidate["kind"] == "hashtag"
    assert hashtag_candidate["mention_count"] == 3
    assert hashtag_candidate["resembles"] is None
    sample = hashtag_candidate["sample"]
    assert sample is not None
    assert sample["id"] in {str(mention.id) for mention in dcfdfs_mentions}
    assert "#DCFDFS" in sample["text"]

    variant_candidate = _candidate(suggestions, "Kankaraj")
    assert variant_candidate is not None
    assert variant_candidate["kind"] == "name_variant"
    assert variant_candidate["mention_count"] == 2
    assert variant_candidate["resembles"] == "Lokesh Kanagaraj"

    # The already-declared hashtag is never offered back as a discovery.
    assert _candidate(suggestions, "#Vaaranam") is None

    # --- and Given: rejected candidates are remembered and never re-suggested. ---
    rejection = await _reject(api_client, title_id, "Kankaraj", "name_variant")
    assert rejection["value"] == "Kankaraj"

    suggestions_after_rejection = await _list_suggestions(api_client, title_id)
    assert _candidate(suggestions_after_rejection, "Kankaraj") is None
    assert len(suggestions_after_rejection["rejections"]) == 1
    assert suggestions_after_rejection["rejections"][0]["value"] == "Kankaraj"
    # The unrelated hashtag candidate is unaffected by the rejection.
    assert _candidate(suggestions_after_rejection, "#DCFDFS") is not None

    stored_rejection = (
        await db_session.execute(
            select(TitleAliasRejection).where(TitleAliasRejection.title_id == uuid.UUID(title_id))
        )
    ).scalar_one()
    assert stored_rejection.value == "Kankaraj"

    # --- When: I approve a suggested hashtag. ---
    approval = await _approve(api_client, title_id, "#DCFDFS", "hashtag")

    # --- Then: it joins the title's identity set... ---
    assert approval["term"]["value"] == "#DCFDFS"
    assert approval["term"]["term_type"] == "hashtag"

    read_back = await api_client.get(f"/api/v1/titles/{title_id}")
    assert read_back.status_code == 200, read_back.text
    title_after = read_back.json()
    hashtag_terms = [term for term in title_after["terms"] if term["term_type"] == "hashtag"]
    assert any(term["value"] == "#DCFDFS" for term in hashtag_terms)

    # ...is used by the next collection run (the query plan is built straight from the
    # identity set, so this is what "used by the next collection run" means at rest)...
    assert "dcfdfs" in title_after["collection_terms"]

    # ...and previously collected posts carrying it are re-matched to the title without
    # paying to re-collect them.
    assert approval["rematched_mentions"] == 3
    assert approval["scanned_mentions"] == corpus_size
    assert approval["collection_calls"] == 0

    matches = (
        (
            await db_session.execute(
                select(MentionQueryMatch).where(
                    MentionQueryMatch.title_id == uuid.UUID(title_id),
                    MentionQueryMatch.query_variant == "hashtag:dcfdfs",
                )
            )
        )
        .scalars()
        .all()
    )
    assert {match.mention_id for match in matches} == {mention.id for mention in dcfdfs_mentions}
    assert all(match.match_source == MatchSource.RETROACTIVE for match in matches)
    # The already-declared-hashtag mention never carried #DCFDFS and must not be matched.
    assert already_declared.id not in {match.mention_id for match in matches}

    # The approved hashtag is now part of the identity set and is never re-suggested.
    suggestions_after_approval = await _list_suggestions(api_client, title_id)
    assert _candidate(suggestions_after_approval, "#DCFDFS") is None


# ---------------------------------------------------------------------------
# Section A — Tamil hashtag mining. `\w`/code-point word-boundary bugs have broken this
# corpus's hashtag extraction four times before; the miner reuses `iter_hashtags`, which
# must yield the whole tag rather than truncating at a vowel sign.
# ---------------------------------------------------------------------------


async def test_tamil_script_hashtag_is_mined_whole_not_truncated_at_a_vowel_sign(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    title = await _create_title(
        api_client, organization_id, name="Vaaranam", hashtags=["#Vaaranam"], lead_cast=["Suriya"]
    )
    title_id = title["id"]

    await _add_mention(
        db_session, title_id, text="இது ஒரு அற்புதமான படம் #தமிழ்சினிமா பாருங்கள்"
    )

    suggestions = await _list_suggestions(api_client, title_id)

    candidate = _candidate(suggestions, "#தமிழ்சினிமா")
    assert candidate is not None
    assert candidate["kind"] == "hashtag"
    assert candidate["mention_count"] == 1


# ---------------------------------------------------------------------------
# Section B — Devanagari name-variant mining. The same word-boundary/edit-distance
# machinery on a marked script other than Tamil, using a real misspelling one edit away
# from a declared director's name (dropping the final vowel sign).
# ---------------------------------------------------------------------------


async def test_devanagari_misspelling_of_a_declared_director_is_offered_as_a_name_variant(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    declared_name = "राजामौली"  # Rajamouli
    misspelling = "राजामौल"  # missing the final vowel sign — one edit away
    title = await _create_title(
        api_client,
        organization_id,
        name="RRR",
        lead_cast=["Ram Charan"],
        directors=[declared_name],
    )
    title_id = title["id"]

    await _add_mention(
        db_session, title_id, text=f"अगली फिल्म {misspelling} की इंतजार है सबको"
    )

    suggestions = await _list_suggestions(api_client, title_id)

    candidate = _candidate(suggestions, misspelling)
    assert candidate is not None
    assert candidate["kind"] == "name_variant"
    assert candidate["resembles"] == declared_name


# ---------------------------------------------------------------------------
# Section C — NFKC expansion past the 300-char column bound, on the approval path this
# time (the preview path already has coverage for the same trap in
# test_preview_sample_results_before_saving.py). SQLite does not enforce VARCHAR limits,
# so only an explicit length assertion here catches a value that would 500 on Postgres.
# ---------------------------------------------------------------------------


async def test_nfkc_expanded_approval_value_is_refused_not_allowed_to_overflow_the_column(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    """250 copies of the ligature 'ﬁ' clear the request schema's raw `max_length=300`
    (250 <= 300), but NFKC normalisation expands each into 'fi', giving 500 characters —
    well past `TITLE_TERM_MAX_LENGTH`. The service's own `ensure_fits` call must catch
    this and refuse it as a 422, not let it reach the `String(300)` column."""
    ligature_value = "ﬁ" * 250
    assert len(ligature_value) == 250
    organization_id = await _create_organization(api_client)
    title = await _create_title(
        api_client, organization_id, name="Vaaranam", hashtags=["#Vaaranam"]
    )
    title_id = title["id"]

    response = await api_client.post(
        _alias_approvals_url(title_id), json={"value": ligature_value, "term_type": "alias"}
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == TOO_LONG_MESSAGE.format(
        subject="An identity term", limit=TITLE_TERM_MAX_LENGTH
    )

    title_after = await api_client.get(f"/api/v1/titles/{title_id}")
    alias_terms = [term for term in title_after.json()["terms"] if term["term_type"] == "alias"]
    assert alias_terms == []


# ---------------------------------------------------------------------------
# Section D — Ranking ties and a total order across two reads. The story's own note:
# "the suggestion list will be busy early in a campaign and must rank by volume, not
# recency." Ties on volume are broken by the folded value, so the order can never
# reshuffle between two reads of an unchanged corpus.
# ---------------------------------------------------------------------------


async def test_tied_candidates_are_ordered_by_folded_value_and_stay_stable_across_two_reads(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    title = await _create_title(
        api_client, organization_id, name="Vaaranam", hashtags=["#Vaaranam"]
    )
    title_id = title["id"]

    # Two ties on volume (#Alpha, #Bravo — one mention each) and one clear volume winner
    # (#Zulu — two mentions), so the winner must rank first regardless of alphabetical
    # order, and the tied pair must be ordered alphabetically on the folded value.
    await _add_mention(db_session, title_id, text="check out #Bravo now")
    await _add_mention(db_session, title_id, text="check out #Alpha now")
    await _add_mention(db_session, title_id, text="check out #Zulu now")
    await _add_mention(db_session, title_id, text="check out #Zulu again")

    first_read = await _list_suggestions(api_client, title_id)
    second_read = await _list_suggestions(api_client, title_id)

    ordered_values = [candidate["value"] for candidate in first_read["candidates"]]
    assert ordered_values == ["#Zulu", "#Alpha", "#Bravo"]
    assert [c["value"] for c in second_read["candidates"]] == ordered_values


# ---------------------------------------------------------------------------
# Section E — Retroactive re-matching must check a mention's `hashtags` column, not just
# its body text (some providers strip tags out of the text entirely — the same reason
# `MinedPost`/`_iter_post_hashtags` reads both sources when mining suggestions). The
# resulting rows must be `MatchSource.RETROACTIVE`, never `COLLECTION` — no query ran.
# ---------------------------------------------------------------------------


async def test_retroactive_rematch_finds_the_term_in_the_hashtags_column_even_when_absent_from_text(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    title = await _create_title(
        api_client, organization_id, name="Vaaranam", hashtags=["#Vaaranam"]
    )
    title_id = title["id"]

    # The word "DCFDFS" never appears in the text at all — only in the hashtags column,
    # exactly as a provider that strips tags from the body would leave it.
    hashtag_only_mention = await _add_mention(
        db_session, title_id, text="best FDFS of the year, no words", hashtags=["DCFDFS"]
    )
    # A control mention that carries neither the word nor the tag, to prove the match is
    # not simply "every mention gets matched".
    unrelated_mention = await _add_mention(
        db_session, title_id, text="totally unrelated content about something else"
    )

    approval = await _approve(api_client, title_id, "#DCFDFS", "hashtag")

    assert approval["rematched_mentions"] == 1
    assert approval["collection_calls"] == 0

    matches = (
        (
            await db_session.execute(
                select(MentionQueryMatch).where(
                    MentionQueryMatch.title_id == uuid.UUID(title_id),
                    MentionQueryMatch.query_variant == "hashtag:dcfdfs",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(matches) == 1
    assert matches[0].mention_id == hashtag_only_mention.id
    assert matches[0].match_source == MatchSource.RETROACTIVE
    assert unrelated_mention.id not in {match.mention_id for match in matches}


# ---------------------------------------------------------------------------
# Section F — `DELETE /titles/{id}/alias-suggestions/rejections/{id}`
# (`AliasDiscoveryService.restore_rejected`). Reviewer round-2 finding 2: this endpoint
# had zero test coverage. Two cases: the happy path (a restored term is offered again),
# and the access-scoping guard that keeps one title's owner from deleting a rejection
# that belongs to a different title.
# ---------------------------------------------------------------------------


def _rejection_restore_url(title_id: str, rejection_id: str) -> str:
    return f"{_alias_rejections_url(title_id)}/{rejection_id}"


async def test_restoring_a_rejected_term_makes_it_suggestable_again(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    title = await _create_title(
        api_client, organization_id, name="Vaaranam", hashtags=["#Vaaranam"]
    )
    title_id = title["id"]

    await _add_mention(
        db_session, title_id, text="loving #DCFDFS energy today", hashtags=["DCFDFS"]
    )

    rejection = await _reject(api_client, title_id, "#DCFDFS", "hashtag")
    suggestions_after_rejection = await _list_suggestions(api_client, title_id)
    assert _candidate(suggestions_after_rejection, "#DCFDFS") is None
    assert len(suggestions_after_rejection["rejections"]) == 1

    restore_response = await api_client.delete(
        _rejection_restore_url(title_id, rejection["id"])
    )
    assert restore_response.status_code == 204, restore_response.text
    assert restore_response.content == b""

    suggestions_after_restore = await _list_suggestions(api_client, title_id)
    assert suggestions_after_restore["rejections"] == []
    restored_candidate = _candidate(suggestions_after_restore, "#DCFDFS")
    assert restored_candidate is not None
    assert restored_candidate["kind"] == "hashtag"

    stored_rejections = (
        (
            await db_session.execute(
                select(TitleAliasRejection).where(
                    TitleAliasRejection.title_id == uuid.UUID(title_id)
                )
            )
        )
        .scalars()
        .all()
    )
    assert stored_rejections == []


async def test_restoring_a_rejection_belonging_to_a_different_title_is_refused_with_404(
    api_client: AsyncClient, db_session: AsyncSession
) -> None:
    organization_id = await _create_organization(api_client)
    title_a = await _create_title(
        api_client, organization_id, name="Vaaranam", hashtags=["#Vaaranam"]
    )
    title_a_id = title_a["id"]
    title_b = await _create_title(
        api_client, organization_id, name="Kanchana", hashtags=["#Kanchana"]
    )
    title_b_id = title_b["id"]

    await _add_mention(
        db_session, title_a_id, text="loving #DCFDFS energy today", hashtags=["DCFDFS"]
    )
    rejection = await _reject(api_client, title_a_id, "#DCFDFS", "hashtag")

    # The rejection id is real, but it belongs to title A — title B must not be able to
    # delete it by naming it in its own path.
    cross_title_response = await api_client.delete(
        _rejection_restore_url(title_b_id, rejection["id"])
    )
    assert cross_title_response.status_code == 404, cross_title_response.text
    body = cross_title_response.json()
    assert body["code"] == "ResourceNotFoundError"

    # Untouched: still refused on title A, and the row still exists.
    suggestions_after = await _list_suggestions(api_client, title_a_id)
    assert _candidate(suggestions_after, "#DCFDFS") is None
    assert len(suggestions_after["rejections"]) == 1

    stored_rejection = (
        await db_session.execute(
            select(TitleAliasRejection).where(
                TitleAliasRejection.title_id == uuid.UUID(title_a_id)
            )
        )
    ).scalar_one()
    assert stored_rejection.id == uuid.UUID(rejection["id"])
