# Testing and CI

[![Tests](https://github.com/educationroz/waste_reporting_system/actions/workflows/tests.yml/badge.svg)](https://github.com/educationroz/waste_reporting_system/actions/workflows/tests.yml)

## Running the suite

```bash
python manage.py test --settings=waste_system.test_settings
```

`waste_system/test_settings.py` imports the real settings and overrides only what
makes tests fast and readable:

- application loggers silenced (a full run used to print dozens of `NOTIF PUSH` lines)
- MD5 password hasher instead of PBKDF2
- in-memory channel layer, so no Redis needed
- throttle rates raised so repeated requests don't 429
- `CSP_MODE='compat'` pinned, so header tests assert the shipping default

Runtime: **~0.9 s** versus ~10.4 s with the default settings.

Plain `python manage.py test` still works; it's just slower and noisier.

## What the audit finding asked for

> **Automated tests + CI** — `tests.py` exists in each app but scanning suggests light
> coverage; wiring GitHub Actions to run `manage.py test` on every push would catch
> regressions like the ones already fixed in your commit history.

Correct on both counts, and worse than "light" on inspection:

- **12 tests existed and 2 of them were already failing.** `BackupRestoreTests` created a
  `role='admin'` user, but backup/restore is gated by `IsSuperAdminUser`, which also needs
  `is_superadmin=True` — so both tests got a 403 while asserting 400-level behaviour. A
  second test predated the `admin_password` re-confirmation now required by restore.
  Wiring CI first would only have produced a permanently red badge.
- **`web_app/tests.py` was an empty stub** — no coverage of the views that render every page.
- **`pip install -r requirements.txt` could not succeed on Linux.** `python-magic-bin` is a
  Windows-only wheel with no platform marker, so any Ubuntu runner failed at install.

## Coverage now: 43 tests

| Area | File | What it protects |
|---|---|---|
| Backup/restore permissions | `api_app/tests.py` | superadmin gate, password re-confirmation, invalid JSON |
| Driver/user lifecycle | `api_app/tests.py` | profile auto-creation, cascade deletion |
| Checkpoints | `api_app/tests.py` | public read, admin-only write |
| Notifications | `api_app/tests.py` | dedupe window |
| Request grouping | `api_app/tests.py` | same-location grouping, driver assignment |
| Registration | `auth_app/tests.py` | privilege escalation via submitted `role` |
| WebSocket limits | `api_app/test_ws_limits.py` | connection cap (4008), handshake rate (4010), message flood (4009), anonymous rejection (4001) |
| Security headers | `web_app/tests.py` | CSP modes, nonce freshness, map-API allow-list, hardening headers |
| Page rendering | `web_app/tests.py` | every route per role, plus Nepali rendering |

### These tests were checked against mutations

A test that cannot fail is worse than no test. Each new area was verified by deliberately
breaking the implementation and confirming the suite went red:

| Mutation | Result |
|---|---|
| Remove the nonce from strict-mode CSP | 4 failures |
| Make the handshake limiter always return `True` | 2 failures |
| Never release a connection slot on disconnect | 3 failures |

All were caught, and the suite returned to green once reverted.

## CI

`.github/workflows/tests.yml` runs on **every push, every PR**, and on manual dispatch.
In-progress runs for the same branch are cancelled when you push again.

Job `test` (blocking):

1. `makemigrations --check --dry-run` — catches a model changed without a migration
2. `manage.py check`
3. `manage.py test --settings=waste_system.test_settings`

Job `deploy-checks` (advisory, `continue-on-error`): runs `manage.py check --deploy` with
`DEBUG=False`. It reports the production-settings checklist without blocking a merge.
It currently reports **W019** only — deliberate, because `admin_drivers.html` uses
same-origin `<embed>` for licence-PDF previews. `frame-ancestors 'self'` enforces the same
restriction through the CSP.

### Notes for the runner

- **Python 3.12** is required: `requirements.txt` pins Django 6.0.4 and numpy 2.5.2, both of
  which need `>=3.12`. Don't lower it without changing those pins.
- **`libmagic1`** is installed via apt. `python-magic` is a ctypes binding and needs the real
  C library; the bundled Windows wheel is now correctly skipped on Linux.
- **Environment variables are mandatory, not decorative.** `settings.py` reads them through
  `python-decouple`. This was verified by unsetting them and watching `manage.py check` fail.

## Two fixes made so CI could work at all

1. **`python-magic-bin` platform marker.** Changed to
   `python-magic-bin==0.4.14; sys_platform == "win32"`. Windows installs are unaffected;
   Linux and macOS now resolve. Verified with `packaging.requirements`.

2. **Duplicate `GOOGLE_OAUTH_CLIENT_ID`.** The setting was assigned twice — once with
   `default=''`, then again 30 lines later *without* a default, silently overriding the
   first. A fresh checkout could not run `manage.py check`. The duplicate is removed;
   `GoogleLoginView` already returns 503 "not configured" when the value is empty, which is
   the right failure mode for an optional integration.

Also removed: a `logging.basicConfig(level=INFO)` sitting at import time in
`api_app/views.py`. It reconfigured the **root** logger for the whole process. Logging now
lives in `settings.LOGGING` and is tunable with `LOG_LEVEL`.

## Adding tests

Async consumer tests need `TransactionTestCase` (not `TestCase`) because the channels test
client runs in a real event loop. Use the `make_communicator()` helper in
`api_app/test_ws_limits.py`: it sets an explicit client IP, without which every test shares
one rate-limit bucket and they interfere with each other.
