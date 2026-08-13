/**
 * The anchor rule, client side (E02-S01).
 *
 * Mirrors `TitleService._ensure_name_is_collectable` and `has_meaningful_content`. This
 * copy exists so the form can block submission and say why before a round trip — it is
 * not the enforcement. The server refuses the same payload independently; if these two
 * ever disagree, the server is right.
 */

export const MIN_UNANCHORED_NAME_LENGTH = 4

/**
 * Matches one character that renders on its own — not whitespace, not in Unicode category
 * C (control/format, where the zero-width family lives), and not a mark (category M).
 *
 * `String.prototype.trim()` removes whitespace but NOT zero-width characters, so a term
 * of nothing but a ZWSP survives a naive `.trim().length > 0` check and reads as real.
 *
 * `\p{M}` was added for E02-S06. A variation selector (U+FE00–FE0F) is category Mn: a real
 * character that paints nothing without a base character to attach to. Without this, a
 * cast entry of one variation selector satisfied the anchor rule and the form's submit
 * button lit up — the same rule wrong in both places rather than a client/server
 * disagreement. Kept in sync with `_renders_on_its_own` in
 * `callsheet/app/core/identity_terms.py`; the server refuses the same payload independently.
 */
const VISIBLE_CHARACTER = /[^\s\p{C}\p{M}]/u

/**
 * Blank-rendering characters that Unicode classifies as letters or symbols, so no
 * category test catches them. Kept in sync with `_BLANK_RENDERING_CHARACTERS` in
 * `callsheet/app/core/identity_terms.py`.
 */
const BLANK_RENDERING = /[ᅟᅠㅤﾠ⠀　]/gu

/**
 * Any mark — non-spacing, spacing, or enclosing. A mark modifies the character before it
 * and never counts as one of its own, spacing marks included: a Devanagari vowel sign is
 * visible, but it is visible *as part of the syllable it attaches to* (E02-S07).
 *
 * Deliberately not global: `.test()` on a global regex advances `lastIndex` between
 * calls, so the same character would alternate between matching and not.
 */
const COMBINING_MARK = /\p{M}/u
const INVISIBLE_CHARACTER = /[\s\p{C}]/u

/**
 * The joiner that fuses what follows into the cluster before it — one emoji family, one
 * Indic conjunct. Its sibling ZWNJ (U+200C) does the opposite and is deliberately absent,
 * so it leaves the two sides counted as two. Kept in sync with `_ZERO_WIDTH_JOINER` in
 * `callsheet/app/core/identity_terms.py`.
 */
const ZERO_WIDTH_JOINER = '‍'

/**
 * A joiner only fuses after one of these. One sitting between two ordinary letters fuses
 * nothing, which is what a stray joiner copied in from another app is — and treating it as
 * fusing would silently shorten a name past the anchor threshold.
 *
 * Every combining-class-9 code point of the scripts this corpus is written in, written as
 * escapes. The server lists the same twelve rather than deriving them from the Unicode
 * combining class, which this side cannot query at all: a rule the two implement
 * differently is worse than one that names its own limits. Escapes rather than the
 * characters because these are invisible in any diff — a *letter* got into this set on the
 * first attempt at writing it by hand. Kept in sync with `_VIRAMAS`.
 */
const VIRAMA = /[\u094d\u09cd\u0a4d\u0acd\u0b4d\u0bcd\u0c4d\u0ccd\u0d3b\u0d3c\u0d4d\u0dca]/u

/** Emoji and their kin. `So` on both sides of a joiner is how a family becomes one glyph. */
const SYMBOL = /\p{So}/u

/** A letter — what a virama's joiner has to be stacking onto for a conjunct to be real. */
const LETTER = /\p{L}/u

/**
 * Skin tones. Category `Sk`, so nothing else treats them as part of the emoji they follow —
 * but they are, and a name made of one skin-toned emoji measured two things a reader sees
 * rather than one. The server lists U+1F3FB–U+1F3FF, which is what this property matches.
 */
const EMOJI_MODIFIER = /\p{Emoji_Modifier}/u

/**
 * Whether a joiner between these actually makes one glyph of them.
 *
 * `beforeBase` is the base of the cluster, which is not always the character literally
 * before the joiner: a skin tone or a variation selector routinely sits in between, and
 * reading the literal character there is how a two-person emoji with skin tones measured
 * four. The virama test does want the literal character, since a virama sits immediately
 * before the joiner.
 */
