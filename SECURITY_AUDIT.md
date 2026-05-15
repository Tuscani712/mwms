# WMS Security Audit · v1.3 · 2026-05-15

> **Update 2026-05-15 (fourth batch, same day):** Four more fixes pre-staged: **M-7** (display_picture URL allowlist), **M-8** (MFA backup-code regeneration), **I-4** (decision_notes 500-char cap), **L-1** (AuditLog scaffold + writer wired to login / MFA disable / password change / MFA code regen). Total pre-staged: **14 of 26 findings**.
>
> **Update 2026-05-15 (third batch, same day):** Three more quick-win fixes pre-staged: **M-1** (password byte-length cap), **M-5** (JSON body size middleware), **L-2** (dependency upper bounds). Total pre-staged: **10 of 26 findings**.
>
> **Update 2026-05-15 (second batch, same day):** Three more quick-win fixes pre-staged: **L-4** (offline site enforcement), **L-7** (`User.__repr__` scrubs hashed_password), **M-6** (email format validation).

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
| ~~M-1~~ | ~~**bcrypt 72-byte silent truncation.**~~ **(✅ fixed 2026-05-15, SCO-42)** — `assert_password_bcrypt_safe()` runs as a pydantic `field_validator` on both `PasswordUpdate.new_password` and `UserCreate.password`. Rejects `UTF-8 bytes > 72` with 422 *before* the value reaches bcrypt. No migration needed: anyone with a longer current password was effectively only using the first 72 bytes anyway, and the dev seed is well under the cap. The legacy truncation in `_to_bytes()` stays as a belt-and-suspenders fallback for direct service callers. | `wms/core/security.py:11` (`BCRYPT_MAX_BYTES`, `assert_password_bcrypt_safe`) | — | — | ✅ Pre-staged |
| M-2 | **No password history.** Users can rotate to `password123` → `password124` → `password123`. | `wms/services/profile.py:74` (`update_password`) | Compliance gap. Defeats forced-rotation policies. | Add `password_history` table (user_id, hashed_password, changed_at). Reject if new password matches any of the last N. | Pre-stage table-only? Defer. Table without enforcement is misleading; ship together. |
| M-3 | **Inconsistent HTML escaping in frontend `innerHTML` calls.** `users.js` escapes; `receiving.js`, `shipping.js`, `dashboard.js`, the `empty-state` setter in `users.js` itself, and `profile.js` set strings via `innerHTML` without a consistent escape helper. Today the data is server-controlled, but `display_name`/`department`/`shift` are user-controlled and *will* land in these views. | `frontend/scripts/{receiving,shipping,dashboard}.js`, `users.js:91` | Stored XSS: an operator sets `display_name = '<img onerror=fetch(...) src=x>'` (no server-side allow-list); a supervisor opens the approval queue or the operator dashboard; their token leaks (see H-3). | Centralize `escapeHtml()` in `api.js` or a tiny `dom.js` helper. Lint rule: any `.innerHTML =` on a non-literal must call the helper. | Defer (touches 5 files). Pre-stage the helper in one place? **Tracker-only for now** — fully addressing this is its own ticket. |
| M-4 | **Error messages leak JWT decode internals.** `f"Invalid challenge token: {e}"` returns the `JWTError` string to the client. | `wms/api/v1/mfa.py:51` | Attackers can probe expiry vs. signature vs. malformed differences to refine token forgery. | Return a generic `"Invalid or expired challenge token"`. Log the detail server-side. | ✅ **Pre-staged** — message generified. |
| ~~M-5~~ | ~~**No global request-size cap on JSON endpoints.**~~ **(✅ fixed 2026-05-15, SCO-43)** — `BodySizeLimitMiddleware` checks `Content-Length` against `settings.max_json_body_bytes` (default 1 MB) and returns 413 on oversize. Multipart `/picture/upload` and `/uploads/*` are explicitly exempted — they have their own stricter, content-aware cap (2 MB) that runs *after* the bytes are decoded by Pillow. Both bypass-paths are covered by tests. | `wms/main.py:60` (`BodySizeLimitMiddleware`) | — | — | ✅ Pre-staged |
| ~~M-6~~ | ~~**`email` field has no format validation**~~ **(✅ fixed 2026-05-15, SCO-41)** — permissive `[^\s<>"']+@[^\s<>"']+\.[^\s<>"']+` regex now applied at both `UserCreate` and `UserUpdate`. Rejects garbage and script-tag payloads without re-inheriting EmailStr's `.local` strictness. | `wms/api/v1/admin_users.py:13` (`EMAIL_PATTERN`) | — | — | ✅ Pre-staged |
| ~~M-7~~ | ~~**Approval-workflow URL is unvalidated.**~~ **(✅ fixed 2026-05-15, SCO-45)** — `_validate_picture_url()` in `wms/services/profile.py` enforces a conservative `/uploads/avatars/` allowlist on `display_picture` change requests. `http(s)://`, `data:`, `javascript:`, `file:`, traversal segments (`..`) and protocol-relative `//` are all rejected. External avatars can be reopened later via a product-decided allowlist without revisiting the call site. | `wms/services/profile.py` | — | — | ✅ Pre-staged |
| ~~M-8~~ | ~~**MFA backup codes have no regeneration UX.**~~ **(✅ fixed 2026-05-15, SCO-46)** — `POST /profile/mfa/regenerate-codes` requires `{current_password}`, replaces the existing hashed code set, and emits an `auth.mfa.backup_codes_regenerated` audit event. Old codes immediately fail verification. | `wms/api/v1/mfa.py`, `wms/services/mfa.py` (`regenerate_backup_codes`) | — | — | ✅ Pre-staged |

