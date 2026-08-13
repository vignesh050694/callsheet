"""Tests for E02-S07 — Judge title length the way a reader sees it so the anchor rule
treats Indic titles consistently.

Story: stories/E02-title-setup-identity-discovery/E02-S07-measure-title-length-by-grapheme.md

The story has exactly one Gherkin scenario ("Two Devanagari titles of the same perceived
length are set up"). It maps to exactly one test:

  - test_sita_and_radhe_are_both_refused_with_the_same_explanation is the scenario,
    verbatim: "सीता" and "राधे" — the story's own two named examples, each two aksharas
    to a reader — submitted with no cast or crew term, must both be refused, with the
    same explanation. Before this story, `visible_length` counted the Devanagari
    consonant-plus-spacing-vowel-sign syllable as two code points (Lo+Mc counted
    separately), so "सीता" measured 4 and sailed through unanchored while "राधे" measured
    3 and was refused — the exact inconsistency the story exists to remove.

The remaining budget (three tests, of the four allowed) is spent on:

  - test_sita_is_refused_bare_a_deliberate_behaviour_change pins the behaviour change
    itself, isolated from the paired-comparison scenario above: "सीता" alone, which used
    to be accepted with no anchor term, must now be refused. This is the test that
    catches someone "fixing" the rule back to its old behaviour by accident, since the
    story's Notes call this out explicitly as the intended, deliberate effect of the fix
    rather than a side effect of it.
  - test_zero_width_joiner_versus_non_joiner_between_the_same_two_letters attacks the one
    piece of this fix that is not in the story's own text: the implementation's choice to
    make ZWJ bind the next character into the cluster before it (so a joined pair counts
    1) and ZWNJ do nothing of the sort (so a separated pair counts 2). This test pins the
    basic contrast the code implements, using the realistic case both docstrings cite — a
    Devanagari virama-formed conjunct, क् + ष (KA + VIRAMA + SSA).
  - test_stray_zwj_between_ordinary_syllables_fuses_nothing pins round 2's fix to a defect
    round 1 found: ZWJ-binding used to be unconditional, so a stray joiner between two
    *ordinary* live syllables — no virama, no font ligature, nothing UAX #29 would ever
    fuse — still collapsed the count. `_joiner_fuses` now restricts fusing to the two
    cases where it does real work (after a virama, or between two `So` symbols), so a
    joiner anywhere else is inert. This test asserts the fixed behaviour directly: the
    same stray-joiner insertion into "விஸ்வாசம்" (Viswasam) that used to drop the count
    now leaves it unchanged, and a bare joiner between two plain letters with no
    combining marks at all behaves identically.
  - test_real_short_indic_titles_need_an_anchor_where_latin_transliteration_does_not
    is the over-refusal search the task brief asked for: real, commercially released short
    Tamil and Telugu titles, measured against the same rule as their own Latin-script
    transliteration. The finding is reported in the docstring and the delivery report,
    not asserted as a bug — the story explicitly rules out changing the threshold or the
    heuristic, so this is reported rather than fixed.
  - test_virama_joiner_still_fuses_a_real_conjunct_request, test_emoji_family_still_
    fuses_but_mismatched_symbol_letter_sides_do_not, and test_malayalam_virama_is_
    present_and_fuses_a_real_conjunct are round 2's three new tests, added against the
    fix described above: the virama branch of `_joiner_fuses` still honours a genuine
    conjunct request; the symbol branch still assembles an emoji family but not a
    mismatched symbol/letter pair; and the nine-script `_VIRAMAS` set is checked for a
    real Malayalam conjunct, as part of confirming no script this product documents as
    in-scope has a missing virama (see the delivery report for that finding).
  - test_skin_toned_emoji_zwj_sequences_count_one,
    test_virama_joiner_refuses_to_fuse_onto_a_non_letter,
    test_every_virama_has_combining_class_nine_and_fuses_a_real_conjunct, and
    test_skin_toned_couple_emoji_title_refused_without_anchor are round 3's four new tests,
    added against three defects a reviewer found in `visible_length`'s joiner handling after
    round 2: `before_joiner` was the literal preceding code point rather than the pending
    cluster's base, so a skin-tone modifier or variation selector sitting before a ZWJ
    defeated the symbol-fusing test (an undercounted refusal — the dangerous direction, since
    a one-glyph title could then ship with no anchor term); the virama branch fused
    unconditionally regardless of what followed the joiner, when only a following letter is a
    real conjunct request; and `_VIRAMAS` was missing three of its twelve combining-class-9
    code points (Malayalam's vertical-bar and circular viramas, and Sinhala entirely).

Every assertion that could be satisfied by either 422 path (empty name vs. unanchored
name) asserts on the exact message, matching the convention `test_create_title_with_
rich_identity.py` and `test_reject_invisible_anchor_terms.py` already established, since
both paths share a status code and a `code` value.
"""

