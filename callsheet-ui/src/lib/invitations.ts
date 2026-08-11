/** The URL an invited colleague opens to accept. Must match the route in `App.tsx`. */
export function buildAcceptanceUrl(token: string, origin: string): string {
  return `${origin}/invitations/accept?token=${encodeURIComponent(token)}`
}
