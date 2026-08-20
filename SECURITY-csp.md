# Content-Security-Policy — production hardening

## What the audit said

> **No `Content-Security-Policy` header** anywhere. You're loading Bootstrap, Leaflet, Google
> Translate, and htmx from multiple CDNs — a CSP would contain damage from any injected script.

## Status: partly stale, now fully addressed

That finding was written against `main`, which has no `waste_system/security.py`. On this branch a
CSP has been shipping since commit `4392e80`. Two corrections to the finding itself:

- **Google Translate is gone.** It was replaced by Django's own i18n (`LocaleMiddleware` +
  `.po`/`.mo` catalogues), so there is no `translate.google.com` script to allow-list. Server-side
  translation is also what makes the Nepali UI work without a third-party dependency.
- **Leaflet, Bootstrap and htmx** are real and are allow-listed (`unpkg.com`, `cdn.jsdelivr.net`,
  `cdnjs.cloudflare.com`).

The genuine remaining weakness was **not** the absence of a header — it was that `script-src`
carried `'unsafe-inline'`, which means the policy did not actually stop script injection. This
change provides a working path off `'unsafe-inline'`.

## The three modes

Set `CSP_MODE` in the environment. Default is `compat`, so **deploying this changes nothing** until
you opt in.

**`CSP_MODE=compat`** — the default; use it today.

- Enforced `script-src`: `'self' 'unsafe-inline' <cdn hosts>`
- Report-Only header: not sent
- Inline `onclick=` handlers: keep working
- Stops script injection? **No** — `'unsafe-inline'` allows it.

**`CSP_MODE=report`** — use this to measure before enforcing.

- Enforced `script-src`: `'self' 'unsafe-inline' <cdn hosts>` (unchanged, nothing breaks)
- Report-Only header: the strict nonce policy
- Inline `onclick=` handlers: keep working
- Stops script injection? Not yet, but it tells you exactly what `strict` would break.

**`CSP_MODE=strict`** — the goal; only after `report` is quiet.

- Enforced `script-src`: `'self' 'nonce-<per-request>' 'strict-dynamic'`
- Report-Only header: not sent
- Inline `onclick=` handlers: **blocked** (this is the breaking change)
- Stops script injection? **Yes** — injected script has no valid nonce.

### Recommended rollout

1. **Deploy as-is** (`compat`). Zero behaviour change; you get the existing protections.
2. **Set `CSP_MODE=report` and `CSP_REPORT_URI=<your collector>`.** Browsers keep running the site
   under the permissive policy but report every violation the strict policy *would* have caused.
   Sentry, Report URI, or a small Django view all work as collectors.
3. **Read the reports.** They enumerate exactly which inline handlers remain.
4. **Migrate those handlers** from `onclick="foo()"` to `addEventListener` in a static JS file.
5. **Flip `CSP_MODE=strict`** once reports are quiet.

## What has already been done for step 4

All **30 inline `<script>` blocks** across 21 templates now carry `nonce="{{ csp_nonce }}"`, so they
already satisfy the strict policy. A fresh 128-bit nonce is generated per request in
`SecurityHeadersMiddleware` and exposed to templates by the `waste_system.security.csp_nonce`
context processor.

Django's `json_script` blocks (`type="application/json"`) are deliberately left un-nonced — they are
data, not executable code, and CSP does not gate them.

What is **not** yet done: the **166 inline `on*=` attributes**. These are what `strict` mode will
break, and they are why the default stays `compat`.

## Why `style-src` keeps `'unsafe-inline'`

There are ~116 inline `style="…"` attributes. Unlike scripts, inline CSS is not a code-execution
vector in modern browsers (IE's `expression()` is long dead), so this is a deliberate,
low-risk trade rather than an oversight.

## Subresource Integrity — deliberately not guessed

CDN `<script>`/`<link>` tags have no `integrity=` attributes. SRI is the right fix, but the correct
sha384 hashes must be computed from the real published files, and this environment has no outbound
network. **Fabricated hashes would break every page**, so they were not added.

To add them, run with network access:

```bash
for u in \
  "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" \
  "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" \
  "https://cdn.jsdelivr.net/npm/htmx.org@1.9.12/dist/htmx.min.js" \
  "https://cdn.jsdelivr.net/npm/htmx.org@1.9.12/dist/ext/head-support.js" \
  "https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js" \
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" \
  "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" ; do
  echo "$u  sha384-$(curl -sfL "$u" | openssl dgst -sha384 -binary | openssl base64 -A)"
done
```

Then add `integrity="sha384-…" crossorigin="anonymous"` to each tag. Pin exact versions (already
done) or SRI will break on the next CDN release.

## Full header set emitted

```
Content-Security-Policy:      default-src 'self'; script-src …; style-src …; font-src …;
                              img-src 'self' data: blob: https:; connect-src …;
                              frame-src 'self' https://accounts.google.com;
                              frame-ancestors 'self'; form-action 'self'; base-uri 'self';
                              object-src 'none'; worker-src 'self' blob:; manifest-src 'self'
                              [+ upgrade-insecure-requests on HTTPS]
X-Content-Type-Options:       nosniff
X-Frame-Options:              SAMEORIGIN
Referrer-Policy:              strict-origin-when-cross-origin
Permissions-Policy:           geolocation=(self), microphone=(), camera=(self), payment=()
Cross-Origin-Opener-Policy:   same-origin
Cross-Origin-Resource-Policy: same-origin
```

`connect-src` is the directive doing the heavy lifting even in `compat` mode: it limits fetch/XHR/
WebSocket to our own origin, the four CDNs, and the two map APIs (Nominatim, OSRM). Injected script
cannot exfiltrate a scraped session to an attacker host.

On HTTPS the policy drops plaintext `ws:` and keeps only `wss:`.

## Known deploy-check warnings (both accepted)

- **W009** — short `SECRET_KEY`: an artefact of the local dev `.env`. Production must set a real
  50+ char random key.
- **W019** — `X_FRAME_OPTIONS` is `SAMEORIGIN`, not `DENY`. Deliberate: `admin_drivers.html` uses
  same-origin `<embed>` for licence-document PDF previews. `frame-ancestors 'self'` enforces the
  same restriction via CSP.

## Verification

`_csp_test.py`-style checks covered: header presence, per-mode `script-src` contents, Report-Only
only in `report` mode, nonce uniqueness across requests, `upgrade-insecure-requests` and `wss:`-only
on HTTPS, `report-uri`/`Reporting-Endpoints` wiring, and all six auxiliary headers — 24 assertions,
all passing. Separately: 14 authenticated pages had every executable inline script correctly nonced,
19 routes returned 200/302 in both `en` and `ne`, and 126 rendered inline scripts passed
`node --check`.