import unicodedata

from httpx import AsyncClient

from app.core.identity_terms import _VIRAMAS, visible_length

ORGANIZATIONS_URL = "/api/v1/organizations"

SUN_PICTURES_PAYLOAD = {
    "name": "Sun Pictures",
    "slug": "sun-pictures",
    "organization_type": "production_house",
}

# Mirrors app/services/identity_rules.py's UNANCHORED_NAME_MESSAGE exactly (minimum=4),
# so tests can distinguish this rejection from the empty-name 422, which shares a status
# code and a `code` value but not a cause.
UNANCHORED_NAME_MESSAGE = (
    "A title name shorter than 4 characters needs at least one cast or crew name "
    "to anchor it, otherwise collection cannot tell it apart from anything else with that name"
)


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


async def test_sita_and_radhe_are_both_refused_with_the_same_explanation(
    api_client: AsyncClient,
) -> None:
    """The story's scenario, verbatim, using its own two named examples. "सीता" is
    सी (Lo+Mc) + ता (Lo+Mc) and "राधे" is रा (Lo+Mc) + धे (Lo+Mn) — two aksharas each,
    the same length to any reader. Under grapheme clustering both measure 2, below
    `MIN_UNANCHORED_NAME_LENGTH`, so submitting either with no cast or crew term must
    refuse it — and, per the scenario's own wording ("both are refused with the same
    explanation, rather than one being created and the other refused"), the two
    rejections must carry the identical message, not just the identical status code."""
    organization_id = await _create_organization(api_client)
    sita = "सीता"
    radhe = "राधे"
    assert visible_length(sita) == visible_length(radhe) == 2

    sita_response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=sita)
    )
    radhe_response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=radhe)
    )

    assert sita_response.status_code == 422, sita_response.text
    assert radhe_response.status_code == 422, radhe_response.text
    sita_body = sita_response.json()
    radhe_body = radhe_response.json()
    assert sita_body["code"] == radhe_body["code"] == "ValidationFailedError"
    assert sita_body["message"] == radhe_body["message"] == UNANCHORED_NAME_MESSAGE

    # Neither submission created a title.
    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 0


# ---------------------------------------------------------------------------
# Budget item 1 — the deliberate behaviour change, pinned on its own.
# ---------------------------------------------------------------------------


async def test_sita_is_refused_bare_a_deliberate_behaviour_change(api_client: AsyncClient) -> None:
    """Before this story, `visible_length` counted the Mc spacing vowel sign in each of
    "सीता"'s two syllables separately, measuring 4 — at `MIN_UNANCHORED_NAME_LENGTH`, so
    the title was created with no anchor term. Grapheme clustering folds each vowel sign
    into the consonant it belongs to, measuring 2, so the identical submission must now
    be refused.

    This is the story's own stated point, not an accident of the fix: "This is a
    behaviour change... Titles such as सीता that are accepted bare today would then
    require an anchor term. That is the intended reading of the rule." If a future
    change makes this test pass by returning 201 again, it has quietly reverted the
    story rather than fixed anything."""
    organization_id = await _create_organization(api_client)
    sita = "सीता"
    assert len(sita) == 4  # the old, wrong measure (code points) — for contrast only
    assert visible_length(sita) == 2  # the new measure (grapheme clusters)

    response = await api_client.post(_titles_url(organization_id), json=_create_payload(name=sita))

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == UNANCHORED_NAME_MESSAGE

    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 0


