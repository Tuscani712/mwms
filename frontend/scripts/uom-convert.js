// SCO-144 — Mass-unit conversion helpers (frontend mirror of
// backend/wms/services/uom_conversion.py).
//
// Canonical mass unit = LB. All <input>s tied to mass quantities should
// route their value through WMS.uom.toCanonical() before submitting to
// the backend, which always speaks canonical LB.
//
// If you edit MASS_FACTORS_PER_LB here, edit the Python mirror too — the
// pytest suite and the JS test suite each check the canonical factor
// (0.45359237 KG/LB) so drift fails loudly on either side.
(function (global) {
  'use strict';

  const MASS_FACTORS_PER_LB = Object.freeze({
    LB: 1.0,
    KG: 0.45359237,
    OZ: 16.0,
    G: 453.59237,
    MG: 453592.37,
  });

  const MASS_UNITS = Object.freeze(Object.keys(MASS_FACTORS_PER_LB));
  const CANONICAL_MASS_UOM = 'LB';

  function normalizeUnit(u) {
    return (u || '').toString().toUpperCase();
  }

  function isMassUnit(u) {
    return MASS_FACTORS_PER_LB[normalizeUnit(u)] !== undefined;
  }

  function toCanonical(value, unit) {
    const u = normalizeUnit(unit);
    const f = MASS_FACTORS_PER_LB[u];
    if (f === undefined) {
      throw new Error(`Unknown mass unit "${unit}" in toCanonical`);
    }
    return Number(value) / f;
  }

  function fromCanonical(valueLb, unit) {
    const u = normalizeUnit(unit);
    const f = MASS_FACTORS_PER_LB[u];
    if (f === undefined) {
      throw new Error(`Unknown mass unit "${unit}" in fromCanonical`);
    }
    return Number(valueLb) * f;
  }

  function convert(value, fromUnit, toUnit) {
    if (normalizeUnit(fromUnit) === normalizeUnit(toUnit)) return Number(value);
    return fromCanonical(toCanonical(value, fromUnit), toUnit);
  }

  // Format a canonical-LB value with an optional secondary unit tooltip-friendly string.
  // e.g. formatWithSecondary(500, 'KG', 1) → '500 LB (≈226.8 KG)'
  function formatWithSecondary(valueLb, secondaryUnit, decimals = 2) {
    const v = Number(valueLb);
    if (!Number.isFinite(v)) return '—';
    if (!isMassUnit(secondaryUnit) || normalizeUnit(secondaryUnit) === CANONICAL_MASS_UOM) {
      return `${v.toFixed(decimals)} LB`;
    }
    const secondary = fromCanonical(v, secondaryUnit);
    return `${v.toFixed(decimals)} LB (≈${secondary.toFixed(decimals)} ${normalizeUnit(secondaryUnit)})`;
  }

  // Build the {value, label} list for a confirmModal select field.
  function massUnitOptions(defaultUnit) {
    const d = normalizeUnit(defaultUnit) || CANONICAL_MASS_UOM;
    // Put the default first so confirmModal selects it without extra wiring.
    const sorted = [d, ...MASS_UNITS.filter((u) => u !== d)];
    return sorted.map((u) => ({ value: u, label: u }));
  }

  global.WMS = global.WMS || {};
  global.WMS.uom = {
    MASS_UNITS,
    MASS_FACTORS_PER_LB,
    CANONICAL_MASS_UOM,
    isMassUnit,
    toCanonical,
    fromCanonical,
    convert,
    formatWithSecondary,
    massUnitOptions,
  };
})(typeof window !== 'undefined' ? window : globalThis);
