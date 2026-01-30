"""
Unit number normalization rules for Chicago addresses.

Common patterns observed:
- "1R", "2R" -> Rear units (unit=1, position=R)
- "1F", "2F" -> Front units (unit=1, position=F)
- "1W", "2W", "3E" -> Directional position (West, East side of building)
- "1FL", "2FL" -> Floor numbers (unit=1, type=Floor)
- "1A", "1B", "2A" -> Lettered sub-units
- "G", "G1" -> Garden level
- "LL" -> Lower level
- "PH", "PH1" -> Penthouse
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedUnit:
    number: Optional[str]
    unit_type: str
    position_indicator: Optional[str]  # R=Rear, F=Front, W=West, E=East, etc.


def parse_unit(unit_str: str, existing_unit_type: str = None) -> ParsedUnit:
    """
    Parse a unit string into components.

    Examples:
        "1R" -> ParsedUnit(number="1", unit_type="Unit", position_indicator="Rear")
        "3w" -> ParsedUnit(number="3", unit_type="Unit", position_indicator="West")
        "1fl" -> ParsedUnit(number="1", unit_type="Floor", position_indicator=None)
        "G" -> ParsedUnit(number=None, unit_type="Garden", position_indicator=None)
        "PH1" -> ParsedUnit(number="1", unit_type="PH", position_indicator=None)
        "3307" -> ParsedUnit(number="3307", unit_type=existing_unit_type or "Unit", position_indicator=None)
    """
    if not unit_str or str(unit_str).lower() in ('nan', 'none', ''):
        return ParsedUnit(None, existing_unit_type or "Unit", None)

    unit_str = str(unit_str).strip()
    unit_upper = unit_str.upper()

    # Floor patterns: "1FL", "2FL", "1FLR", "FLOOR 1"
    floor_match = re.match(r'^(\d+)\s*(FL|FLR|FLOOR)$', unit_upper)
    if floor_match:
        return ParsedUnit(floor_match.group(1), "Floor", None)

    # Penthouse patterns
    ph_match = re.match(r'^(PH|PENTHOUSE)\s*(\d*)$', unit_upper)
    if ph_match:
        num = ph_match.group(2) if ph_match.group(2) else None
        return ParsedUnit(num, "PH", None)

    # Garden level
    garden_match = re.match(r'^(G|GARDEN|GDN)\s*(\d*)$', unit_upper)
    if garden_match:
        num = garden_match.group(2) if garden_match.group(2) else None
        return ParsedUnit(num, "Garden", None)

    # Lower level
    if unit_upper in ('LL', 'LOWER', 'LWR'):
        return ParsedUnit(None, "Lower", None)

    # Basement
    if unit_upper in ('BSMT', 'BASEMENT', 'B'):
        return ParsedUnit(None, "Bsmt", None)

    # Position indicators: 1R, 2F, 3W, 4E (number + single letter position)
    position_match = re.match(r'^(\d+)\s*([RFWE])$', unit_upper)
    if position_match:
        position_map = {'R': 'Rear', 'F': 'Front', 'W': 'West', 'E': 'East'}
        return ParsedUnit(
            position_match.group(1),
            "Unit",
            position_map.get(position_match.group(2), position_match.group(2))
        )

    # Lettered units: 1A, 1B, 2A (keep as-is, they're valid unit numbers)
    letter_match = re.match(r'^(\d+[A-Z])$', unit_upper)
    if letter_match:
        return ParsedUnit(unit_upper, existing_unit_type or "Unit", None)

    # Plain numbers
    if unit_upper.isdigit():
        return ParsedUnit(unit_upper, existing_unit_type or "Unit", None)

    # Default: keep original
    return ParsedUnit(unit_str.upper(), existing_unit_type or "Unit", None)


def format_unit_for_display(parsed: ParsedUnit) -> str:
    """
    Format a parsed unit for the canonical address string.

    Examples:
        ParsedUnit("1", "Unit", "Rear") -> "Unit 1 (Rear)"
        ParsedUnit("1", "Floor", None) -> "Floor 1"
        ParsedUnit("3307", "Apt", None) -> "Apt 3307"
    """
    parts = []
    if parsed.unit_type:
        parts.append(parsed.unit_type)
    if parsed.number:
        parts.append(parsed.number)
    result = " ".join(parts)
    if parsed.position_indicator:
        result += f" ({parsed.position_indicator})"
    return result