### 🔵 LOW

| # | Finding | Location | Attack | Fix | Pre-stage? |
|---|---|---|---|---|---|
| ~~L-1~~ | ~~**No security-relevant logging.**~~ **(🟡 partially staged 2026-05-15, SCO-48)** — `audit_log` table + `wms/services/audit_log.py` writer now durably record `auth.login.{success,failure}`, `auth.password.changed`, `auth.mfa.disabled`, `auth.mfa.backup_codes_regenerated`. No alerting / log shipping yet — SEC-6 still owns dashboards, retention, and shipping. The schema landing now is the expensive part; turning it on for the rest of the call sites is one line each. | `wms/models/core.py` (`AuditLog`), `wms/services/audit_log.py` | — | — | 🟡 Partially staged |
| ~~L-2~~ | ~~**Dependency versions unpinned upper-bound**~~ **(✅ fixed 2026-05-15, SCO-44)** — every runtime and dev dep in `pyproject.toml` now has a compat upper bound (e.g., `bcrypt>=4.1,<6`, `Pillow>=10.3,<13`, `pytest>=8.0,<10`). A breaking major release can no longer land silently — it requires an intentional bound bump. | `backend/pyproject.toml:7-29` | — | — | ✅ Pre-staged |
| L-3 | **JWT subjects are predictable** (`WHS-001-001` ascending). | `wms/seeders/seed.py` | Username enumeration via `?q=` search is trivial. Combined with H-1 → effective brute-force. | Out of scope (employee codes are operationally useful). Mitigate at H-1 (rate limit). | n/a |
| ~~L-4~~ | ~~**`Site.is_active` not enforced at JWT validation.**~~ **(✅ fixed 2026-05-15, SCO-39)** — `get_current_user` now rejects with 401 "Site is offline" when the user's site row has `is_online=False`. Maintenance windows / incident-response toggles now reach the auth layer. | `wms/core/deps.py:34` (`get_current_user`) | — | — | ✅ Pre-staged |
| L-5 | **Token TTL of 8 hours with no refresh-token rotation.** Stolen tokens are valid the full shift. | `wms/core/config.py:20` | A pickpocketed phone = 8 hours of access. | Shorten to 1h + add `/auth/refresh` with rotation. | Defer (UX-affecting). |
| L-6 | **No CSRF token on cookie-auth fallback.** Today we use the Authorization header (CSRF-resistant), but `api.js`'s `clear()` path silently strips on 401 and could mask a future cookie-auth migration regression. | `frontend/scripts/api.js` | None today. Future-proofing. | Comment + lint rule. | Defer. |
| ~~L-7~~ | ~~**`hashed_password` reachable on ORM**~~ **(✅ fixed 2026-05-15, SCO-40)** — `User.__repr__` now scrubs the field. A debug-print or accidental f-string with a User instance shows only the safe identity tuple. Regression test asserts neither the field name nor a bcrypt prefix appears in `repr(user)`. | `wms/models/core.py:55` | — | — | ✅ Pre-staged |

