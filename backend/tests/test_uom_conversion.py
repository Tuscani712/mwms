"""Tests for the mass-unit conversion utility (SCO-144).

Pure-function tests. No DB, no fixtures — bugs here propagate everywhere,
so the math must be airtight on its own.

If you edit MASS_FACTORS_PER_LB in wms/services/uom_conversion.py, the
canonical-factor test below catches drift from the NIST value (0.45359237
KG per LB). Keep these in sync with the frontend mirror in
frontend/scripts/uom-convert.js.
"""
from __future__ import annotations

import math

import pytest

from wms.services import uom_conversion as uc
from wms.services.production import (
    ConversionImpossibleError,
    _convert_uom,
)


def test_canonical_factor_is_nist_exact():
    # If this fails, the frontend mirror needs the same fix.
    assert uc.MASS_FACTORS_PER_LB["KG"] == 0.45359237
    assert uc.CANONICAL_MASS_UOM == "LB"


@pytest.mark.parametrize("unit", ["LB", "KG", "OZ", "G", "MG"])
def test_round_trip_identity(unit: str):
    # Converting and back must return the original value within float epsilon.
    for v in (0.001, 1.0, 50.0, 50_000.0):
        lb = uc.to_canonical(v, unit)
        back = uc.from_canonical(lb, unit)
        assert math.isclose(back, v, rel_tol=1e-12), (unit, v, back)


def test_kg_to_lb_known_value():
    # 1000 KG → 2204.6226218487757 LB (NIST exact).
    lb = uc.to_canonical(1000.0, "KG")
    assert math.isclose(lb, 2204.6226218487757, rel_tol=1e-12)


def test_boundary_precision_small_and_large():
    # 0.001 KG round-trips at full precision; 50000 KG too.
    for v in (0.001, 50_000.0):
        assert math.isclose(
            uc.convert(uc.convert(v, "KG", "LB"), "LB", "KG"), v, rel_tol=1e-12
        )


def test_unknown_unit_raises():
    with pytest.raises(uc.UnitConversionError):
        uc.to_canonical(1.0, "BAG")
    with pytest.raises(uc.UnitConversionError):
        uc.from_canonical(1.0, "L")


def test_is_mass_unit_table():
    for u in ("LB", "KG", "OZ", "G", "MG", "lb", "kg"):
        assert uc.is_mass_unit(u)
    for u in ("EA", "PACK", "BAG", "L", "", None):
        assert not uc.is_mass_unit(u)


def test_convert_same_unit_is_passthrough():
    # No float drift when source == target.
    assert uc.convert(123.456, "LB", "LB") == 123.456
    assert uc.convert(123.456, "kg", "KG") == 123.456


def test_production_convert_uom_mass_to_mass():
    # The previously-stub _convert_uom now handles mass↔mass and routes
    # through the conversion utility. Recipes in KG against LB lots no
    # longer break preflight.
    class _SKU:
        code = "GARLIC-PWD"
    assert math.isclose(
        _convert_uom(from_uom="KG", to_uom="LB", qty=1.0, sku=_SKU()),
        2.2046226218487757,
        rel_tol=1e-12,
    )


def test_production_convert_uom_volume_still_raises():
    # Volume conversions are still SCO-51 v2 work; ensure we haven't
    # accidentally widened the implementation.
    class _SKU:
        code = "OIL-CANOLA"
    with pytest.raises(ConversionImpossibleError):
        _convert_uom(from_uom="L", to_uom="GAL", qty=1.0, sku=_SKU())
