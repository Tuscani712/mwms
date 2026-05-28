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

  // SCO-143: SKU creation now captures the THREE-tier UoM model:
  //   - "Unit of measure" is the BASE / consumption unit (LB, EA, OZ).
  //   - "Purchase UoM" is what the SKU comes in from the supplier (BAG,
  //     PACK, CASE). Leave blank for SKUs purchased at base unit.
  //   - "Base per purchase unit" is the conversion factor (e.g., 50 lb per
  //     bag, 8 each per pack).
  // The receipt service applies the conversion at lot creation so the
  // operator types what the truck driver brings ("10 bags") and inventory
  // stocks the canonical equivalent ("500 LB").
  async function createSKU() {
    const result = await confirmModal.form({
      title: 'Add SKU',
      body: 'A SKU defines a stock-keeping unit available in this site. Code must be unique site-wide.',
      fields: [
        { name: 'code', label: 'SKU code', required: true, placeholder: 'PROD-001' },
        { name: 'description', label: 'Description', required: true, placeholder: 'Finished product' },
        { name: 'uom', label: 'Base unit (recipes + inventory)', value: 'EA', placeholder: 'LB / EA / OZ' },
        { name: 'purchase_uom', label: 'Purchase unit (optional)', value: '', placeholder: 'BAG / PACK / CASE — blank if purchased at base unit' },
        { name: 'base_per_purchase_unit', label: 'Base units per purchase unit', type: 'number', value: '1.0', placeholder: 'e.g. 50.0 lb per bag, 8 each per pack' },
        { name: 'unit_weight_kg', label: 'Unit weight (kg, per base unit)', type: 'number', value: '1.0' },
        { name: 'requires_qc', label: 'Requires QC at receipt', type: 'select',
          options: [{ value: 'false', label: 'No' }, { value: 'true', label: 'Yes' }],
          value: 'false',
        },
        { name: 'shelf_life_days', label: 'Shelf life (days, optional)', type: 'number', value: '' },
        { name: 'reorder_point', label: 'Reorder point (in base UoM)', type: 'number', value: '0' },
        { name: 'safety_stock', label: 'Safety stock (in base UoM)', type: 'number', value: '0' },
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
          uom: (result.uom || 'EA').toUpperCase(),
          purchase_uom: (result.purchase_uom || '').trim().toUpperCase(),
          base_per_purchase_unit: Number(result.base_per_purchase_unit) || 1.0,
          unit_weight_kg: Number(result.unit_weight_kg) || 1.0,
          requires_qc: result.requires_qc === 'true',
          shelf_life_days: result.shelf_life_days ? Number(result.shelf_life_days) : null,
          reorder_point: Number(result.reorder_point) || 0,
          safety_stock: Number(result.safety_stock) || 0,
        },
      });
      // Bust the inventory page's SKU typeahead cache so the new row appears immediately.
      window.WMS_SKU_CACHE?.invalidate();
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
    if (!window.WMS?.multiLineModal) {
      return alertMsg('Modal unavailable', 'multi-line-modal.js failed to load.');
    }
    // SCO-143: surface purchase UoM next to the SKU code so the operator
    // sees they're entering "bag count" vs "each count" before typing the
    // qty. SKUs without a packaging unit show their base UoM.
    const skuOptions = skus.map((s) => {
      const unitLabel = (s.purchase_uom && s.purchase_uom.trim())
        ? `${s.purchase_uom} of ${s.base_per_purchase_unit} ${s.uom}`
        : s.uom;
      return { value: String(s.id), label: `${s.code} · ${s.description} · qty in ${unitLabel}` };
    });
    const result = await window.WMS.multiLineModal({
      title: 'Create ASN',
      body: (
        'One supplier truck may carry multiple SKUs. Add a line per SKU on this shipment. ' +
        'Qty is in the SKU\'s PURCHASE unit (e.g., bags, packs, cases) — the system converts ' +
        'to stock units at receipt time based on the SKU\'s base_per_purchase_unit.'
      ),
      headerFields: [
        { name: 'asn_code', label: 'ASN code', required: true, placeholder: 'ASN-2026-0001' },
        { name: 'supplier', label: 'Supplier', required: true, placeholder: 'Northwind Beef Co.' },
      ],
      lineFields: [
        { name: 'sku_id', type: 'select', options: skuOptions, required: true },
        { name: 'expected_qty', type: 'number', value: '1', required: true, placeholder: 'Qty (purchase units)' },
      ],
      addLineLabel: 'Add SKU line',
      confirmLabel: 'Create ASN',
    });
    if (!result) return;
    try {
      await WMS_API.request('/receiving/asns', {
        method: 'POST',
        body: {
          asn_code: result.header.asn_code.trim(),
          supplier: result.header.supplier.trim(),
          lines: result.lines.map((ln) => ({
            sku_id: Number(ln.sku_id),
            expected_qty: Number(ln.expected_qty),
          })),
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
    if (!window.WMS?.multiLineModal) {
      return alertMsg('Modal unavailable', 'multi-line-modal.js failed to load.');
    }
    const skuOptions = skus.map((s) => ({ value: String(s.id), label: `${s.code} · ${s.description}` }));
    const result = await window.WMS.multiLineModal({
      title: 'Create order',
      body: 'Sales order header + line items. One order can ship multiple SKUs.',
      headerFields: [
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
      lineFields: [
        { name: 'sku_id', type: 'select', options: skuOptions, required: true },
        { name: 'qty_ordered', type: 'number', value: '1', required: true, placeholder: 'Qty' },
      ],
      addLineLabel: 'Add SKU line',
      confirmLabel: 'Create order',
    });
    if (!result) return;
    try {
      await WMS_API.request('/shipping/orders', {
        method: 'POST',
        body: {
          order_code: result.header.order_code.trim(),
          customer: result.header.customer.trim(),
          priority: result.header.priority || 'normal',
          lines: result.lines.map((ln) => ({
            sku_id: Number(ln.sku_id),
            qty_ordered: Number(ln.qty_ordered),
            fefo_required: false,
          })),
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