### ℹ️ INFO

| # | Item | Note |
|---|---|---|
| I-1 | **Tests don't cover token-after-deactivate.** No test verifies that a deactivated user's existing JWT stops working on the next request. The code does check `is_active.is_(True)` in `get_current_user`, so behavior is correct — but it's untested. | Add a test in `test_admin_users.py`. |
| I-2 | **`Base.metadata.create_all` runs at startup** — fine for dev, but means production isn't using Alembic migrations yet. | Already flagged in `IMPLEMENTATION_ROADMAP.md`. |
| I-3 | **MFA enrollment exposes `secret` plaintext** in the setup response. This is intentional (so users can manually enter the key if QR rendering fails), but worth flagging in a threat model. | If users' setup requests are logged, the secret is in logs. Don't log request bodies. |
| ~~I-4~~ | ~~**Approval queue notes have no length cap on `decision_notes`.**~~ **(✅ fixed 2026-05-15, SCO-47)** — `ApprovalDecision.notes` now `max_length=500` in pydantic, returning 422 instead of bubbling a DB length error. | — |
| I-5 | **Seed data uses uniform `password123`** for all non-admin users. | Documented in `BACKEND_SCHEMA.md`. Acceptable for dev seed. |

---

## Pre-staged fixes (applied)

Fourteen fixes have been scaffolded across four batches the same day. Each is intentionally minimal — bigger items remain on the SEC-1..SEC-7 follow-up list.

### Fourth batch (2026-05-15 later still · SCO-45/46/47/48)

#### 11. `display_picture` URL allowlist (M-7)
`_validate_picture_url()` in `wms/services/profile.py` enforces a conservative `/uploads/avatars/` allowlist. `http(s)://`, `data:`, `javascript:`, `file:`, `..` traversal, and protocol-relative `//` all return 400. The check runs at the service layer so both the API entrypoint and any future programmatic caller go through the same gate. External avatars (if product later decides to support them) can be reopened by extending the allowlist tuple without revisiting consumers.

