/* ═══════════════════════════════════════════════════════════════════════════
   Admin · System Settings — registry-driven knob editor (SCO-53)
   ─────────────────────────────────────────────────────────────────────────
   This page reads a *form schema* from the server (GET /admin/settings/registry)
   and renders one row per setting. The server is the source of truth for which
   keys exist, their types, bounds, and edit-level gates — the client cannot
   inject arbitrary keys because the server rejects anything not in its
   registry (see backend/wms/api/v1/settings.py contract).

   While the backend is still TODO, we ship with a FROZEN LOCAL FALLBACK so the
   page renders as documentation of the intended UX. The fallback mirrors what
   PAGES_WORKFLOW §5 + SETTINGS_REGISTRY.md describe. When the live endpoint
   lands the fallback is bypassed automatically.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';

  if (!window.WMS_API || !WMS_API.isAuthed()) {
    // Auth-gated like every other admin page; api.js dispatches the session
    // banner on its own when a 401 occurs mid-session.
    return;
  }

  const $ = (s, root = document) => root.querySelector(s);
  const $$ = (s, root = document) => Array.from(root.querySelectorAll(s));

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  function toast(kind, msg) {
    const t = window.WMS && window.WMS.toast;
    if (!t) return;
    if (kind === 'err') t.err(msg);
    else if (kind === 'info') t.info ? t.info(msg) : t.ok(msg);
    else t.ok(msg);
  }

  // ── Frozen local registry fallback ──────────────────────────────────────
  // Mirrors the SCO-53 settings contract. Every entry has:
  //   key, type, default, bounds, scope, edit_level, description, hot_reload, source
  // Type drives the input control rendered by renderRow().
  // NOTE: keep this in sync with backend/wms/services/settings_registry.py
  // once the backend stub gets fleshed out. The contract is identical so the
  // swap will be transparent.
  const LOCAL_REGISTRY = {
    inventory: [
      { key: 'inventory.aging_bucket_days', type: 'list[int]', default: [30, 60, 90],
        bounds: { each_min: 1, each_max: 3650, len_min: 1, len_max: 6, ascending: true },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-49',
        description: 'Aging buckets used for the Inventory KPI tile and aging report.' },
      { key: 'inventory.expiring_soon_days', type: 'int', default: 7,
        bounds: { min: 0, max: 365 },
        scope: 'site', edit_level: 3, hot_reload: true, source: 'SCO-49',
        description: 'Days-to-expiry threshold for the "expiring soon" KPI.' },
      { key: 'inventory.adjust_large_threshold', type: 'int', default: 100,
        bounds: { min: 1, max: 1000000 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-49',
        description: 'Adjustments with |delta| above this require Lvl 4+ to commit.' },
      { key: 'inventory.kpi_cache_ttl_sec', type: 'int', default: 300,
        bounds: { min: 0, max: 3600 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-49',
        description: 'KPI cache TTL; saving this clears the cache immediately.' },
      { key: 'inventory.search_limit_max', type: 'int', default: 200,
        bounds: { min: 1, max: 1000 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-49',
        description: 'Hard cap on /inventory/lots ?limit= per request.' },
    ],
    quality: [
      { key: 'quality.hold_escalation_days', type: 'list[int]', default: [14, 21, 30],
        bounds: { each_min: 1, each_max: 365, len_min: 1, len_max: 6, ascending: true },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-50',
        description: 'Age buckets for hold escalation badges (green / yellow / orange / red).' },
      { key: 'quality.supplier_perf_window_days', type: 'int', default: 90,
        bounds: { min: 7, max: 365 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-50',
        description: 'Rolling window for supplier defect % + trend comparison.' },
      { key: 'quality.destroy_requires_level', type: 'int', default: 4,
        bounds: { min: 3, max: 5 },
        scope: 'global', edit_level: 5, hot_reload: true, source: 'SCO-50',
        description: 'Minimum permission level to choose "destroy" on a QA hold.' },
    ],
    production: [
      { key: 'production.yield_variance_threshold', type: 'float', default: 0.01,
        bounds: { min: 0, max: 1 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-51',
        description: 'Yield variance above this emits production.yield_variance_high.' },
      { key: 'production.shortage_override_requires_level', type: 'int', default: 4,
        bounds: { min: 3, max: 5 },
        scope: 'global', edit_level: 5, hot_reload: true, source: 'SCO-51',
        description: 'Minimum level to override a shortage during work order start.' },
      { key: 'production.recipe_edit_requires_level', type: 'int', default: 3,
        bounds: { min: 2, max: 5 },
        scope: 'global', edit_level: 5, hot_reload: true, source: 'SCO-51',
        description: 'Minimum level to edit a locked recipe (creates a version bump).' },
      { key: 'production.fefo_threshold_days', type: 'int', default: 7,
        bounds: { min: 0, max: 365 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-51',
        description: 'FEFO horizon for preflight reservation ordering.' },
    ],
    reports: [
      { key: 'reports.cache_ttl_sec', type: 'int', default: 300,
        bounds: { min: 0, max: 3600 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-52',
        description: 'Report cache TTL; ?refresh=1 always bypasses regardless.' },
      { key: 'reports.csv_max_rows', type: 'int', default: 50000,
        bounds: { min: 100, max: 500000 },
        scope: 'global', edit_level: 5, hot_reload: true, source: 'SCO-52',
        description: 'Hard cap on CSV export rows; protects worker memory.' },
      { key: 'reports.date_range_max_days', type: 'int', default: 365,
        bounds: { min: 1, max: 3650 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-52',
        description: 'Maximum window for any report query; longer ranges return 400.' },
      { key: 'reports.outlier_threshold', type: 'float', default: 0.20,
        bounds: { min: 0.01, max: 1 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-52',
        description: 'Per-user picks/hour deviation flagged in both directions.' },
      { key: 'reports.genealogy_max_depth', type: 'int', default: 25,
        bounds: { min: 1, max: 200 },
        scope: 'global', edit_level: 5, hot_reload: true, source: 'SCO-52',
        description: 'Recursive genealogy walk depth limit (cycle protection).' },
    ],
    auth: [
      { key: 'auth.token_ttl_min', type: 'int', default: 480,
        bounds: { min: 5, max: 10080 },
        scope: 'global', edit_level: 5, hot_reload: false, source: 'env→registry',
        description: 'JWT access-token TTL in minutes. Shortening emits audit L-5.',
        note: 'Currently env-only — promote to settings table per SETTINGS_REGISTRY.md' },
      { key: 'auth.mfa.require_mfa', type: 'bool', default: false,
        bounds: null,
        scope: 'role', edit_level: 5, hot_reload: true, source: 'password_policies table',
        description: 'Per-role MFA requirement. Already DB-driven via /admin/policy/password — surfaced here for visibility.' },
      { key: 'auth.password_policy.min_length', type: 'int', default: 12,
        bounds: { min: 8, max: 64 },
        scope: 'global', edit_level: 5, hot_reload: true, source: 'password_policies table',
        description: 'Minimum password length. Existing endpoint: PUT /admin/policy/password.' },
      { key: 'auth.password_policy.require_complexity', type: 'bool', default: true,
        bounds: null,
        scope: 'global', edit_level: 5, hot_reload: true, source: 'password_policies table',
        description: 'Require mix of upper/lower/digit/symbol classes.' },
    ],
    uploads: [
      { key: 'uploads.max_avatar_bytes', type: 'int', default: 2097152,
        bounds: { min: 65536, max: 10485760 },
        scope: 'global', edit_level: 5, hot_reload: false, source: 'env→registry',
        description: 'Per-file cap for avatar uploads (bytes). Currently env-only.' },
      { key: 'uploads.max_avatar_dimension', type: 'int', default: 2048,
        bounds: { min: 128, max: 8192 },
        scope: 'global', edit_level: 5, hot_reload: false, source: 'env→registry',
        description: 'Max pixel dimension on either axis post-Pillow resize.' },
      { key: 'system.body_size_limit_bytes', type: 'int', default: 1048576,
        bounds: { min: 65536, max: 10485760 },
        scope: 'global', edit_level: 5, hot_reload: false, source: 'env→registry',
        description: 'JSON body cap enforced by BodySizeLimitMiddleware.' },
    ],
    system: [
      { key: 'system.site_offline', type: 'bool', default: false,
        bounds: null,
        scope: 'site', edit_level: 4, hot_reload: true, source: 'sites.is_online',
        description: 'Take this site offline. Min 60s cooldown between toggles. Invalidates all tokens for the site.',
        action: 'site-toggle' },
      { key: 'system.environment_banner', type: 'enum', default: 'none',
        bounds: { values: ['none', 'dev', 'staging', 'preview'] },
        scope: 'global', edit_level: 5, hot_reload: true, source: 'TODO',
        description: 'Optional environment ribbon shown at the top of every page (none = production).' },
    ],
    branding: [
      { key: 'branding.logo_url', type: 'upload', default: null,
        bounds: { max_bytes: 524288, max_dim: 1024, formats: ['png', 'svg', 'webp'] },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-53 (promoted from localStorage)',
        description: 'Per-site logo. Served from /uploads/branding/{site_id}.{ext}.',
        action: 'logo-upload' },
      { key: 'branding.display_name', type: 'str', default: '',
        bounds: { min_len: 0, max_len: 64 },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-53',
        description: 'Display name shown in topbar/login (overrides "WMS").' },
      { key: 'branding.accent_color', type: 'enum', default: 'amber',
        bounds: { values: ['amber', 'teal', 'magenta', 'lime'] },
        scope: 'site', edit_level: 4, hot_reload: true, source: 'SCO-53',
        description: 'Accent token swap (--amber alias). Restricted palette to keep contrast.' },
    ],
  };

  // ── State ───────────────────────────────────────────────────────────────
  let activeModule = 'inventory';
  let currentValues = {};      // key → resolved value at active scope
  let dirty = new Set();        // keys with unsaved edits
  const user = WMS_API.getUser ? WMS_API.getUser() : null;
  const permLevel = (user && user.permission_level) || 0;

  // ── Permission-gate banner ─────────────────────────────────────────────
  function renderGateBanner() {
    const banner = $('#gate-banner');
    if (!banner) return;
    if (permLevel < 4) {
      banner.hidden = false;
      banner.classList.add('gate-banner--warn');
      banner.textContent = `▴ Read-only view — your permission level (${permLevel}) is below the Lvl 4 minimum required to edit any setting. Server will refuse any PUT.`;
    } else {
      banner.hidden = false;
      banner.classList.remove('gate-banner--warn');
      banner.textContent = `▴ Backend wiring pending — values shown below are registry defaults from SETTINGS_REGISTRY.md. Endpoints documented in backend/wms/api/v1/settings.py.`;
    }
  }

  // ── Module switcher ────────────────────────────────────────────────────
  function bindNav() {
    $$('.settings-nav-item').forEach((btn) => {
      btn.addEventListener('click', () => {
        activeModule = btn.dataset.module;
        $$('.settings-nav-item').forEach((b) => b.classList.toggle(
          'settings-nav-item--active', b === btn
        ));
        renderPanel();
      });
    });
  }

  // ── Value coercion ─────────────────────────────────────────────────────
  // The server validates authoritatively; we coerce client-side only to give
  // immediate feedback. Bounds violations here just disable Save — the actual
  // 400 from the server (when wired) will surface in a toast.
  function coerce(entry, raw) {
    switch (entry.type) {
      case 'int':
        return raw === '' ? null : Number.parseInt(raw, 10);
      case 'float':
        return raw === '' ? null : Number.parseFloat(raw);
      case 'bool':
        return raw === 'true' || raw === true;
      case 'enum':
      case 'str':
        return String(raw);
      case 'list[int]':
        if (Array.isArray(raw)) return raw;
        return String(raw).split(',').map((s) => Number.parseInt(s.trim(), 10)).filter((n) => !Number.isNaN(n));
      default:
        return raw;
    }
  }

  function isValid(entry, value) {
    if (value === null || value === undefined) return entry.default === null;
    const b = entry.bounds;
    if (!b) return true;
    if (entry.type === 'int' || entry.type === 'float') {
      if (b.min !== undefined && value < b.min) return false;
      if (b.max !== undefined && value > b.max) return false;
      return Number.isFinite(value);
    }
    if (entry.type === 'enum') {
      return b.values && b.values.includes(value);
    }
    if (entry.type === 'str') {
      const len = String(value).length;
      if (b.min_len !== undefined && len < b.min_len) return false;
      if (b.max_len !== undefined && len > b.max_len) return false;
      return true;
    }
    if (entry.type === 'list[int]') {
      if (!Array.isArray(value)) return false;
      if (b.len_min && value.length < b.len_min) return false;
      if (b.len_max && value.length > b.len_max) return false;
      if (b.each_min !== undefined && value.some((n) => n < b.each_min)) return false;
      if (b.each_max !== undefined && value.some((n) => n > b.each_max)) return false;
      if (b.ascending) {
        for (let i = 1; i < value.length; i++) {
          if (value[i] <= value[i - 1]) return false;
        }
      }
      return true;
    }
    return true;
  }

  // ── Row rendering ──────────────────────────────────────────────────────
  function inputFor(entry) {
    const current = currentValues[entry.key] ?? entry.default;
    const canEdit = permLevel >= entry.edit_level;
    const dis = canEdit ? '' : 'disabled';
    const title = canEdit ? '' : `title="Requires Lvl ${entry.edit_level}+ to edit"`;
    switch (entry.type) {
      case 'bool':
        return `
          <select class="input" data-key="${escapeHtml(entry.key)}" ${dis} ${title}>
            <option value="false" ${!current ? 'selected' : ''}>Off</option>
            <option value="true"  ${current ? 'selected' : ''}>On</option>
          </select>`;
      case 'enum':
        return `
          <select class="input" data-key="${escapeHtml(entry.key)}" ${dis} ${title}>
            ${(entry.bounds.values || []).map((v) => `
              <option value="${escapeHtml(v)}" ${String(current) === String(v) ? 'selected' : ''}>${escapeHtml(v)}</option>
            `).join('')}
          </select>`;
      case 'list[int]':
        return `
          <input class="input input--mono" type="text" data-key="${escapeHtml(entry.key)}"
                 value="${escapeHtml(Array.isArray(current) ? current.join(', ') : '')}"
                 placeholder="e.g. 30, 60, 90"
                 ${dis} ${title} />`;
      case 'upload':
        return `
          <button class="btn btn--ghost btn--sm" data-key="${escapeHtml(entry.key)}" data-action="upload" ${dis} ${title}>
            Upload…
          </button>`;
      case 'int':
      case 'float':
        return `
          <input class="input input--mono" type="number" data-key="${escapeHtml(entry.key)}"
                 value="${current ?? ''}"
                 ${entry.bounds && entry.bounds.min !== undefined ? `min="${entry.bounds.min}"` : ''}
                 ${entry.bounds && entry.bounds.max !== undefined ? `max="${entry.bounds.max}"` : ''}
                 ${entry.type === 'float' ? 'step="0.01"' : 'step="1"'}
                 ${dis} ${title} />`;
      case 'str':
      default:
        return `
          <input class="input input--mono" type="text" data-key="${escapeHtml(entry.key)}"
                 value="${escapeHtml(current ?? '')}"
                 ${dis} ${title} />`;
    }
  }

  function boundsLabel(entry) {
    const b = entry.bounds;
    if (!b) return '';
    if (entry.type === 'int' || entry.type === 'float') {
      return `${b.min ?? '−∞'} … ${b.max ?? '∞'}`;
    }
    if (entry.type === 'enum') return (b.values || []).join(' / ');
    if (entry.type === 'list[int]') {
      return `${b.len_min}–${b.len_max} ints, ${b.each_min}–${b.each_max}${b.ascending ? ', ascending' : ''}`;
    }
    if (entry.type === 'str') return `${b.min_len ?? 0}–${b.max_len ?? '∞'} chars`;
    if (entry.type === 'upload') return `≤${Math.round(b.max_bytes / 1024)} KB, ${b.formats.join('/')}`;
    return '';
  }

  function renderRow(entry) {
    const canEdit = permLevel >= entry.edit_level;
    return `
      <div class="settings-row" data-key="${escapeHtml(entry.key)}" data-dirty="false">
        <div class="settings-row-meta">
          <span class="settings-key">${escapeHtml(entry.key)}</span>
          <span class="settings-desc">${escapeHtml(entry.description)}</span>
          <span class="settings-bounds">
            ${escapeHtml(entry.type)}
            ${boundsLabel(entry) ? `· ${escapeHtml(boundsLabel(entry))}` : ''}
            · scope <em>${escapeHtml(entry.scope)}</em>
            · Lvl ${entry.edit_level}+
            ${entry.hot_reload ? '· hot-reload' : '· restart required'}
            ${entry.source ? `· src ${escapeHtml(entry.source)}` : ''}
          </span>
          ${entry.note ? `<span class="settings-bounds" style="color: var(--amber);">▴ ${escapeHtml(entry.note)}</span>` : ''}
        </div>
        <div class="settings-value">
          ${inputFor(entry)}
        </div>
        <div class="settings-bounds" style="text-align: center;">
          default <code style="font-family: var(--font-mono);">${escapeHtml(
            Array.isArray(entry.default) ? entry.default.join(', ') : String(entry.default)
          )}</code>
        </div>
        <div class="settings-actions">
          <button class="btn btn--ghost btn--xs" data-act="save" data-key="${escapeHtml(entry.key)}"
                  ${canEdit ? 'disabled' : 'disabled'} title="Backend wiring pending (PUT /admin/settings/{key})">
            Save
          </button>
          <button class="btn btn--ghost btn--xs" data-act="reset" data-key="${escapeHtml(entry.key)}"
                  ${canEdit ? 'disabled' : 'disabled'} title="Backend wiring pending (POST /admin/settings/{key}/reset)">
            Reset
          </button>
        </div>
      </div>`;
  }

  function renderBrandingPanel(entries) {
    // Branding gets a custom layout because it includes a file upload + live
    // preview. The other entries (display_name, accent_color) still render as
    // standard rows underneath.
    const logoEntry = entries.find((e) => e.action === 'logo-upload');
    const others = entries.filter((e) => e.action !== 'logo-upload');
    return `
      <div class="branding-grid">
        <div>
          <div class="logo-preview" id="logo-preview">
            <span>No logo set</span>
          </div>
          <p class="settings-bounds" style="margin-top: var(--space-2);">
            ${escapeHtml(logoEntry ? logoEntry.description : '')}
          </p>
          <button class="btn btn--ghost btn--sm" disabled title="Backend wiring pending (POST /admin/settings/branding/logo)">
            Upload logo…
          </button>
        </div>
        <div>
          ${others.map(renderRow).join('')}
        </div>
      </div>
    `;
  }

  // ── Panel render ───────────────────────────────────────────────────────
  function renderPanel() {
    const titles = {
      inventory: 'Inventory', quality: 'Quality', production: 'Production',
      reports: 'Reports & Metrics', auth: 'Auth & MFA', uploads: 'Uploads',
      system: 'System', branding: 'Branding',
    };
    const panelTitle = $('#panel-title');
    const panelMeta = $('#panel-meta');
    const panelBody = $('#panel-body');
    if (!panelTitle || !panelBody) return;

    panelTitle.innerHTML = `<em>${escapeHtml(titles[activeModule] || activeModule)}</em>`;
    const entries = LOCAL_REGISTRY[activeModule] || [];
    panelMeta.textContent = `${entries.length} setting${entries.length === 1 ? '' : 's'} · scope: site (effective)`;

    if (entries.length === 0) {
      panelBody.innerHTML = `
        <div class="empty-state">
          <span class="empty-state-glyph">∅</span>
          <span class="empty-state-text">No settings registered for this module yet.</span>
          <span class="empty-state-sub">Add an entry to <code>settings_registry.py</code> + <code>SETTINGS_REGISTRY.md</code> in the same commit.</span>
        </div>`;
      return;
    }

    if (activeModule === 'branding') {
      panelBody.innerHTML = renderBrandingPanel(entries);
    } else {
      panelBody.innerHTML = entries.map(renderRow).join('');
    }

    bindRowEvents(entries);
  }

  // ── Row event wiring (dirty-tracking only — Save/Reset are disabled until
  //    backend lands; this code is structured so that flipping the disabled
  //    flag is the only thing that needs to change). ──────────────────────
  function bindRowEvents(entries) {
    const byKey = new Map(entries.map((e) => [e.key, e]));
    $$('.settings-row .input').forEach((input) => {
      input.addEventListener('input', () => {
        const key = input.dataset.key;
        const entry = byKey.get(key);
        if (!entry) return;
        const raw = input.value;
        const coerced = coerce(entry, raw);
        const valid = isValid(entry, coerced);
        const row = input.closest('.settings-row');
        if (!row) return;
        const isChanged = JSON.stringify(coerced) !== JSON.stringify(currentValues[key] ?? entry.default);
        row.dataset.dirty = String(isChanged);
        if (isChanged) dirty.add(key); else dirty.delete(key);
        // Once backend lands, swap the disabled flag below to !valid:
        // const saveBtn = row.querySelector('[data-act="save"]');
        // if (saveBtn) saveBtn.disabled = !valid || !isChanged;
        if (!valid) {
          input.style.borderColor = 'var(--signal-crit)';
          input.title = 'Out of bounds — server will reject';
        } else {
          input.style.borderColor = '';
          input.title = '';
        }
      });
    });

    // Save / Reset are currently disabled (backend not wired). Wire-up plan:
    // - data-act="save"  → PUT /admin/settings/{key} { scope_type, scope_value, value }
    //   On 200: clear dirty flag, toast "saved", re-fetch value (in case server
    //   coerced). On 400: surface server error inline near the input.
    // - data-act="reset" → POST /admin/settings/{key}/reset { scope_type, scope_value }
    //   On 200: clear input to entry.default, clear dirty flag, toast "reset to default".
    // Both should call settings.changed via the server's audit hook automatically.
  }

  // ── Boot ────────────────────────────────────────────────────────────────
  async function boot() {
    renderGateBanner();
    bindNav();
    renderPanel();

    // Try the live registry; fall through to local fallback on any failure.
    // When the backend lands, this block becomes the primary source.
    try {
      const live = await WMS_API.request('/admin/settings/registry').catch(() => null);
      if (live && live.modules) {
        // TODO(SCO-53): merge live.modules into LOCAL_REGISTRY, then re-render.
        // For now we never reach here — the endpoint 404s and we keep the
        // local fallback. Logging only so dev tools show the swap point.
        console.info('[settings] live registry available — swap to live source');
      } else {
        const banner = $('#gate-banner');
        if (banner && !banner.hidden) {
          // Banner already populated by renderGateBanner; nothing else to do.
        }
      }
    } catch (e) {
      // Expected today — endpoint not mounted. Stay on the local fallback.
      console.debug('[settings] no live registry endpoint, using local fallback', e);
    }

    // Effective-scope label — for now mirrors the user's home site.
    const eff = $('#effective-scope');
    if (eff && user) {
      eff.textContent = `site:${user.site_id || '—'}`;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