# ---------------------------------------------------------------------------
# Budget item 2 — ZWJ vs. ZWNJ: the implementer's own addition beyond the story's text.
# ---------------------------------------------------------------------------


async def test_zero_width_joiner_versus_non_joiner_between_the_same_two_letters(
    api_client: AsyncClient,
) -> None:
    """Mechanical pin of the ZWJ/ZWNJ contrast the implementation adds on top of the
    story's request: `visible_length` treats U+200D (ZWJ) as binding the character that
    follows it into the cluster before it, and treats its sibling U+200C (ZWNJ) as
    ordinary invisible punctuation that does no such binding. Using the realistic case
    the docstrings themselves cite — a Devanagari virama-formed conjunct, क् + ष (KA +
    VIRAMA + SSA) — a ZWJ inserted to force the "kṣa" ligature measures 1, while a ZWNJ
    inserted to force the letters apart measures 2, and the same two letters with no
    joiner at all (a plain, un-ligated conjunct) also measures 2."""
    ka_virama = "क्"  # KA + VIRAMA (U+0915 U+094D)
    ssa = "ष"  # SSA (U+0937)
    zwj = "‍"
    zwnj = "‌"

    joined = ka_virama + zwj + ssa
    separated = ka_virama + zwnj + ssa
    unmarked = ka_virama + ssa

    assert visible_length(joined) == 1
    assert visible_length(separated) == 2
    assert visible_length(unmarked) == 2


async def test_stray_zwj_between_ordinary_syllables_fuses_nothing(
    api_client: AsyncClient,
) -> None:
    """FIXED (round 2): ZWJ-binding in `visible_length` used to be unconditional — it
    did not check that a virama or an emoji-pictographic sequence was actually present,
    so a single ZWJ dropped between two *ordinary* live syllables, with no virama and no
    font ligature between them, still collapsed the count by one. `_joiner_fuses` now
    restricts fusing to the two cases where it does real work (after a virama, or
    between two `So` symbols for an emoji sequence); anywhere else the joiner is inert.

    "விஸ்வாசம்" (Viswasam, a real 2019 Tamil film title) measures 5. Splicing a single
    ZWJ between its first two syllables — a plausible accident of copy-pasting text
    through a source that inserts ZWJs for unrelated font-shaping reasons, not a
    deliberate attack — lands right after "வி"'s vowel sign (Mc, not a virama), so the
    joiner now fuses nothing and the count is unchanged. The same holds with no
    combining marks in the picture at all: a bare ZWJ dropped between two plain
    consonants leaves their count exactly as it was without it."""
    viswasam = "விஸ்வாசம்"
    assert visible_length(viswasam) == 5

    zwj = "‍"
    with_one_stray_joiner = "வி" + zwj + "ஸ்வாசம்"
    assert visible_length(with_one_stray_joiner) == 5

    plain_consonants = "க" + "த"
    with_stray_joiner_between_plain_consonants = "க" + zwj + "த"
    assert visible_length(with_stray_joiner_between_plain_consonants) == visible_length(
        plain_consonants
    )
    assert visible_length(with_stray_joiner_between_plain_consonants) == 2


# ---------------------------------------------------------------------------
# Budget item 3 — over-refusal search: real short Indic titles against the rule their
# own Latin-script transliteration is measured by.
# ---------------------------------------------------------------------------


