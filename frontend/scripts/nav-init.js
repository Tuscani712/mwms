/* ═══════════════════════════════════════════════════════════════════════════
   Top-nav partial — single source of truth for the primary nav strip.

   To add a page to the nav, append to NAV_ITEMS below. To keep a sub-page
   (e.g. admin-orgmeta.html) highlighting its parent tab, give the parent an
   `activeFor` regex tested against the current pathname.

   Mount point: any element with id="topnav-mount" — typically `<nav class="topnav" id="topnav-mount">`.
   ─────────────────────────────────────────────────────────────────────────── */

(() => {
  'use strict';

  const NAV_ITEMS = [
    { href: 'index.html',      label: 'Dashboard'  },
    { href: 'inventory.html',  label: 'Inventory'  },
    { href: 'receiving.html',  label: 'Receiving'  },
    { href: 'shipping.html',   label: 'Shipping'   },
    { href: 'production.html', label: 'Production' },
    { href: 'quality.html',    label: 'Quality'    },
    { href: 'reports.html',    label: 'Reports'    },
    // Admin tab stays active for every admin-* sub-page (users, orgmeta, sites, branding)
    { href: 'admin.html',      label: 'Admin', activeFor: /^(admin(?:-[a-z]+)?\.html|users\.html)$/ },
  ];

  function currentPage() {
    const last = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
    // Treat bare site root (/) as the dashboard.
    return last || 'index.html';
  }

  function render() {
    const mount = document.getElementById('topnav-mount');
    if (!mount) return;
    const current = currentPage();
    mount.innerHTML = NAV_ITEMS.map((item) => {
      const isActive = item.activeFor
        ? item.activeFor.test(current)
        : current === item.href.toLowerCase();
      const cls = 'topnav-item' + (isActive ? ' topnav-item--active' : '');
      return `<a href="${item.href}" class="${cls}">${item.label}</a>`;
    }).join('');
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', render);
  } else {
    render();
  }
})();
