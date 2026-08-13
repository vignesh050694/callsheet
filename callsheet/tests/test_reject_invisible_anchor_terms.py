"""Tests for E02-S06 — Reject invisible characters as anchor terms so the collectability
rule cannot be waved through.

Story: stories/E02-title-setup-identity-discovery/E02-S06-reject-invisible-anchor-terms.md

The story has exactly one Gherkin scenario ("A term made only of an invisible character is
offered as the anchor for a short title"). It maps to exactly one test:

  - test_variation_selector_only_lead_cast_term_is_refused_as_unanchored is the scenario,
    verbatim: `POST .../titles` with `{"name": "DC", "lead_cast": ["️"]}` — the story's
    own reproduction — must be refused with the unanchored-name explanation and no title
    created, where before the fix it returned 201 with `has_anchor_term: true`.

The story's Notes name a second surface (campaign milestone names, sharing the same
`has_meaningful_content` predicate via `TitleService._desired_milestones`) and say fixing
the predicate closes both. That surface's regression test already lives in
`test_anchor_release_date_and_milestones.py` — it was written during E02-S02 as an explicit
characterisation of the (then) open defect, with its own docstring committing to be
rewritten once E02-S06 landed a fix. It has been rewritten here as part of this story's
delivery to assert the fixed behaviour (422, nothing stored) instead of the defect, so it is
not duplicated in this file.

The remaining budget (four tests) is spent where the predicate — rewritten from a category
allow-list to `_renders_on_its_own`, which now also excludes every Unicode mark category
(Mn/Mc/Me) — is most likely to be wrong:

  - test_variation_selector_only_name_is_refused_as_empty_even_with_anchor_term
    extends the fix to the *name* field (not just a term field), which the single Gherkin
    scenario does not exercise, and pins that it takes the empty-name path, not the
    anchor-rule path.
  - test_legitimate_marks_bearing_terms_are_still_accepted_as_anchor is the other side of the
    same coin: a fix that rejects marks must not reject ordinary words that merely contain
    one. Tamil and Devanagari terms carry Mn/Mc marks as a normal part of the script;
    Latin names decompose to a base letter plus a combining accent; and a great many emoji
    in real-world text carry a trailing variation selector (U+FE0F) attached to a visible
    base character — the exact character class this fix touches, so it is the case most
    likely to regress silently.
  - test_earlier_bypass_characters_remain_rejected_as_anchor_terms is a regression sweep,
    through the API, for the six previously-fixed bypasses (ZWSP/ZWNJ/ZWJ/BOM, four
    Hangul filler code points, the Braille blank) against the *rewritten* predicate, since
    `_renders_on_its_own` replaced the category-list implementation those fixes were made
    against.
  - test_has_meaningful_content_unit_for_marks pins the predicate directly (not just through
    the API) on the two cases above that are easiest to get backwards: a mark with no base
    character renders nothing and must be False, while the same mark attached to a base
    character is part of a real glyph and must be True.
"""

import unicodedata

import pytest
from httpx import AsyncClient

from app.core.identity_terms import has_meaningful_content

ORGANIZATIONS_URL = "/api/v1/organizations"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}

# Mirrors app/services/identity_rules.py's UNANCHORED_NAME_MESSAGE exactly, so tests can
# distinguish this rejection from the empty-name 422, which shares a status code and a
# `code` value but not a cause.
UNANCHORED_NAME_MESSAGE = (
    "A title name shorter than 4 characters needs at least one cast or crew name "
    "to anchor it, otherwise collection cannot tell it apart from anything else with that name"
)
EMPTY_NAME_MESSAGE = "A title needs a name"


def _titles_url(organization_id: str) -> str:
    return f"{ORGANIZATIONS_URL}/{organization_id}/titles"


