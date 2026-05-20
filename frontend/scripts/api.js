/* ═══════════════════════════════════════════════════════════════════════════
   WMS API Client — auth-aware fetch wrapper
   ═══════════════════════════════════════════════════════════════════════════ */

window.WMS_API = (() => {
  'use strict';

  const BASE = window.WMS_API_BASE || 'http://localhost:8775/api/v1';
  const TOKEN_KEY = 'wms.token';
  const USER_KEY = 'wms.user';

  function getToken() {
    return localStorage.getItem(TOKEN_KEY);
  }

  function setSession({ access_token, site_id, role, full_name, permission_level }) {
    localStorage.setItem(TOKEN_KEY, access_token);
    localStorage.setItem(USER_KEY, JSON.stringify({ site_id, role, full_name, permission_level }));
  }

  function getUser() {
    const raw = localStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  }

  function clear() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  async function request(path, { method = 'GET', body = null, auth = true } = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (auth) {
      const token = getToken();
      if (token) headers['Authorization'] = `Bearer ${token}`;
    }
    const opts = { method, headers };
    if (body !== null) opts.body = JSON.stringify(body);

    const res = await fetch(`${BASE}${path}`, opts);
    if (res.status === 401) {
      clear();
      // Soft-fail: callers may handle this and fall back to mock display
      throw new Error('Unauthorized');
    }
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`API ${res.status}: ${text}`);
    }
    if (res.status === 204) return null;
    return res.json();
  }

  return {
    BASE,
    getToken,
    setSession,
    getUser,
    clear,
    request,
    isAuthed: () => Boolean(getToken()),
    login: (employee_code, password, site_id) =>
      request('/auth/login', { method: 'POST', body: { employee_code, password, site_id }, auth: false }),
    me: () => request('/auth/me'),
    sites: () => request('/sites', { auth: false }),
    health: () => request('/health', { auth: false }),
    ping: () => request('/health/ping', { auth: false }),
    receiving: {
      inbound: () => request('/receiving/inbound'),
      checkIn: (asn_id, dock_door) =>
        request('/receiving/check-in', { method: 'POST', body: { asn_id, dock_door } }),
      createReceipt: (payload) =>
        request('/receiving/receipts', { method: 'POST', body: payload }),
      putaway: (asn_id) => request(`/receiving/putaway-suggestions/${asn_id}`),
    },
    inventory: {
      lots: (params = {}) => {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
          if (v === undefined || v === null || v === '') return;
          qs.append(k, String(v));
        });
        const tail = qs.toString();
        return request(`/inventory/lots${tail ? `?${tail}` : ''}`);
      },
      sku: (sku_code) => request(`/inventory/sku/${encodeURIComponent(sku_code)}`),
      kpis: (refresh = false) =>
        request(`/inventory/kpis${refresh ? '?refresh=true' : ''}`),
      adjust: (lot_id, delta, reason) =>
        request('/inventory/adjust', {
          method: 'POST',
          body: { lot_id, delta, reason },
        }),
      belowSafetyStock: () => request('/inventory/below-safety-stock'),
    },
    shipping: {
      orders: (status) => request(`/shipping/orders${status ? `?status=${status}` : ''}`),
      consolidation: (order_id, line_id) =>
        request(`/shipping/consolidation/${order_id}/${line_id}`),
      assignPicks: (payload) =>
        request('/shipping/picks', { method: 'POST', body: payload }),
      truckLoad: (shipment_id, order_id) =>
        request('/shipping/truck-load', { method: 'POST', body: { shipment_id, order_id } }),
      packingSlip: (order_id) => request(`/shipping/packing-slip/${order_id}`),
    },
    orgmeta: {
      // SCO-81: org-metadata picker + CRUD endpoints. site_id is optional
      // (server defaults to caller's site for create; list-without-site_id
      // returns own-site for depts/shifts and own-site+globals for roles).
      roles: (params = {}) => {
        const qs = new URLSearchParams();
        if (params.site_id) qs.set('site_id', params.site_id);
        if (params.include_globals === false) qs.set('include_globals', 'false');
        const t = qs.toString();
        return request(`/admin/roles${t ? `?${t}` : ''}`);
      },
      createRole: (payload) =>
        request('/admin/roles', { method: 'POST', body: payload }),
      updateRole: (id, payload) =>
        request(`/admin/roles/${id}`, { method: 'PUT', body: payload }),
      deactivateRole: (id) =>
        request(`/admin/roles/${id}`, { method: 'DELETE' }),

      departments: (site_id) =>
        request(`/admin/departments${site_id ? `?site_id=${site_id}` : ''}`),
      createDepartment: (payload) =>
        request('/admin/departments', { method: 'POST', body: payload }),
      updateDepartment: (id, payload) =>
        request(`/admin/departments/${id}`, { method: 'PUT', body: payload }),
      deactivateDepartment: (id) =>
        request(`/admin/departments/${id}`, { method: 'DELETE' }),

      shifts: (site_id) =>
        request(`/admin/shifts${site_id ? `?site_id=${site_id}` : ''}`),
      createShift: (payload) =>
        request('/admin/shifts', { method: 'POST', body: payload }),
      updateShift: (id, payload) =>
        request(`/admin/shifts/${id}`, { method: 'PUT', body: payload }),
      deactivateShift: (id) =>
        request(`/admin/shifts/${id}`, { method: 'DELETE' }),
    },
  };
})();
