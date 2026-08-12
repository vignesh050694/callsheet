/** The URL an invited colleague opens to accept. Must match the route in `App.tsx`. */
export function buildAcceptanceUrl(token: string, origin: string): string {
  return `${origin}/invitations/accept?token=${encodeURIComponent(token)}`
}

/**
 * The URL a tagged artist opens to accept (E01-S04). A separate route from the one
 * above because the two tokens live in different tables and redeem through different
 * endpoints — sending an artist to the organization link is the bug E01-S03's review
 * caught, and one shared route would invite it back.
 */
export function buildTitleAcceptanceUrl(token: string, origin: string): string {
  return `${origin}/titles/invitations/accept?token=${encodeURIComponent(token)}`
}
