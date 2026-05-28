# Nisaba — Licensing & Third-Party Dependency Audit

**Document purpose:** authoritative reference for Nisaba's licensing posture
and the third-party license inventory of every runtime and build-time
dependency. Used by engineering, legal, and any future investor/acquirer due
diligence. Re-run the audit on every dependency upgrade (see "Re-audit
checklist" at bottom).

**Last audited:** 2026-05-28
**Auditor:** ClaudeBag (architect agent)
**Result:** ✅ Clean — no copyleft contamination. Posture is safe for
closed-source commercial distribution.

---

## 1. Nisaba's own posture

Nisaba (the company) is the sole owner and maintainer of the Software
(the Nisaba WMS codebase). The Software is **closed-source proprietary**.

- **Repository:** `Tuscani712/mwms` (will be renamed to `Tuscani712/nisaba`).
  Must remain **private** on GitHub. Any flip to public is a posture
  violation and must be reversed immediately.
- **License file:** `LICENSE.txt` (proprietary, all rights reserved). Do not
  replace with an OSI-approved license without an explicit licensing-strategy
  decision by leadership.
- **`package.json`:** marked `"license": "UNLICENSED"` and `"private": true`
  — both correct; do not change.
- **`pyproject.toml`:** intentionally has no `license` classifier — Nisaba
  is not a published PyPI package and never will be without a strategy change.
- **Customer-facing license** is a separate document (EULA / Terms of
  Service) negotiated per-customer. `LICENSE.txt` protects the source;
  the EULA defines what running the deployed software permits.

### What this posture forbids

- Publishing the source publicly (GitHub public repo, gists, paste sites,
  Slack screenshots in public channels, Stack Overflow code samples that
  paste production code).
- Distributing binaries or container images outside customer-tenant
  deployments without an executed agreement.
- Accepting external code contributions from anyone who has not signed an
  IP-assignment agreement assigning the work to Nisaba.
- Adding dependencies whose license terms conflict with the above (see §3).

---

## 2. Third-party dependency inventory

Audit method:
- **Python:** `pip-licenses --format=json` against the resolved venv at
  `backend/.venv/`. Captures direct + transitive runtime + dev deps.
- **JavaScript:** scanned every `package.json` under `node_modules/`
  (devDependencies only — there are no runtime JS deps; frontend is static
  HTML + vanilla JS).

### 2.1 Python — 50 packages

License distribution:

| License                          | Count | Status |
|----------------------------------|-------|--------|
| MIT / MIT License                | 29    | ✅ permissive |
| BSD-3-Clause                     | 8     | ✅ permissive |
| Apache-2.0 / Apache Software     | 5     | ✅ permissive |
| BSD-2-Clause                     | 2     | ✅ permissive |
| PSF-2.0                          | 2     | ✅ permissive |
| ISC                              | 1     | ✅ permissive |
| MIT-CMU (HPND variant, Pillow)   | 1     | ✅ permissive |
| Unlicense (email-validator)      | 1     | ✅ public-domain equivalent |
| MPL-2.0 (certifi)                | 1     | ⚠️ weak copyleft — see §3.1 |
| MIT AND PSF-2.0 (greenlet)       | 1     | ✅ permissive |
| Apache-2.0 OR BSD-2-Clause       | 1     | ✅ permissive |
| Apache-2.0 OR BSD-3-Clause       | 1     | ✅ permissive |
| Apache + MIT (uvloop)            | 1     | ✅ permissive |

Full Python inventory: see `audit/python-licenses-2026-05-28.json`
(generated artifact; regenerate on re-audit).

Notable runtime packages: fastapi (MIT), uvicorn (BSD-3), sqlalchemy (MIT),
pydantic (MIT), bcrypt (Apache), pillow (HPND), python-jose (MIT),
cryptography (Apache-2.0 OR BSD-3).

### 2.2 JavaScript — 112 packages (devDependencies only)

License distribution:

| License        | Count | Status |
|----------------|-------|--------|
| MIT            | 93    | ✅ permissive |
| ISC            | 9     | ✅ permissive |
| BSD-2-Clause   | 4     | ✅ permissive |
| BSD-3-Clause   | 3     | ✅ permissive |
| CC0-1.0        | 2     | ✅ public-domain equivalent |
| Python-2.0     | 1     | ✅ permissive (argparse — `node_modules/argparse`) |

**Zero copyleft (GPL/AGPL/SSPL/LGPL) found.**

Notable: stylelint stack, postcss-html, postcss + transitive deps.
None ship to customers — the frontend bundle is hand-written HTML/CSS/JS,
none of `node_modules/` is referenced from served pages. They run only at
dev/CI time for linting.

---

## 3. Watch list — licenses that need ongoing attention

### 3.1 MPL-2.0 (Mozilla Public License) — certifi

**Status:** safe today, monitor on any change.

MPL-2.0 is **file-level weak copyleft**. It triggers when you *modify the
MPL-licensed source files themselves*; it does **not** trigger on linking,
distribution of unmodified copies, or use in a closed-source project.

- Nisaba consumes `certifi` as a pip dependency, unmodified.
- We do not fork or patch `certifi` source files.
- We do not need to publish anything to remain compliant.

**Re-audit trigger:** if anyone proposes vendoring or patching certifi, escalate.

### 3.2 Forbidden licenses (any future dependency carrying one of these is a STOP)

| License | Why forbidden |
|---------|---------------|
| **AGPL-3.0** | Network use counts as distribution → forces source disclosure for SaaS. *The* SaaS landmine. |
| **GPL-2.0 / GPL-3.0** | Strong copyleft via linking. Runtime use in a closed-source product would force the entire product under GPL. |
| **LGPL-2.1 / LGPL-3.0** | Acceptable *only* via dynamic linking with the LGPL component as a separable shared library. In a typical Python/Node project this distinction is hard to maintain — treat as forbidden unless reviewed individually. |
| **SSPL** (MongoDB Server Side Public License) | AGPL-with-teeth; forces release of operational tooling. |
| **Commons Clause / BSL / Elastic License** | "Source-available" licenses that restrict commercial use — incompatible with our charging customers. Read carefully on a case-by-case basis. |
| **CC BY-NC / CC BY-SA / CC BY-ND** | Creative Commons non-commercial or share-alike clauses. Image/asset packs are the usual offender. |
| **WTFPL / "Do What The Fuck You Want To"** | Permissive but unenforceable / unprofessional — some corporate customers reject products that ship with it. Prefer the named permissive equivalents. |

### 3.3 Trademark + patent grant nuances

- **Apache-2.0** grants an explicit patent license from contributors. Good.
- **MIT / BSD** are silent on patents — implied license at best. If a
  dependency carries known patent exposure, prefer an Apache-licensed
  alternative.
- **MPL-2.0** also includes a patent grant.

---

## 4. Per-component license obligations Nisaba ships with the product

Permissive licenses (MIT/BSD/ISC/Apache/etc.) all require **attribution**:
preserving the copyright notice and license text in distributions.

For a SaaS deployment, "distribution" is ambiguous — most licensors interpret
SaaS hosting as not triggering distribution obligations, but the safest
posture is:

1. Maintain a `THIRD_PARTY_NOTICES.md` at the project root listing every
   direct dependency, its license, and a copy of (or link to) the license
   text. **TODO:** generate this file before first customer deploy. The
   automated route is `pip-licenses --format=markdown --with-license-file
   --no-license-path` + a sibling script for JS deps.
2. Include `THIRD_PARTY_NOTICES.md` in the deployed bundle (e.g. served at
   `/legal/third-party` or shipped in the customer's tenant downloads).
3. For Apache-2.0 deps specifically, retain the `NOTICE` file contents if
   present in upstream.

This is a *future-customer* task, not blocking today. Documented here so it
doesn't get forgotten.

---

## 5. Re-audit checklist

Run this whenever:
- Adding a new direct dependency to `pyproject.toml` or `package.json`
- Upgrading a major version of an existing dependency
- Bringing on a new engineer (one-time sign-off on this doc)
- Before any due-diligence event (investor demo, acquisition discussion,
  customer security questionnaire)
- Quarterly, regardless

Steps:
1. Refresh the venv: `cd backend && .venv/bin/pip install -e ".[dev]" -U`
2. Regenerate Python inventory:
   `backend/.venv/bin/pip-licenses --format=json > audit/python-licenses-YYYY-MM-DD.json`
3. Refresh JS deps: `npm install` (root `package.json`)
4. Regenerate JS license tally — script TBD; manual sort-uniq on
   `node_modules/*/package.json` `license` fields works today.
5. Diff against §2.1 and §2.2 here. Any **new** license string requires a
   classification decision (permissive / weak copyleft / forbidden / new
   category).
6. If anything in §3.2 (forbidden) appears, **the upgrade is blocked**.
   Find an alternative or vendor a replacement.
7. Update this file's "Last audited" line and commit.

---

## 6. Acquisition / due-diligence packet

When an investor or acquirer asks "what's your open-source posture and
dependency audit story," this document is the answer. To strengthen the
posture before that conversation:

- [ ] Sign and store IP-assignment agreements for every contributor (founders,
      employees, contractors, advisors with code access).
- [ ] NDA template signed by every customer pilot, prospective investor with
      code access, and any contractor.
- [ ] Generate `THIRD_PARTY_NOTICES.md` (see §4).
- [ ] Document any in-house cryptographic implementations or patentable
      algorithms separately (for now, we use stock `bcrypt` and `python-jose`
      — no in-house crypto).
- [ ] Make sure the GitHub repo has been **private since inception**. If at
      any point it was public, document the exposure window — anything
      committed during that window is harder to claim as a trade secret.

---

## 7. Decision log

| Date | Decision | By |
|------|----------|-----|
| 2026-05-28 | Closed-source proprietary posture confirmed; sole ownership Nisaba | Meatbag |
| 2026-05-28 | Dependency audit baseline established — clean, no copyleft contamination | ClaudeBag |
| 2026-05-28 | `LICENSE.txt` (proprietary) added to repo root | ClaudeBag |

Append a row every time the posture changes or a license-related decision
is made.

---

**See also:** `LICENSE.txt` (the legal instrument itself).