async def test_real_short_indic_titles_need_an_anchor_where_latin_transliteration_does_not(
    api_client: AsyncClient,
) -> None:
    """FINDING, not a bug report: "பேட்டா" (Petta, a 2019 Rajinikanth film — one of
    Tamil cinema's biggest commercial releases) measures 3 grapheme clusters and is
    refused bare; "పుష్ప" (Pushpa, a 2021 Telugu film that became a global crossover
    hit) measures 3 and is refused bare too. Both are unambiguous, non-generic,
    internationally recognised titles — nothing a reader would call "too short or
    generic to be collectable" — yet the rule this story hardens now blocks their
    native-script names without an anchor term. The same two titles typed in their
    common Latin transliteration ("Petta", "Pushpa") clear the threshold and are
    accepted bare in the same request shape.

    This is arguably the story working as intended: by akshara, "Petta" and "Pushpa"
    really are three syllables each, genuinely short by the rule's own stated
    definition, and the story's Out of scope explicitly forbids changing the four-
    character threshold or the length heuristic as part of this fix. It is reported
    here, pinned by a passing test, rather than left as an unsquashed assumption: the
    same title is collectable in one script and not in the other, which is a live
    product question even though it is not a defect in this story's own delivery."""
    organization_id = await _create_organization(api_client)
    petta_tamil = "பேட்டா"
    petta_latin = "Petta"
    pushpa_telugu = "పుష్ప"
    pushpa_latin = "Pushpa"
    assert visible_length(petta_tamil) == 3
    assert visible_length(petta_latin) == 5
    assert visible_length(pushpa_telugu) == 3
    assert visible_length(pushpa_latin) == 6

    petta_tamil_response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=petta_tamil)
    )
    petta_latin_response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=petta_latin)
    )
    pushpa_telugu_response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=pushpa_telugu)
    )
    pushpa_latin_response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=pushpa_latin)
    )

    assert petta_tamil_response.status_code == 422, petta_tamil_response.text
    assert petta_tamil_response.json()["message"] == UNANCHORED_NAME_MESSAGE
    assert petta_latin_response.status_code == 201, petta_latin_response.text

    assert pushpa_telugu_response.status_code == 422, pushpa_telugu_response.text
    assert pushpa_telugu_response.json()["message"] == UNANCHORED_NAME_MESSAGE
    assert pushpa_latin_response.status_code == 201, pushpa_latin_response.text


# ---------------------------------------------------------------------------
# Round 2 — three new tests pinning the narrowed `_joiner_fuses` fix itself.
# ---------------------------------------------------------------------------


def test_virama_joiner_still_fuses_a_real_conjunct_request() -> None:
    """The narrowing to `_joiner_fuses` must not have thrown out the case it exists
    for: a joiner placed directly after a virama is a genuine conjunct request and
    legitimately fuses — that is correct Unicode behaviour, not a bug, even though it
    looks superficially like the stray-joiner case the round 1 finding was about.

    क् + ZWJ + ष (KA + VIRAMA + ZWJ + SSA) is a real conjunct request and measures 1.
    Removing only the virama — क + ZWJ + ष, the same two letters with the same joiner
    between them — leaves nothing for the joiner to fuse after, so it measures 2. The
    virama's presence, not the joiner alone, is what makes the difference."""
    ka_virama = "क्"  # KA + VIRAMA (U+0915 U+094D)
    ka_no_virama = "क"  # KA alone
    ssa = "ष"
    zwj = "‍"

    assert visible_length(ka_virama + zwj + ssa) == 1
    assert visible_length(ka_no_virama + zwj + ssa) == 2


def test_emoji_family_still_fuses_but_mismatched_symbol_letter_sides_do_not() -> None:
    """The other branch of `_joiner_fuses`: a joiner between two `So` symbols is how an
    emoji family is assembled into one glyph, and that must still work. But the branch
    is specifically "both sides are `So`" — a joiner with a symbol on one side and an
    ordinary letter on the other is not an emoji sequence and must not fuse, regardless
    of which side the symbol is on."""
    man = "\U0001f468"
    woman = "\U0001f469"
    girl = "\U0001f467"
    zwj = "‍"

    family = man + zwj + woman + zwj + girl
    assert visible_length(family) == 1

    symbol_then_letter = man + zwj + "A"
    assert visible_length(symbol_then_letter) == 2

    letter_then_symbol = "A" + zwj + man
    assert visible_length(letter_then_symbol) == 2