async def _create_organization(client: AsyncClient, payload: dict = SUN_PICTURES_PAYLOAD) -> str:
    response = await client.post(ORGANIZATIONS_URL, json=payload)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_payload(**overrides: object) -> dict:
    payload: dict = {
        "name": "Vaaranam Aayiram",
        "release_date": "2026-09-11",
        "aliases": [],
        "hashtags": [],
        "lead_cast": [],
        "directors": [],
        "music_directors": [],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# The one Gherkin scenario.
# ---------------------------------------------------------------------------


async def test_variation_selector_only_lead_cast_term_is_refused_as_unanchored(
    api_client: AsyncClient,
) -> None:
    """The story's own reproduction, verbatim: a two-character title name ("DC" — the
    story's franchise-collision example) with a single VARIATION SELECTOR-16 (U+FE0F) as
    the only lead cast entry. U+FE0F is category Mn and renders nothing on its own, so it
    is not a real cast member — the submission must be refused exactly like any other
    unanchored short name, and no title may be created.

    Before the fix, `has_meaningful_content` only treated categories Cc/Cf/Zl/Zp/Zs and an
    explicit blank-rendering set as invisible; Mn was not covered, so this returned 201
    with `has_anchor_term: true` (the story's reproduction of the bug).

    Asserted on the exact message, not just the status code: the empty-name 422 path
    shares both the status code and the `code` value with this one, so only
    `UNANCHORED_NAME_MESSAGE` proves the anchor check — not some other check — is what
    caught this."""
    organization_id = await _create_organization(api_client)
    variation_selector_16 = "️"
    assert unicodedata.category(variation_selector_16) == "Mn"

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="DC", lead_cast=[variation_selector_16]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == UNANCHORED_NAME_MESSAGE

    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.status_code == 200, list_response.text
    assert list_response.json()["total"] == 0


# ---------------------------------------------------------------------------
# Budget item 1 — the same character class reaching the *name* field, not a term field.
# ---------------------------------------------------------------------------


async def test_variation_selector_only_name_is_refused_as_empty_even_with_anchor_term(
    api_client: AsyncClient,
) -> None:
    """A title name that is nothing but variation selectors is not a name — even with a
    real cast member supplied, because a real anchor term cannot rescue a name that,
    once cleaned, is not there at all. Same shape as the pre-existing ZWSP/blank-rendering
    "invisible name" tests in test_create_title_with_rich_identity.py, now for the mark
    category this story adds.

    Asserted on `EMPTY_NAME_MESSAGE` specifically, not `UNANCHORED_NAME_MESSAGE`: this
    must take the name-emptiness path, not the anchor path, and a real anchor term
    present proves it was the *name* check that fired."""
    organization_id = await _create_organization(api_client)
    variation_selectors_only = "︀️"

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name=variation_selectors_only, lead_cast=["Vijay Sethupathi"]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == EMPTY_NAME_MESSAGE
    assert body["message"] != UNANCHORED_NAME_MESSAGE


# ---------------------------------------------------------------------------
# Budget item 2 — legitimate marks-bearing terms must still be accepted. This is the
# obvious way a "reject marks" fix breaks real users, and it is script-specific, so it
# would not show up in any ASCII-only test.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "term",
    [
        "தமிழ்",  # Tamil: letters plus a virama (U+0BCD, category Mn)
        "राधे",  # Devanagari: letters plus a spacing vowel sign (U+093E, category Mc)
        "\U0001f31e",  # a plain emoji, no marks attached (sanity boundary)
        "❤️",  # a heart emoji with a trailing variation selector (base + Mn) —
        # the exact combination this fix has to tell apart from a bare variation selector
        "René",  # "René" decomposed: base letters plus a combining acute (Mn)
    ],
    ids=[
        "tamil_word_with_virama",
        "devanagari_word_with_spacing_vowel_sign",
        "plain_emoji_no_marks",
        "emoji_with_trailing_variation_selector",
        "latin_name_with_combining_accent",
    ],
)
async def test_legitimate_marks_bearing_terms_are_still_accepted_as_anchor(
    api_client: AsyncClient, term: str
) -> None:
    """None of these are invisible: each carries at least one visible base character,
    with a mark attached the way real text actually attaches marks. A fix aimed at
    "reject a term that is only marks" must not reject a term that merely contains one —
    each of these, alone in `lead_cast` against the short name "DC", must still satisfy
    the anchor rule and let the title be created.

    The stored value is compared NFKC-normalised, not raw: `clean_display_value`
    NFKC-normalises on the way in (E02-S01), which composes a decomposed accent like
    "René" into its precomposed form — that is unrelated to this story and expected,
    not a sign the term was rejected or mangled."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="DC", lead_cast=[term]),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["has_anchor_term"] is True
    cast_term = next(t for t in body["terms"] if t["term_type"] == "cast")
    assert cast_term["value"] == unicodedata.normalize("NFKC", term)


# ---------------------------------------------------------------------------
# Budget item 3 — the six earlier bypasses must remain closed under the rewritten
# predicate (`_renders_on_its_own`, which replaced the category-list implementation
# those fixes were made against).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "invisible_term",
    [
        "​",  # ZWSP
        "‌",  # ZWNJ
        "‍",  # ZWJ
        "﻿",  # BOM
        "ᅟ",  # HANGUL CHOSEONG FILLER
        "ᅠ",  # HANGUL JUNGSEONG FILLER
        "ㅤ",  # HANGUL FILLER
        "ﾠ",  # HALFWIDTH HANGUL FILLER
        "⠀",  # BRAILLE PATTERN BLANK
    ],
    ids=[
        "zwsp",
        "zwnj",
        "zwj",
        "bom",
        "hangul_choseong_filler",
        "hangul_jungseong_filler",
        "hangul_filler",
        "halfwidth_hangul_filler",
        "braille_pattern_blank",
    ],
)
async def test_earlier_bypass_characters_remain_rejected_as_anchor_terms(
    api_client: AsyncClient, invisible_term: str
) -> None:
    """Regression cover for the six earlier bypasses of this same rule, now against
    `_renders_on_its_own` rather than the category-list predicate those fixes originally
    targeted. Each, alone in `lead_cast` against the short name "DC", must still be
    refused with the anchor-rule message."""
    organization_id = await _create_organization(api_client)

    response = await api_client.post(
        _titles_url(organization_id),
        json=_create_payload(name="DC", lead_cast=[invisible_term]),
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == UNANCHORED_NAME_MESSAGE


# ---------------------------------------------------------------------------
# Budget item 4 — direct unit coverage of `has_meaningful_content` for the two cases
# easiest to get backwards: a mark alone (no base) vs. the identical mark attached to a
# base character.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("️", False),  # variation selector alone — the story's own defect
        ("́", False),  # combining acute alone, no base character
        ("❤️", True),  # base + variation selector — a real glyph
        ("é", True),  # base letter + combining acute — a real glyph ("é")
        ("தமிழ்", True),  # word ending in a virama (Mn)
        ("राधे", True),  # devanagari word with a spacing vowel sign (Mc)
    ],
    ids=[
        "variation_selector_alone",
        "combining_acute_alone",
        "emoji_with_variation_selector",
        "letter_with_combining_acute",
        "tamil_word_with_virama",
        "devanagari_word_with_spacing_vowel_sign",
    ],
)
def test_has_meaningful_content_unit_for_marks(value: str, expected: bool) -> None:
    assert has_meaningful_content(value) is expected
