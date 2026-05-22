/* ═══════════════════════════════════════════════════════════════════════════
   Admin · Sites — multi-site directory CRUD (SCO-54)
   ─────────────────────────────────────────────────────────────────────────
   Drives /api/v1/sites read-and-write. Write endpoints require the caller to
   be on the master site (server enforces); this UI also hides destructive
   controls when the caller can't use them, so non-master admins get a clean
   read-only view instead of confusing 403s.
   ═══════════════════════════════════════════════════════════════════════════ */

(() => {
  'use strict';
  if (!window.WMS_API || !WMS_API.isAuthed()) return;

  const $ = (s) => document.querySelector(s);
  const grid = $('#sites-grid');
  const metaEl = $('#sites-meta');
  const gateEl = $('#gate-banner');
  const addSection = $('#add-section');

  // Track whether the caller is on the master site. Used to gate UI controls.
  // Server enforces independently; this is for UX clarity, not security.
  let callerCanWrite = false;
  let masterSiteId = null;

  // Migrated to shared WMS.toast (scripts/toast.js). The old #toast div in the
  // HTML is now unused and will be cleaned up in a follow-up.
  function toast(kind, msg) {
    if (kind === 'err') return window.WMS?.toast?.err(msg);
    return window.WMS?.toast?.ok(msg);
  }

  function escapeHtml(s) {
    return String(s ?? '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[c]));
  }

  // ── SCO-118 lifecycle scaffolding state ─────────────────────────────
  // Today's binary is_online maps onto two of the six canonical lifecycle
  // states ('online' / 'offline'). The other four ('provisioning',
  // 'degraded', 'decommissioned', 'archived') aren't reachable until the
  // backend schema grows a lifecycle column — keep them in the rendered UI
  // (with stubbed counts/pills) so the wire-up is a swap, not a rewrite.
  let activeFilter = 'all';
  let lastLoadedSites = [];

  function deriveLifecycle(site) {
    // Future: read site.lifecycle directly. Today it's a function of is_online.
    return site.is_online ? 'online' : 'offline';
  }

  function deriveEnrollmentStatus(_site) {
    // No backend column yet — every site renders as "enrolled" so the pill
    // demonstrates intent without lying. When the schema lands, return one of
    // 'pending' | 'enrolled' | 'revoked' | 'expired' from site.enrollment.status.
    return 'enrolled';
  }

  function lifecyclePill(state) {
    const labels = {
      online: 'Online', offline: 'Offline', provisioning: 'Provisioning',
      degraded: 'Degraded', decommissioned: 'Decommissioned', archived: 'Archived',
    };
    return `<span class="pill pill--lifecycle-${state}">${labels[state] || state}</span>`;
  }

  function enrollmentPill(state) {
    const labels = { pending: 'Pending enroll', enrolled: 'Enrolled', revoked: 'Revoked', expired: 'Expired' };
    return `<span class="pill pill--enroll-${state}" title="Enrollment status (placeholder — backend wiring pending)">${labels[state] || state}</span>`;
  }

  function siteCard(site, counts) {
    const writable = callerCanWrite && !site.is_master;
    const offlineToggleLabel = site.is_online ? 'Take offline' : 'Bring online';
    const lifecycle = deriveLifecycle(site);
    const enrollment = deriveEnrollmentStatus(site);
    // Pending-action tooltips help admins understand why a button is disabled.
    const pendingHint = 'Backend wiring pending — UI scaffolded for SCO-118';
    return `
      <article class="site-card" data-master="${site.is_master}" data-online="${site.is_online}"
               data-lifecycle="${lifecycle}" data-id="${escapeHtml(site.id)}">
        <div class="site-card-head">
          <h3 class="site-name">${escapeHtml(site.name)}</h3>
          <span class="site-id">${escapeHtml(site.id)}</span>
        </div>
        <div class="site-pills">
          ${site.is_master ? '<span class="pill" style="color: var(--amber); border-color: var(--amber);">Master</span>' : ''}
          ${lifecyclePill(lifecycle)}
          ${enrollmentPill(enrollment)}
          <span class="pill">${escapeHtml(site.build_version)}</span>
        </div>
        <div class="site-meta">
          <span class="site-meta-label">City</span><span>${escapeHtml(site.city)}</span>
          <span class="site-meta-label">TZ</span><span>${escapeHtml(counts ? counts.timezone : '')}</span>
          <span class="site-meta-label">Address</span><span style="font-family: var(--font-mono); color: var(--ink-tertiary);">—</span>
          <span class="site-meta-label">Last enrolled</span><span style="font-family: var(--font-mono); color: var(--ink-tertiary);">—</span>
        </div>
        <div class="site-counts">
          <span class="site-count"><strong>${counts ? counts.user_count : '—'}</strong> users</span>
          <span class="site-count"><strong>${counts ? counts.department_count : '—'}</strong> departments</span>
        </div>
        <div class="site-actions">
          ${callerCanWrite && !site.is_master ? `<button class="btn btn--ghost btn--xs" data-act="edit" data-id="${escapeHtml(site.id)}">Edit</button>` : ''}
          ${callerCanWrite && !site.is_master ? `<button class="btn btn--ghost btn--xs" data-act="toggle" data-id="${escapeHtml(site.id)}">${offlineToggleLabel}</button>` : ''}
          ${writable ? `<button class="btn btn--ghost btn--xs btn--pending" data-act="decommission" data-id="${escapeHtml(site.id)}" disabled title="${pendingHint}">Decommission</button>` : ''}
          ${writable ? `<button class="btn btn--ghost btn--xs btn--pending" data-act="archive" data-id="${escapeHtml(site.id)}" disabled title="${pendingHint} — enabled once site is decommissioned">Archive</button>` : ''}
          ${writable ? `<button class="btn btn--ghost btn--xs" data-act="hard-delete" data-id="${escapeHtml(site.id)}" style="color: var(--signal-crit);" title="Hard delete — only allowed when site has zero users + departments">Hard delete</button>` : ''}
          ${writable ? `<button class="btn btn--ghost btn--xs btn--pending" data-act="rotate-key" data-id="${escapeHtml(site.id)}" disabled title="${pendingHint}">Rotate key</button>` : ''}
          ${writable ? `<button class="btn btn--ghost btn--xs btn--pending" data-act="revoke" data-id="${escapeHtml(site.id)}" disabled title="${pendingHint}" style="color: var(--signal-crit);">Revoke</button>` : ''}
          <button class="btn btn--ghost btn--xs" data-act="open-drawer" data-id="${escapeHtml(site.id)}" style="margin-left: auto;">Detail ▸</button>
        </div>
      </article>
    `;
  }

  // ── Filter chips ────────────────────────────────────────────────────
  function updateFilterCounts(sites) {
    const counts = { all: sites.length, online: 0, offline: 0, decommissioned: 0, archived: 0 };
    sites.forEach((s) => { counts[deriveLifecycle(s)] = (counts[deriveLifecycle(s)] || 0) + 1; });
    document.querySelectorAll('[data-bind^="filter-count-"]').forEach((el) => {
      const key = el.dataset.bind.replace('filter-count-', '');
      el.textContent = counts[key] != null ? counts[key] : '—';
    });
  }

  function applyFilter() {
    document.querySelectorAll('#sites-grid .site-card').forEach((card) => {
      const lc = card.dataset.lifecycle;
      const show = activeFilter === 'all' || activeFilter === lc;
      card.style.display = show ? '' : 'none';
    });
  }

  function setFilter(name) {
    activeFilter = name;
    document.querySelectorAll('#lifecycle-filters .filter-chip').forEach((c) => {
      c.setAttribute('aria-pressed', String(c.dataset.filter === name));
    });
    applyFilter();
  }

  // ── Enrollment key generation (client-side scaffolding) ─────────────
  function generateEnrollmentKey() {
    // 256-bit entropy → 32 chars URL-safe base64 (no padding). Real key
    // will come from the backend; this is purely visible groundwork.
    const bytes = new Uint8Array(24);
    crypto.getRandomValues(bytes);
    return btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
  }

  function buildInstallCommand(siteId, key) {
    // Placeholder MCS URL — once configured, will come from a /api/v1/mcs/config
    // endpoint or the page's own origin if the dashboard IS the MCS.
    const mcsUrl = window.location.origin || 'https://mcs.example.com';
    return `curl -fsSL ${mcsUrl}/install.sh | SITE_ID=${siteId} ENROLLMENT_KEY=${key} MCS_URL=${mcsUrl} bash`;
  }

  function showEnrollmentKeyBlock(siteId, key) {
    const block = $('#enrollment-key-block');
    const display = $('#enrollment-key-display');
    const cmd = $('#install-cmd-display');
    display.value = key;
    cmd.textContent = buildInstallCommand(siteId, key);
    block.hidden = false;
    block.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    setTimeout(() => display.select(), 50);
  }

  async function copyToClipboard(text, btn, okLabel = 'Copied ✓') {
    try {
      await navigator.clipboard.writeText(text);
      const orig = btn.textContent;
      btn.textContent = okLabel;
      setTimeout(() => { btn.textContent = orig; }, 1400);
    } catch (_) {
      toast('err', 'Clipboard unavailable — select and copy manually.');
    }
  }

  // ── Drawer ──────────────────────────────────────────────────────────
  function openDrawer(siteId) {
    const site = lastLoadedSites.find((s) => s.id === siteId);
    if (!site) return;
    $('#drawer-title').textContent = `${site.name} · ${site.id}`;
    $('#drawer-summary').innerHTML = `
      <div>Lifecycle: ${lifecyclePill(deriveLifecycle(site))}</div>
      <div style="margin-top: 4px;">Enrollment: ${enrollmentPill(deriveEnrollmentStatus(site))}</div>
      <div style="margin-top: 4px;">Build: ${escapeHtml(site.build_version)}</div>
    `;
    $('#lifecycle-drawer').dataset.open = 'true';
    $('#lifecycle-drawer').setAttribute('aria-hidden', 'false');
    $('#drawer-backdrop').dataset.open = 'true';
  }

  function closeDrawer() {
    $('#lifecycle-drawer').dataset.open = 'false';
    $('#lifecycle-drawer').setAttribute('aria-hidden', 'true');
    $('#drawer-backdrop').dataset.open = 'false';
  }

  async function load() {
    grid.innerHTML = '';
    metaEl.textContent = 'Loading…';
    try {
      const sites = await WMS_API.sites();
      const master = sites.find((s) => s.is_master);
      masterSiteId = master ? master.id : null;
      const me = WMS_API.getUser ? WMS_API.getUser() : null;
      callerCanWrite = Boolean(me && masterSiteId && me.site_id === masterSiteId && (me.permission_level || 0) >= 5);

      gateEl.style.display = callerCanWrite ? 'none' : 'block';
      addSection.hidden = !callerCanWrite;

      // Fetch detail (counts + timezone) in parallel; non-fatal per-card.
      const details = await Promise.all(
        sites.map((s) => WMS_API.sitesAdmin.get(s.id).catch(() => null))
      );
      const onlineCount = sites.filter((s) => s.is_online).length;
      metaEl.textContent = `${sites.length} sites · ${onlineCount} online · master = ${masterSiteId || '—'}`;
      grid.innerHTML = sites.map((s, i) => siteCard(s, details[i])).join('');
      lastLoadedSites = sites;
      updateFilterCounts(sites);
      applyFilter();
    } catch (e) {
      metaEl.textContent = 'Failed to load';
      toast('err', `Sites: ${e.message}`);
    }
  }

  $('#site-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const payload = {
      id: $('#site-id').value.trim().toUpperCase(),
      name: $('#site-name').value.trim(),
      city: $('#site-city').value.trim(),
      timezone: $('#site-tz').value.trim() || 'America/Chicago',
      build_version: $('#site-build').value.trim() || 'v0.1.0',
      is_online: $('#site-online').checked,
      is_master: false,
    };
    try {
      await WMS_API.sitesAdmin.create(payload);
      // Scaffold: generate + show enrollment key client-side. Real backend
      // response will include { enrollment: { key, expires_at } } — swap out
      // this local generator at wire-up time. The "shown once" UX stays.
      const key = generateEnrollmentKey();
      showEnrollmentKeyBlock(payload.id, key);
      toast('ok', `Site "${payload.id}" created — copy the enrollment key now`);
      ['site-id', 'site-name', 'site-city'].forEach((id) => { $('#' + id).value = ''; });
      load();
    } catch (err) {
      toast('err', err.message);
    }
  });

  // Enrollment key block interactions (post-create)
  $('#enrollment-key-copy').addEventListener('click', (e) =>
    copyToClipboard($('#enrollment-key-display').value, e.currentTarget, 'Key copied ✓')
  );
  $('#install-cmd-copy').addEventListener('click', (e) =>
    copyToClipboard($('#install-cmd-display').textContent, e.currentTarget, 'Command copied ✓')
  );
  $('#enrollment-key-dismiss').addEventListener('click', () => {
    $('#enrollment-key-block').hidden = true;
    $('#enrollment-key-display').value = '';
    $('#install-cmd-display').textContent = '';
  });

  // Filter chips
  document.getElementById('lifecycle-filters').addEventListener('click', (e) => {
    const chip = e.target.closest('.filter-chip:not([disabled])');
    if (!chip) return;
    setFilter(chip.dataset.filter);
  });

  // Archive section toggle
  $('#archive-toggle').addEventListener('click', () => {
    const sec = $('#archive-section');
    sec.dataset.open = sec.dataset.open === 'true' ? 'false' : 'true';
  });

  // Lifecycle drawer dismiss
  $('#drawer-close').addEventListener('click', closeDrawer);
  $('#drawer-backdrop').addEventListener('click', closeDrawer);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && $('#lifecycle-drawer').dataset.open === 'true') closeDrawer();
  });

  grid.addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const id = btn.dataset.id;
    const act = btn.dataset.act;
    try {
      if (act === 'toggle') {
        await WMS_API.sitesAdmin.toggleOnline(id);
        toast('ok', `Toggled ${id}`);
      } else if (act === 'hard-delete') {
        // Renamed from "delete"/"Archive" to make the destructive nature
        // explicit. Server still refuses if users/depts exist; this is the
        // path for sites that never went live.
        const confirmed = await confirmModal.typed({
          title: `Hard delete site "${id}"?`,
          body: 'Permanently removes the site row. Only allowed if no users or departments still reference it. For sites that went live, use Decommission → Archive instead (once wired).',
          confirmWord: id,
          confirmLabel: 'Hard delete',
        });
        if (!confirmed) return;
        await WMS_API.sitesAdmin.remove(id);
        toast('ok', `Hard-deleted ${id}`);
      } else if (act === 'edit') {
        const detail = await WMS_API.sitesAdmin.get(id);
        const result = await confirmModal.form({
          title: `Edit site "${id}"`,
          body: 'Update the site name and city. ID, timezone, and master/online status are managed elsewhere.',
          fields: [
            { name: 'name', label: 'Name', value: detail.name, required: true, placeholder: 'Northwind Dallas' },
            { name: 'city', label: 'City', value: detail.city, required: true, placeholder: 'Dallas, TX' },
          ],
          confirmLabel: 'Save changes',
        });
        if (!result) return;
        await WMS_API.sitesAdmin.update(id, { name: result.name, city: result.city });
        toast('ok', `Updated ${id}`);
      } else if (act === 'decommission') {
        // SCO-118.D scaffold — wiring pending. Soft-retire moves the site to
        // a read-only state and is reversible. Will live at:
        //   POST /api/v1/sites/{id}/decommission { reason }
        await confirmModal.alert({
          title: 'Decommission — wire-up pending',
          body: `This will eventually soft-retire site "${id}" (read-only, reversible). Backend endpoint POST /api/v1/sites/{id}/decommission has not landed yet.`,
        });
        return;
      } else if (act === 'archive') {
        // SCO-118.D scaffold — wiring pending. Only valid for decommissioned
        // sites. Will live at:
        //   POST /api/v1/sites/{id}/archive { reason }
        await confirmModal.alert({
          title: 'Archive — wire-up pending',
          body: `Archive moves a previously-decommissioned site to long-term storage. Backend endpoint POST /api/v1/sites/{id}/archive has not landed yet.`,
        });
        return;
      } else if (act === 'rotate-key') {
        // SCO-118.D scaffold — wiring pending. Issues new enrollment key,
        // invalidates the old one. Site can't recheckin until installer is
        // re-keyed.
        //   POST /api/v1/sites/{id}/enrollment/rotate
        //     → 200 { key, expires_at }  (shown once)
        await confirmModal.alert({
          title: 'Rotate enrollment key — wire-up pending',
          body: `Rotating issues a new key and invalidates the old one — the site will be unable to talk to MCS until the installer is re-keyed. Backend endpoint POST /api/v1/sites/{id}/enrollment/rotate has not landed yet.`,
          danger: true,
        });
        return;
      } else if (act === 'revoke') {
        // SCO-118.D scaffold — wiring pending. Immediately blocks the site's
        // MCS handshake.
        //   POST /api/v1/sites/{id}/enrollment/revoke
        await confirmModal.alert({
          title: 'Revoke enrollment — wire-up pending',
          body: `Revoking immediately disables the site's MCS handshake. The site stays in the directory but cannot push audit/health. Backend endpoint POST /api/v1/sites/{id}/enrollment/revoke has not landed yet.`,
          danger: true,
        });
        return;
      } else if (act === 'open-drawer') {
        openDrawer(id);
        return;
      }
      load();
    } catch (err) {
      toast('err', err.message);
    }
  });

  load();
})();