def test_malayalam_virama_is_present_and_fuses_a_real_conjunct() -> None:
    """Virama-set completeness check. `_VIRAMAS` lists nine code points: Devanagari,
    Bengali, Gurmukhi, Gujarati, Odia, Tamil, Telugu, Kannada, Malayalam. This suite's
    other tests exercise Devanagari and Tamil directly; Malayalam — chosen because its
    conjunct/chillu behaviour is the most unusual of the nine and the likeliest place
    for a listed-not-derived set to have a subtle mistake — had not been exercised.

    "വിശ്വാസം" (the Malayalam cognate of Tamil "விஸ்வாசம்", meaning "faith") already
    contains a virama-formed conjunct (ശ + virama + വ) and measures 4. Inserting a ZWJ
    directly after that existing virama is a genuine conjunct request and correctly
    fuses it to 3. As a control, a bare ZWJ between the same two consonants with no
    virama present fuses nothing, exactly as the Devanagari/Tamil cases above.

    FINDING (not a defect): searching the product's own docs and stories turned up no
    fixed language/script allowlist anywhere in this codebase — language identification
    is free-text (E04-S01) — and the only place a concrete script list is hard-coded at
    all is `_VIRAMAS`/`VIRAMA` itself. The product's documented in-scope market is Tamil,
    with Telugu appearing as a secondary named example; both are covered. No script
    named anywhere in the product's stories or concept note as in-scope is missing from
    the set — if anything the set is a superset, covering seven more major Indic scripts
    (Devanagari, Bengali, Gurmukhi, Gujarati, Odia, Kannada, Malayalam) beyond the two
    the product currently documents as its target market."""
    faith = "വിശ്വാസം"
    assert visible_length(faith) == 4

    zwj = "‍"
    virama_index = faith.index("്")
    forced_conjunct = faith[: virama_index + 1] + zwj + faith[virama_index + 1 :]
    assert visible_length(forced_conjunct) == 3

    sha = "ശ"
    va = "വ"
    assert visible_length(sha + zwj + va) == visible_length(sha + va) == 2


# ---------------------------------------------------------------------------
# Round 3 — three defects a reviewer found in `visible_length`'s joiner handling,
# all now fixed: (1) the dangerous one, an undercounted refusal, where
# `before_joiner` was the literal preceding code point rather than the pending
# cluster's base, so a skin-tone modifier or variation selector sitting between an
# emoji and the joiner defeated the `So`-on-both-sides symbol test; (2) the virama
# branch fused unconditionally, with no check on what followed the joiner; (3)
# `_VIRAMAS` was missing three of the twelve combining-class-9 code points across
# the scripts this corpus covers (Malayalam's two rarer viramas, and Sinhala
# entirely).
# ---------------------------------------------------------------------------


def test_skin_toned_emoji_zwj_sequences_count_one() -> None:
    """FINDING 1, the dangerous defect: a title that is genuinely one glyph to a
    reader could previously ship with no anchor term, because `visible_length`
    undercounted it as *more* clusters than it has, not fewer — the anchor rule
    triggers on "too short", so overcounting a one-glyph name as several was the
    silent, unsafe direction to get this wrong in.

    The break was reading the literal character immediately before a ZWJ rather
    than the base of the cluster it belongs to. A skin-tone modifier (`Sk`,
    U+1F3FB-U+1F3FF) routinely sits in that position in real emoji sequences, and
    `_joiner_fuses`'s symbol test (`category(before) == 'So'`) never matched an
    `Sk` character, so the fuse silently failed to apply.

    "woman(medium skin tone) + ZWJ + man(medium skin tone)" is one glyph (a
    'couple' emoji) and must measure 1 — the story's own bug report says this
    measured 4 before the fix. Chaining a second joiner through a heart with an
    explicit variation selector in between — the real 'couple with heart' ZWJ
    sequence, U+1F469 U+1F3FD U+200D U+2764 U+FE0F U+200D U+1F468 U+1F3FD — adds a
    second base-vs-literal trap (the character right before the second ZWJ is the
    variation selector, not the heart) and must still measure 1; the bug report
    says this measured 5."""
    zwj = "‍"
    woman = "\U0001f469"
    man = "\U0001f468"
    medium_skin_tone = "\U0001f3fd"
    heart = "❤"
    variation_selector_16 = "️"

    couple = woman + medium_skin_tone + zwj + man + medium_skin_tone
    assert len(couple) == 5  # the undercounted-refusal measure the bug produced
    assert visible_length(couple) == 1

    couple_with_heart = (
        woman
        + medium_skin_tone
        + zwj
        + heart
        + variation_selector_16
        + zwj
        + man
        + medium_skin_tone
    )
    assert len(couple_with_heart) == 8  # the undercounted-refusal measure the bug produced
    assert visible_length(couple_with_heart) == 1