function joinerFuses(before: string, beforeBase: string | null, after: string): boolean {
  if (VIRAMA.test(before)) return LETTER.test(after) && sharesScriptBlock(before, after)
  return SYMBOL.test(beforeBase ?? before) && SYMBOL.test(after)
}

/**
 * Whether two characters come from the same Indic script block.
 *
 * Each of these scripts occupies its own aligned 128-code-point block — Devanagari at
 * U+0900 down to Sinhala at U+0D80 — so shifting away the low seven bits names the block.
 * Arithmetic rather than a script lookup because this side cannot ask for a character's
 * Unicode script at all, and the server computes it the same way for that reason.
 *
 * "Is the next character a letter" is not enough on its own: a Devanagari virama, a joiner
 * and the Latin letter `A` fused into one cluster, because `A` is unquestionably a letter —
 * and no font stacks a Devanagari consonant onto it. Kept in sync with
 * `_shares_script_block`.
 */
function sharesScriptBlock(left: string, right: string): boolean {
  return (left.codePointAt(0) ?? 0) >> 7 === (right.codePointAt(0) ?? 0) >> 7
}

function stripNonRendering(value: string): string {
  return value.replace(BLANK_RENDERING, '')
}

export function hasMeaningfulContent(value: string): boolean {
  return VISIBLE_CHARACTER.test(stripNonRendering(value))
}

/**
 * How many things a reader sees here — grapheme clusters, not code units (E02-S07).
 *
 * `String.length` counts UTF-16 code units, which is the wrong unit twice over for a rule
 * about how short a name looks. Counting base characters plus spacing marks — what this
 * did before — was wrong a third way: it split an akshara in two, so `सीता` measured 4 and
 * passed the rule while `राधे` measured 3 and was refused, two names of identical length
 * to anyone reading them.
 *
 * Kept in sync with `visible_length` in `callsheet/app/core/identity_terms.py`; the server
 * enforces the same rule independently and is right if the two ever disagree.
 */
export function visibleLength(value: string): number {
  let count = 0
  // The two things a joiner needs to know about what came before it, which are not the
  // same character — see `joinerFuses`.
  let previous: string | null = null
  let clusterBase: string | null = null
  let joinerFollows: string | null = null
  let joinerFollowsBase: string | null = null

  for (const character of stripNonRendering(value)) {
    if (character === ZERO_WIDTH_JOINER) {
      // Nothing counted yet means there is nothing to fuse onto.
      joinerFollows = count > 0 ? previous : null
      joinerFollowsBase = count > 0 ? clusterBase : null
      previous = character
      continue
    }

    if (
      EMOJI_MODIFIER.test(character) ||
      COMBINING_MARK.test(character) ||
      INVISIBLE_CHARACTER.test(character)
    ) {
      previous = character
      continue
    }

    if (joinerFollows !== null && joinerFuses(joinerFollows, joinerFollowsBase, character)) {
      // Fused into the cluster before it, but it becomes that cluster's base — an emoji
      // family chains joiner after joiner and each one fuses onto the last.
      joinerFollows = null
      joinerFollowsBase = null
      previous = character
      clusterBase = character
      continue
    }

    joinerFollows = null
    joinerFollowsBase = null
    previous = character
    clusterBase = character
    count += 1
  }

  return count
}

/** People anchor a query. A hashtag can be as generic as the name it accompanies. */
export interface AnchorFields {
  leadCast: string[]
  directors: string[]
  musicDirectors: string[]
}

export function hasAnchorTerm({ leadCast, directors, musicDirectors }: AnchorFields): boolean {
  return [...leadCast, ...directors, ...musicDirectors].some(hasMeaningfulContent)
}

export function isNameCollectable(name: string, anchors: AnchorFields): boolean {
  if (!hasMeaningfulContent(name)) return false
  if (visibleLength(name) >= MIN_UNANCHORED_NAME_LENGTH) return true
  return hasAnchorTerm(anchors)
}

/** Splits a comma-separated field into clean terms, dropping blanks and invisibles. */
export function parseTermList(rawValue: string): string[] {
  return rawValue
    .split(',')
    .map((term) => term.trim())
    .filter(hasMeaningfulContent)
}