#### 12. MFA backup-code regeneration (M-8)
`POST /profile/mfa/regenerate-codes` accepts `{current_password}` (password-gated like M-8's sibling H-2 disable), issues a fresh set of 8 backup codes, replaces the stored hashed set, and emits an `auth.mfa.backup_codes_regenerated` audit event. Old codes immediately fail `verify_user_code`. Requires MFA to already be enabled (regenerating codes on a half-enrolled profile is a 400, not a silent no-op).

#### 13. `decision_notes` 500-char cap (I-4)
`ApprovalDecision.notes` is now `Field(default=None, max_length=500)`. DB column was already `String(500)`, so previously the client got a database-driven 500. Now they get a clean 422 with the offending field named.

#### 14. AuditLog scaffold + writer (L-1, partial)
New `audit_log` table (`event_type`, `user_id`, `actor_id`, `site_id`, `ip`, `user_agent`, `occurred_at`, `detail_json`). New `wms/services/audit_log.py` exposes `audit.record(...)` and stable event-type constants. Wired into:
- `auth.login.success` / `auth.login.failure` (in `auth.py`)
- `auth.password.changed` (in `profile.py`)
- `auth.mfa.disabled` / `auth.mfa.backup_codes_regenerated` (in `mfa.py`)

This is intentionally a foundation — SEC-6 still owns alerting, log shipping, retention policy, and extending to the admin-user CRUD paths. The pattern matches the H-4 `LoginAttempt` pre-stage: schema lands now so the bigger ticket doesn't need a second migration.

### Third batch (2026-05-15 later · SCO-42/43/44)

#### 8. bcrypt byte-length validator on password fields (M-1)
`assert_password_bcrypt_safe()` runs as a pydantic `field_validator` on both `PasswordUpdate.new_password` and `UserCreate.password`. Rejects UTF-8 inputs > 72 bytes with 422 before bcrypt gets a chance to silently truncate. Defended against ASCII (73 chars rejected, 72 accepted), emoji (`"🙂" * 19` = 76 bytes rejected), and end-to-end via the password-change endpoint. The legacy `_to_bytes()` truncation stays as a belt-and-suspenders fallback for any direct service caller.

#### 9. Global JSON body size middleware (M-5)
`BodySizeLimitMiddleware` rejects 413 when `Content-Length > settings.max_json_body_bytes` (default 1 MB). Explicitly bypassed for `/uploads/*` and `*/picture/upload` so the multipart pipeline's stricter, content-aware 2 MB cap is the one that matters there. Tests assert both the cap and the bypass.

#### 10. Upper-bound version pins on dependencies (L-2)
Every runtime and dev dep in `pyproject.toml` now has a compat upper bound: `bcrypt>=4.1,<6`, `Pillow>=10.3,<13`, `pydantic>=2.6,<3`, etc. A breaking major release can no longer land silently — it requires an intentional bound bump.

### Second batch (2026-05-15 later · SCO-39/40/41)

#### 5. Offline-site enforcement at auth (L-4)
`get_current_user` now rejects 401 "Site is offline" when the user's site row has `is_online=False`. Taking a site offline for maintenance/incident now actually pulls its users' tokens. ~3 lines in `wms/core/deps.py`.

#### 6. `User.__repr__` scrubs `hashed_password` (L-7)
`<User id=… code=… site=… level=… active=…>` — deliberately omits the hash. Debug print, ORM `str()`, or accidental f-string interpolation can no longer leak the bcrypt digest. ~5 lines in `wms/models/core.py`.

#### 7. Email format validation on admin payloads (M-6)
`UserCreate.email` and `UserUpdate.email` now require `[^\s<>"']+@[^\s<>"']+\.[^\s<>"']+`. Rejects obvious garbage and `<script>`-style payloads (the literal `<` and `>` are excluded by the character class) without re-adopting EmailStr's `.local` strictness. ~3 lines in `wms/api/v1/admin_users.py`.

### Initial batch

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

- ~~Did not introduce a global request-size middleware (M-5) — coupled to deployment tier, easier to do with nginx.~~ **(superseded — added in SCO-43)**
- Did not migrate `python-jose` → `PyJWT` (H-5) — works fine today; deserves its own PR.
- Did not roll out CSP (H-6) — first-time CSP always breaks something; needs a careful incremental rollout, not a drive-by.
- Did not validate `display_picture_url` against an allowlist (M-7) — UX implications around external avatars need a product decision first.

Each is tracked above so nothing is "audited and forgotten".

---

## Test footprint after pre-stage

| Audit ID | Test file | Cases |
|---|---|---|
| C-1, H-2, M-4, I-1 | `tests/test_security_audit_fixes.py` | 7 |
| L-4, L-7, M-6 | `tests/test_security_audit_quickwins.py` | 8 |
| M-1, M-5 | `tests/test_security_audit_batch2.py` | 9 |
| M-7, M-8, I-4, L-1 | `tests/test_security_audit_batch3.py` | 22 |

46 regression tests guarding the 14 pre-staged fixes. Total suite: **125/125 green**.
