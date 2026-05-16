# WMS Settings Registry

> Accumulator of all client-configurable knobs surfaced from each page workflow. SCO-53 (System Settings page) renders from this registry — no speculative settings are built before their consumer ships.
>
> **Contract**: adding a knob = appending one row in the same commit that introduces the consumer code.
>
> Columns:
> - **Key** — dot-notation identifier used in code (`module.subgroup.name`)
> - **Type** — `int` / `bool` / `float` / `enum` / `list[int]` / `str`
> - **Default** — hardcoded fallback if no DB row resolves
> - **Bounds** — server-validated min/max or allowed values
> - **Scope** — finest scope this setting can be overridden at (`global` / `site` / `role` / `user`)
> - **Edit level** — minimum `permission_level` to change
> - **Audit** — emits `settings.changed` on update (always yes)
> - **Hot-reload** — does change apply without restart?
> - **Source** — task ID that introduced it

| Key | Type | Default | Bounds | Scope | Edit Lvl | Hot-reload | Source |
|---|---|---|---|---|---|---|---|
| _(populated as each task lands — empty until SCO-49 ships)_ | | | | | | | |

---

## Already-shipped knobs (to be folded in when SCO-53 lands)

These exist in code today but aren't yet rendered in the settings UI. SCO-53 wraps them so the admin doesn't need to edit DB rows directly.

| Key | Lives in | Notes |
|---|---|---|
| `auth.password_policy.*` | `password_policies` table | Already DB-driven via `/admin/policy/password`. SCO-53 surfaces a friendlier UI on top. |
| `auth.mfa.require_mfa` | `password_policies.require_mfa` | Same table; per-scope. |
| `profile.field_visibility.*` | `user_profile_fields` table | Per-field visible/editable, already DB-driven. |
| `system.body_size_limit_bytes` | `Settings.max_json_body_bytes` (env) | Currently env-only; needs settings-table wrapper. |
| `uploads.max_avatar_bytes` | `Settings.max_upload_bytes` (env) | Same. |
| `uploads.max_avatar_dimension` | `Settings.max_image_dimension` (env) | Same. |
| `auth.token_ttl_min` | `Settings.token_ttl_min` (env) | Same — note: audit L-5 covers shortening. |
| `system.site_offline` | `sites.is_online` column | DB-driven per-site; SCO-53 exposes the toggle with confirm modal + cooldown. |
| `branding.logo_url` | `localStorage` (client-only) | SCO-53 promotes to server-persisted per-site. |

---

**Version**: 0.1 (skeleton)  
**Last Updated**: 2026-05-15