def test_virama_joiner_refuses_to_fuse_onto_a_non_letter() -> None:
    """FINDING 2: the virama branch of `_joiner_fuses` fused unconditionally,
    without checking what came after the joiner at all. A virama plus a joiner is
    a request to stack a consonant onto whatever follows, and that request is
    only real Unicode behaviour when what follows is another letter — stacking a
    consonant onto a digit or an emoji is not a conjunct, and the bug report says
    all three (letter, digit, emoji) measured 1 before the fix.

    क् + ZWJ + a digit and क् + ZWJ + an emoji must both measure 2 — the joiner
    is inert — while क् + ZWJ + a real consonant (ष) still measures 1, so the
    fix is a refusal to fuse onto non-letters specifically, not a break of the
    conjunct case the branch exists for."""
    ka_virama = "क्"  # KA + VIRAMA (U+0915 U+094D)
    ssa = "ष"
    zwj = "‍"

    assert visible_length(ka_virama + zwj + "5") == 2
    assert visible_length(ka_virama + zwj + "\U0001f600") == 2
    assert visible_length(ka_virama + zwj + "A") == 2
    assert visible_length(ka_virama + zwj + ssa) == 1


def test_virama_joiner_refuses_to_fuse_across_script_blocks() -> None:
    """Pins the rule `_shares_script_block` was just added for: the letter-check the
    test above pins is not enough on its own, because "letter" alone let क् + ZWJ + "A"
    fuse to 1 — "A" is a letter, just not one from the virama's own script. The virama
    branch of `_joiner_fuses` now also requires the letter following the joiner to
    share the virama's Unicode script block (`ord(c) >> 7`, since each of these Indic
    scripts occupies its own aligned 128-code-point block), mirrored in TypeScript by
    `sharesScriptBlock` in `callsheet-ui/src/lib/title-identity.ts`. A virama followed
    by a joiner and a letter of its OWN script is still a genuine conjunct request and
    fuses; the same shape with a letter from a DIFFERENT Indic script is not a conjunct
    a reader would ever see as one glyph, and must not fuse — in either direction.

    क् + ZWJ + ष (Devanagari virama, Devanagari letter) measures 1, as it always has.
    क् + ZWJ + ப (Devanagari virama, Tamil letter) measures 2. க் + ZWJ + க (Tamil
    virama, Devanagari letter) also measures 2 — the mismatch is refused regardless of
    which of the two scripts the virama itself belongs to."""
    devanagari_ka_virama = "क्"  # KA + VIRAMA (U+0915 U+094D)
    devanagari_ssa = "ष"  # SSA (U+0937), same script as the virama above
    tamil_pa = "ப"  # PA (U+0BAA), a different Indic script
    tamil_ka_virama = "க்"  # Tamil KA + VIRAMA (U+0B95 U+0BCD)
    devanagari_ka = "क"  # KA (U+0915), a different Indic script from the virama above
    zwj = "‍"

    assert visible_length(devanagari_ka_virama + zwj + devanagari_ssa) == 1
    assert visible_length(devanagari_ka_virama + zwj + tamil_pa) == 2
    assert visible_length(tamil_ka_virama + zwj + devanagari_ka) == 2


