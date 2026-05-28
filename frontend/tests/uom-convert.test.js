// SCO-144 — node smoke test for frontend mass-unit conversion.
// Run with: node frontend/tests/uom-convert.test.js
//
// Mirrors backend/tests/test_uom_conversion.py. If either side drifts
// off the NIST factor (0.45359237 KG/LB) the corresponding test fails
// loudly here or in pytest.
//
// No test runner — just assert + process.exitCode. Keeps frontend's
// zero-dependency posture intact.
'use strict';

const path = require('node:path');
const vm = require('node:vm');
const fs = require('node:fs');
const assert = require('node:assert/strict');

// Load uom-convert.js into a sandbox so we can read WMS.uom without a DOM.
const scriptPath = path.join(__dirname, '..', 'scripts', 'uom-convert.js');
const source = fs.readFileSync(scriptPath, 'utf8');
const sandbox = { window: {} };
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const uom = sandbox.window.WMS && sandbox.window.WMS.uom;
if (!uom) {
  console.error('FAIL: WMS.uom not exposed by uom-convert.js');
  process.exit(1);
}

let failures = 0;
function it(name, fn) {
  try {
    fn();
    console.log(`  ✓ ${name}`);
  } catch (err) {
    failures++;
    console.log(`  ✗ ${name}`);
    console.log(`    ${err.message}`);
  }
}

console.log('uom-convert.js');

it('canonical factor matches NIST (0.45359237 KG per LB)', () => {
  assert.equal(uom.MASS_FACTORS_PER_LB.KG, 0.45359237);
  assert.equal(uom.CANONICAL_MASS_UOM, 'LB');
});

it('isMassUnit classifies known units', () => {
  for (const u of ['LB', 'KG', 'OZ', 'G', 'MG', 'lb', 'kg']) {
    assert.ok(uom.isMassUnit(u), `expected ${u} mass`);
  }
  for (const u of ['EA', 'PACK', 'BAG', 'L', '', null, undefined]) {
    assert.ok(!uom.isMassUnit(u), `expected ${u} non-mass`);
  }
});

it('1000 KG → 2204.6226... LB (NIST exact)', () => {
  const lb = uom.toCanonical(1000, 'KG');
  assert.ok(Math.abs(lb - 2204.6226218487757) < 1e-9, `got ${lb}`);
});

it('round-trips each mass unit at multiple magnitudes', () => {
  for (const u of uom.MASS_UNITS) {
    for (const v of [0.001, 1, 50, 50000]) {
      const back = uom.fromCanonical(uom.toCanonical(v, u), u);
      assert.ok(Math.abs(back - v) / v < 1e-12, `${u} ${v} -> ${back}`);
    }
  }
});

it('convert() is a passthrough on same-unit (no float drift)', () => {
  assert.equal(uom.convert(123.456, 'LB', 'LB'), 123.456);
  assert.equal(uom.convert(123.456, 'kg', 'KG'), 123.456);
});

it('massUnitOptions puts the default first', () => {
  const opts = uom.massUnitOptions('KG');
  assert.equal(opts[0].value, 'KG');
  assert.equal(opts.length, uom.MASS_UNITS.length);
});

it('formatWithSecondary renders the tooltip-friendly string', () => {
  const s = uom.formatWithSecondary(500, 'KG', 1);
  assert.match(s, /^500\.0 LB \(≈226\.8 KG\)$/);
});

it('unknown unit throws', () => {
  assert.throws(() => uom.toCanonical(1, 'BAG'));
  assert.throws(() => uom.fromCanonical(1, 'L'));
});

if (failures > 0) {
  console.log(`\n${failures} failure(s)`);
  process.exit(1);
}
console.log('\nall passed');
