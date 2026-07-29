# Marketing / Social Posting Setup

Covers `marketing_poster.py` (Reddit/Twitter/Instagram posting) and the
admin auth it sits behind. See the frontend repo's `SOCIAL_PIPELINE.md`
for the daily content-generation half (that's a separate repo/pipeline
that calls the endpoints documented here).

## Admin auth is stateless (as of the fix below)

`_make_admin_token()` / `_verify_admin_token()` in `app.py` derive the
token as an HMAC of `ADMIN_PASSWORD` itself — **not** a randomly-issued
value tracked in server memory. This was a real bug that caused a lot
of confusion in one session: the old version stored issued tokens in
an in-memory `set()`, which gets wiped on every backend restart/
redeploy. Since this repo redeploys often, anyone already logged into
the admin panel would get silently logged out mid-session with a
generic "Unauthorized" that looked like a real auth or credentials
bug — it wasn't, it was just a stale token from before the last
restart.

**Do not revert this to a random/stored token.** A solo-admin tool with
no per-user sessions or revocation requirement has no real need for
that, and it's what caused the confusion.

## Render deploy behavior — check this if a push "isn't taking effect"

This service's deploy history showed every deploy as "Manually
triggered by you via Dashboard" despite Auto-Deploy being set to
**"On Commit"** in Settings → Deploy. In practice, pushes sometimes sat
un-deployed for several minutes without anyone noticing, which looked
exactly like "the fix doesn't work" when it just hadn't gone out yet.

**If a backend fix seems to not be working:** check
`dashboard.render.com` → the service → **Events** tab first, confirm
the latest commit SHA actually shows "Deploy live", before assuming the
code itself is wrong. If it's not there, use **Manual Deploy → Deploy
latest commit** to force it rather than waiting.

## Twitter/X

`post_twitter(text, image_url="")` in `marketing_poster.py`.

- OAuth 1.0a, via `requests_oauthlib.OAuth1`. Needs 4 env vars:
  `TWITTER_API_KEY`, `TWITTER_API_SECRET`, `TWITTER_ACCESS_TOKEN`,
  `TWITTER_ACCESS_SECRET` (plus `TWITTER_USERNAME` for building the
  result URL — cosmetic only, not used for auth).
- **The X app's "User authentication settings" must be set to "Read and
  Write"** (Developer Portal → app → User authentication settings), and
  **the Access Token must be regenerated *after* that setting is
  saved** — a token generated under the old permission level doesn't
  retroactively gain the new permission. Symptom if this is wrong:
  `403 oauth1-permissions` error.
- Image attachment requires the older v1.1 `media/upload.json` endpoint
  even though the actual tweet is created via v2 — there's no v2
  equivalent for media upload. Pass the image as a
  `(filename, bytes, content_type)` tuple to `requests`' `files=`, not
  raw bytes — an under-specified multipart part can get rejected.
- **This API tier charges per post now** (pay-per-use credits on the
  Developer Portal's newer "Pay Per Use" project type). If credits hit
  $0, posting fails with `402 Payment Required` / "credits depleted".
  Given that, Twitter posting is treated as **manual-only** in the
  actual pipeline (see frontend `SOCIAL_PIPELINE.md`) — this function
  still exists and works, it's just not called automatically.
- **Whitespace in env vars breaks OAuth1 signing silently** — a stray
  trailing newline copied from a browser into Render's env var field
  produces a `215: Bad Authentication data` error that looks like wrong
  credentials. All four values are `.strip()`'d defensively; if you
  re-paste any of them, still double check for accidental whitespace.

## Instagram

`post_instagram(caption, image_url)` in `marketing_poster.py`.

**Critical: this app uses the "Instagram API with Instagram Login" flow,
not the older Facebook-Login-linked one.** Tokens from this flow start
with `IGAA`. This matters because the two flows use genuinely different
hosts and request formats, and mixing them up produces a misleading
`"Invalid OAuth access token - Cannot parse access token"` error that
looks like a bad/corrupted token when the token is actually fine:

| | Instagram Login (this app) | Facebook Login (older, NOT this app) |
|---|---|---|
| Host | `graph.instagram.com` | `graph.facebook.com` |
| Body | JSON | URL query params |
| Auth | `Authorization: Bearer <token>` header | `access_token` query param |

If you ever regenerate credentials and it starts throwing that "cannot
parse" error again, this mismatch is the first thing to check — it is
not necessarily a bad token.

**Setup, from scratch, if this ever needs redoing:**
1. Instagram account must be a Business or Creator professional
   account (Instagram app → Settings → Professional account).
2. Needs a Facebook Page linked to it (Instagram → Settings → Business
   tools and controls → connect a Page). The Facebook login used for
   the Developer Portal must use a real name — Facebook disables
   profiles that look like a brand/business name, which would kill
   access to everything tied to it.
3. `developers.facebook.com` → create an app → add the **"Manage
   messaging & content on Instagram"** use case → also separately add
   the `instagram_business_content_publish` permission on the
   **Permissions and features** page (it's not in the "required" bundle
   the use-case setup adds automatically, but it's the one that
   actually lets the app publish, so don't skip it).
4. Add the Instagram account as an **"Instagram Tester"** role (not the
   generic "Tester" role — that one wants a Facebook developer account,
   not an Instagram handle, and will reject it) under App Roles →
   Roles → Add People.
5. Accept the tester invite from the Instagram side at
   `instagram.com/accounts/manage_access` — this exact URL, it's not
   surfaced anywhere obvious in Instagram's own Settings menus.
6. Back in the Developer Console → "API setup with Instagram login" →
   "Generate access tokens" → Add account → log in as the Instagram
   account in the popup → Allow.
7. Copy the **Access Token** and the **Instagram Account ID** from that
   same row (not the "Instagram app secret" near the top of the page,
   and not the OAuth 2.0 Client ID/Secret shown earlier in setup —
   neither of those are used here).
8. Set `INSTAGRAM_ACCESS_TOKEN` and `INSTAGRAM_ACCOUNT_ID` on Render.
   **Copy with Cmd+A inside the field, not a manual drag-select**, and
   double check for trailing whitespace — same class of bug as Twitter.

**Two-step publish, and a real timing gotcha:** creating the media
container (`POST /{id}/media`) can succeed while the image is still
being processed by Instagram's servers. Publishing immediately
(`POST /{id}/media_publish`) can then fail with
`"Media ID is not available"` (error code 9007) even though nothing
was actually wrong — it just wasn't ready yet. The code polls the
container's `status_code` (via `GET /{container_id}?fields=status_code`)
until it reports `FINISHED` before publishing, capped at ~12s total so
the request can't run into gunicorn's default 30s worker timeout (no
`--timeout` override in the `Procfile`).

## AI-generated content (`/api/admin/marketing/generate`)

Uses `gpt-4o-mini` with an explicit system prompt banning em dashes and
emojis (user requirement — "no em dashes, no goofy emojis" in
generated posts). There's also a server-side `.replace('—', ', ')`
strip on the response as a backstop, since LLMs reach for em dashes
regardless of being told not to. If this rule ever needs loosening,
both the prompt and the strip need updating together.
