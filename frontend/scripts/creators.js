/* ═══════════════════════════════════════════════════════════════════════════
   Shared "Create X" handlers — Option B (Receive → Ship walkthrough enablers)
   Three buttons live on three pages:
     #btn-new-sku    (inventory.html)
     #btn-new-asn    (receiving.html)
     #btn-new-order  (shipping.html)
   Each is wired here via event delegation so the host scripts stay focused.
   ─────────────────────────────────────────────────────────────────────────── */

(() => {
  'use strict';
  if (!window.WMS_API || !window.confirmModal) return;

  async function fetchSKUs() {
    try { return await WMS_API.request('/inventory/skus'); }
    catch (_) { return []; }
  }

  function alertMsg(title, body) {
    return confirmModal.alert({ title, body });
  }

  async function createSKU() {
    const result = await confirmModal.form({
      title: 'Add SKU',
      body: 'A SKU defines a stock-keeping unit available in this site. Code must be unique site-wide.',
      fields: [
        { name: 'code', label: 'SKU code', required: true, placeholder: 'PROD-001' },
        { name: 'description', label: 'Description', required: true, placeholder: 'Finished product' },
        { name: 'uom', label: 'Unit of measure', value: 'EA' },
        { name: 'unit_weight_kg', label: 'Unit weight (kg)', type: 'number', value: '1.0' },
        { name: 'requires_qc', label: 'Requires QC at receipt', type: 'select',
          options: [{ value: 'false', label: 'No' }, { value: 'true', label: 'Yes' }],
          value: 'false',
        },
        { name: 'shelf_life_days', label: 'Shelf life (days, optional)', type: 'number', value: '' },
        { name: 'reorder_point', label: 'Reorder point', type: 'number', value: '0' },
        { name: 'safety_stock', label: 'Safety stock', type: 'number', value: '0' },
      ],
      confirmLabel: 'Create SKU',
    });
    if (!result) return;
    try {
      await WMS_API.request('/inventory/skus', {
        method: 'POST',
        body: {
          code: result.code.trim(),
          description: result.description.trim(),
          uom: result.uom || 'EA',
          unit_weight_kg: Number(result.unit_weight_kg) || 1.0,
          requires_qc: result.requires_qc === 'true',
          shelf_life_days: result.shelf_life_days ? Number(result.shelf_life_days) : null,
          reorder_point: Number(result.reorder_point) || 0,
          safety_stock: Number(result.safety_stock) || 0,
        },
      });
      window.location.reload();
    } catch (e) {
      alertMsg('Create failed', e.message || 'Unknown error');
    }
  }

  async function createASN() {
    const skus = await fetchSKUs();
    if (!skus.length) {
      return alertMsg('No SKUs', 'Create at least one SKU on the Inventory page before opening an ASN.');
    }
    // Step 1 — header.
    const header = await confirmModal.form({
      title: 'Create ASN — step 1 of 2',
      body: 'Advance Shipping Notice header. Pick a unique code + supplier.',
      fields: [
        { name: 'asn_code', label: 'ASN code', required: true, placeholder: 'ASN-2026-0001' },
        { name: 'supplier', label: 'Supplier', required: true, placeholder: 'Northwind Beef Co.' },
      ],
      confirmLabel: 'Next: line item',
    });
    if (!header) return;
    // Step 2 — single line (MVP). Multi-line ASN is a follow-up.
    const line = await confirmModal.form({
      title: 'Create ASN — step 2 of 2',
      body: 'Add an inbound line item. Additional lines via repeat-create or future multi-row editor.',
      fields: [
        { name: 'sku_id', label: 'SKU', type: 'select',
          options: skus.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.description}` })),
          required: true,
        },
        { name: 'expected_qty', label: 'Expected qty', type: 'number', value: '1', required: true },
      ],
      confirmLabel: 'Create ASN',
    });
    if (!line) return;
    try {
      await WMS_API.request('/receiving/asns', {
        method: 'POST',
        body: {
          asn_code: header.asn_code.trim(),
          supplier: header.supplier.trim(),
          lines: [{
            sku_id: Number(line.sku_id),
            expected_qty: Number(line.expected_qty),
          }],
        },
      });
      window.location.reload();
    } catch (e) {
      alertMsg('Create failed', e.message || 'Unknown error');
    }
  }

  async function createOrder() {
    const skus = await fetchSKUs();
    if (!skus.length) {
      return alertMsg('No SKUs', 'Create at least one SKU on the Inventory page before opening an order.');
    }
    const header = await confirmModal.form({
      title: 'Create order — step 1 of 2',
      body: 'Sales order header. Code must be unique.',
      fields: [
        { name: 'order_code', label: 'Order code', required: true, placeholder: 'SO-2026-0001' },
        { name: 'customer', label: 'Customer', required: true, placeholder: 'Heartland Grocers' },
        { name: 'priority', label: 'Priority', type: 'select',
          options: [
            { value: 'low', label: 'Low' },
            { value: 'normal', label: 'Normal' },
            { value: 'high', label: 'High' },
          ],
          value: 'normal',
        },
      ],
      confirmLabel: 'Next: line item',
    });
    if (!header) return;
    const line = await confirmModal.form({
      title: 'Create order — step 2 of 2',
      body: 'Add an order line. Additional lines via repeat-create or future multi-row editor.',
      fields: [
        { name: 'sku_id', label: 'SKU', type: 'select',
          options: skus.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.description}` })),
          required: true,
        },
        { name: 'qty_ordered', label: 'Qty ordered', type: 'number', value: '1', required: true },
        { name: 'fefo_required', label: 'FEFO required', type: 'select',
          options: [{ value: 'false', label: 'No' }, { value: 'true', label: 'Yes' }],
          value: 'false',
        },
      ],
      confirmLabel: 'Create order',
    });
    if (!line) return;
    try {
      await WMS_API.request('/shipping/orders', {
        method: 'POST',
        body: {
          order_code: header.order_code.trim(),
          customer: header.customer.trim(),
          priority: header.priority || 'normal',
          lines: [{
            sku_id: Number(line.sku_id),
            qty_ordered: Number(line.qty_ordered),
            fefo_required: line.fefo_required === 'true',
          }],
        },
      });
      window.location.reload();
    } catch (e) {
      alertMsg('Create failed', e.message || 'Unknown error');
    }
  }

  document.addEventListener('click', (e) => {
    const t = e.target.closest('#btn-new-sku, #btn-new-asn, #btn-new-order');
    if (!t) return;
    if (t.id === 'btn-new-sku') return createSKU();
    if (t.id === 'btn-new-asn') return createASN();
    if (t.id === 'btn-new-order') return createOrder();
  });
})();