# Doubled first consonant ("KA-KA") of each script `_VIRAMAS` covers — a real,
# common conjunct shape (gemination) rather than an arbitrary letter pairing, so
# forcing it with an explicit ZWJ after the virama is a genuine conjunct request
# in every one of the twelve scripts, not a synthetic one.
_DOUBLED_KA_BY_VIRAMA = {
    "्": "क",  # Devanagari
    "্": "ক",  # Bengali
    "੍": "ਕ",  # Gurmukhi
    "્": "ક",  # Gujarati
    "୍": "କ",  # Odia
    "்": "க",  # Tamil
    "్": "క",  # Telugu
    "್": "ಕ",  # Kannada
    "഻": "ക",  # Malayalam, vertical bar virama
    "഼": "ക",  # Malayalam, circular virama
    "്": "ക",  # Malayalam, plain virama
    "්": "ක",  # Sinhala
}


def test_every_virama_has_combining_class_nine_and_fuses_a_real_conjunct() -> None:
    """FINDING 3: `_VIRAMAS` was missing three of the twelve combining-class-9
    code points in the scripts this corpus covers — Malayalam's vertical-bar
    (U+0D3B) and circular (U+0D3C) viramas, and Sinhala's al-lakuna (U+0DCA) were
    all absent, so a genuine conjunct request in those scripts silently failed to
    fuse.

    Checked two ways, matching how the mistake the story's own comment describes
    actually happened: pasting U+0D3A MALAYALAM LETTER TTTA — a *letter*, not a
    virama — into the set by hand. `unicodedata.combining(...) == 9` is the
    invariant a letter can never satisfy (a letter has combining class 0), so it
    would have caught that mistake directly, independent of whether the specific
    letter used also happened to break a scripted conjunct test.

    First, `_VIRAMAS` itself: every member has combining class 9, and there are
    exactly twelve. Second, behaviour: for every member, that script's own first
    consonant doubled around the virama with an explicit ZWJ — a real,
    unremarkable geminated conjunct — measures 1, not 2."""
    assert len(_VIRAMAS) == 12
    for virama in _VIRAMAS:
        assert unicodedata.combining(virama) == 9, (
            f"{virama!r} (U+{ord(virama):04X}) is not combining class 9 — "
            "it does not belong in _VIRAMAS"
        )

    assert set(_DOUBLED_KA_BY_VIRAMA) == _VIRAMAS
    zwj = "‍"
    for virama, ka in _DOUBLED_KA_BY_VIRAMA.items():
        forced_conjunct = ka + virama + zwj + ka
        assert visible_length(forced_conjunct) == 1, (
            f"virama U+{ord(virama):04X} did not fuse its own script's doubled consonant"
        )


# ---------------------------------------------------------------------------
# Round 3, budget item 4 — end-to-end regression for Finding 1's actual stakes:
# not just that `visible_length` returns 1, but that the anchor rule the story
# exists to fix actually refuses a one-glyph title on that basis.
# ---------------------------------------------------------------------------


async def test_skin_toned_couple_emoji_title_refused_without_anchor(
    api_client: AsyncClient,
) -> None:
    """What Finding 1 was actually dangerous about, end to end: with the bug in
    place, "woman(skin-tone) + ZWJ + man(skin-tone)" measured 4 — at
    `MIN_UNANCHORED_NAME_LENGTH` — so a title that is one glyph to a reader would
    have been created with no cast or crew term, sailing straight past the rule
    this story exists to enforce. With the fix, the same title measures 1 and
    must be refused bare, exactly like "सीता" and "राधे" above."""
    organization_id = await _create_organization(api_client)
    zwj = "‍"
    woman = "\U0001f469"
    man = "\U0001f468"
    medium_skin_tone = "\U0001f3fd"
    couple = woman + medium_skin_tone + zwj + man + medium_skin_tone
    assert visible_length(couple) == 1

    response = await api_client.post(
        _titles_url(organization_id), json=_create_payload(name=couple)
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "ValidationFailedError"
    assert body["message"] == UNANCHORED_NAME_MESSAGE

    list_response = await api_client.get(_titles_url(organization_id))
    assert list_response.json()["total"] == 0
