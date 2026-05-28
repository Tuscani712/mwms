"""Mass-unit conversion (SCO-144).

Canonical mass unit: LB (pound). All mass-class quantities on the backend
are stored as LB regardless of how the operator entered them. The frontend
(scripts/uom-convert.js) mirrors this table so both sides agree to the bit.

Add a new mass unit by extending MASS_FACTORS_PER_LB only — every helper
derives from that single source.
"""
from __future__ import annotations

CANONICAL_MASS_UOM = "LB"

# How many of <unit> equal one LB. Derived from NIST exact conversions.
MASS_FACTORS_PER_LB: dict[str, float] = {
    "LB": 1.0,
    "KG": 0.45359237,            # 1 LB = 0.45359237 KG (exact)
    "OZ": 16.0,                  # 1 LB = 16 OZ (exact)
    "G":  453.59237,             # 1 LB = 453.59237 G
    "MG": 453592.37,             # 1 LB = 453592.37 MG
}

MASS_UNITS: frozenset[str] = frozenset(MASS_FACTORS_PER_LB)


class UnitConversionError(ValueError):
    """Raised when a unit is not in the mass conversion table."""

    def __init__(self, unit: str, *, side: str = "from"):
        super().__init__(
            f"Unknown mass unit {unit!r} on the {side} side of a conversion. "
            f"Supported: {sorted(MASS_UNITS)}"
        )
        self.unit = unit
        self.side = side


def is_mass_unit(unit: str | None) -> bool:
    """True iff `unit` is in the mass-class conversion table.

    Used by callers to decide whether a quantity needs LB-canonicalization
    or is already an opaque count (EA, PACK, ...).
    """
    if not unit:
        return False
    return unit.upper() in MASS_UNITS


def to_canonical(value: float, unit: str) -> float:
    """Convert a mass quantity from `unit` to canonical LB.

    1000 KG → 2204.6226218487757 LB.
    """
    u = (unit or "").upper()
    if u not in MASS_UNITS:
        raise UnitConversionError(unit, side="from")
    return value / MASS_FACTORS_PER_LB[u]


def from_canonical(value_lb: float, unit: str) -> float:
    """Convert canonical LB back into `unit`.

    Inverse of to_canonical. Used by display layers that want to show a
    lot's quantity in a non-canonical unit.
    """
    u = (unit or "").upper()
    if u not in MASS_UNITS:
        raise UnitConversionError(unit, side="to")
    return value_lb * MASS_FACTORS_PER_LB[u]


def convert(value: float, from_unit: str, to_unit: str) -> float:
    """Convert `value` from one mass unit to another via LB.

    Same-unit inputs are returned unchanged (no float drift).
    """
    if (from_unit or "").upper() == (to_unit or "").upper():
        return value
    return from_canonical(to_canonical(value, from_unit), to_unit)
