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
 * Matches one character that actually renders — not whitespace, and not in Unicode
 * category C (control/format, which is where the zero-width family lives).
 *
 * `String.prototype.trim()` removes whitespace but NOT zero-width characters, so a term
 * of nothing but a ZWSP survives a naive `.trim().length > 0` check and reads as real.
 */
const VISIBLE_CHARACTER = /[^\s\p{C}]/u

/**
 * Blank-rendering characters that Unicode classifies as letters or symbols, so no
 * category test catches them. Kept in sync with `_BLANK_RENDERING_CHARACTERS` in
 * `callsheet/app/core/identity_terms.py`.
 */
const BLANK_RENDERING = /[ᅟᅠㅤﾠ⠀　]/gu

/**
 * Non-spacing and enclosing marks paint on top of the previous character and add no
 * width. Spacing marks (`\p{Mc}`) are excluded from this pattern on purpose: Devanagari,
 * Telugu and Tamil vowel signs are Mc and occupy their own rendered width.
 *
 * Deliberately not global: `.test()` on a global regex advances `lastIndex` between
 * calls, so the same character would alternate between matching and not.
 */
const COMBINING_MARK = /[\p{Mn}\p{Me}]/u
const INVISIBLE_CHARACTER = /[\s\p{C}]/u

function stripNonRendering(value: string): string {
  return value.replace(BLANK_RENDERING, '')
}

export function hasMeaningfulContent(value: string): boolean {
  return VISIBLE_CHARACTER.test(stripNonRendering(value))
}

/**
 * How many characters this actually paints. `String.length` counts UTF-16 code units,
 * which is the wrong unit twice over for a rule about how short a name looks — combining
 * marks and joined emoji both inflate it.
 */
export function visibleLength(value: string): number {
  return [...stripNonRendering(value)].filter(
    (character) => !COMBINING_MARK.test(character) && !INVISIBLE_CHARACTER.test(character),
  ).length
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
