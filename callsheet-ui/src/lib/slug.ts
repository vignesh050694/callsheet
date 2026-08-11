/** Lowercase, hyphenated, no trailing separators — matches the backend's slug pattern. */
export function toSlug(rawName: string): string {
  return rawName
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
}
