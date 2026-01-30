"""
Address normalization module.

Normalizes address components for consistent comparison and duplicate detection.
"""

import re
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from .unit_patterns import parse_unit


@dataclass
class NormalizedAddress:
    id: str
    house_number: str
    pre_direction: Optional[str]
    street_name: str
    post_direction: Optional[str]
    street_type: Optional[str]
    unit: Optional[str]
    unit_type: Optional[str]
    unit_position: Optional[str]
    city: str
    state: str
    zip_code: str
    lat: Optional[float]
    lon: Optional[float]
    external_source: Optional[str]

    # Computed fields
    canonical_street: str = ""
    canonical_full: str = ""
    match_key_exact: str = ""
    match_key_no_unit: str = ""

    is_po_box: bool = False
    normalization_warnings: List[str] = field(default_factory=list)


class AddressNormalizer:
    """Normalizes addresses for consistent comparison."""

    # Street type mappings
    STREET_TYPES = {
        'ST': 'Street', 'ST.': 'Street', 'STR': 'Street', 'STREET': 'Street', 'STRT': 'Street',
        'AV': 'Avenue', 'AVE': 'Avenue', 'AVE.': 'Avenue', 'AVEN': 'Avenue', 'AVENU': 'Avenue', 'AVENUE': 'Avenue',
        'DR': 'Drive', 'DR.': 'Drive', 'DRIV': 'Drive', 'DRIVE': 'Drive', 'DRV': 'Drive',
        'RD': 'Road', 'RD.': 'Road', 'ROAD': 'Road',
        'BLVD': 'Boulevard', 'BLVD.': 'Boulevard', 'BLV': 'Boulevard', 'BOUL': 'Boulevard', 'BOULEVARD': 'Boulevard',
        'CT': 'Court', 'CT.': 'Court', 'COURT': 'Court',
        'CIR': 'Circle', 'CIRC': 'Circle', 'CIRCL': 'Circle', 'CIRCLE': 'Circle', 'CRCL': 'Circle',
        'LA': 'Lane', 'LN': 'Lane', 'LN.': 'Lane', 'LANE': 'Lane',
        'PL': 'Place', 'PL.': 'Place', 'PLACE': 'Place',
        'PKWY': 'Parkway', 'PKWAY': 'Parkway', 'PKY': 'Parkway', 'PARKWAY': 'Parkway',
        'TER': 'Terrace', 'TERR': 'Terrace', 'TERRACE': 'Terrace',
        'WAY': 'Way', 'WY': 'Way',
        'HWY': 'Highway', 'HIGHWAY': 'Highway', 'HIWAY': 'Highway',
        'TRL': 'Trail', 'TRAIL': 'Trail', 'TRLS': 'Trail',
        'SQ': 'Square', 'SQR': 'Square', 'SQRE': 'Square', 'SQU': 'Square', 'SQUARE': 'Square',
        'EXPY': 'Expressway', 'EXPW': 'Expressway', 'EXPRESSWAY': 'Expressway',
        'PATH': 'Path', 'WALK': 'Walk',
        'ALY': 'Alley', 'ALLEY': 'Alley',
        'PT': 'Point', 'POINT': 'Point',
    }

    # Direction mappings
    DIRECTIONS = {
        'N': 'N', 'NO': 'N', 'NORTH': 'N',
        'S': 'S', 'SO': 'S', 'SOUTH': 'S',
        'E': 'E', 'EAST': 'E',
        'W': 'W', 'WEST': 'W',
        'NE': 'NE', 'NORTHEAST': 'NE', 'NORTH EAST': 'NE',
        'NW': 'NW', 'NORTHWEST': 'NW', 'NORTH WEST': 'NW',
        'SE': 'SE', 'SOUTHEAST': 'SE', 'SOUTH EAST': 'SE',
        'SW': 'SW', 'SOUTHWEST': 'SW', 'SOUTH WEST': 'SW',
    }

    # Unit type mappings
    UNIT_TYPES = {
        '#': 'Unit', 'NO': 'Unit', 'NO.': 'Unit', 'NUM': 'Unit', 'UNIT': 'Unit', 'UN': 'Unit',
        'APT': 'Apt', 'APT.': 'Apt', 'APARTMENT': 'Apt', 'APARTMNT': 'Apt',
        'STE': 'Ste', 'STE.': 'Ste', 'SUITE': 'Ste',
        'FL': 'Floor', 'FLR': 'Floor', 'FLOOR': 'Floor',
        'RM': 'Rm', 'RM.': 'Rm', 'ROOM': 'Rm',
        'BLDG': 'Bldg', 'BLDG.': 'Bldg', 'BUILDING': 'Bldg',
        'BSMT': 'Bsmt', 'BASEMENT': 'Bsmt',
        'DEPT': 'Dept', 'DEPARTMENT': 'Dept',
        'LBBY': 'Lobby', 'LOBBY': 'Lobby',
        'LOT': 'Lot',
        'OFC': 'Ofc', 'OFFICE': 'Ofc',
        'PH': 'PH', 'PENTHOUSE': 'PH',
        'PIER': 'Pier',
        'REAR': 'Rear', 'R': 'Rear',
        'SPC': 'Space', 'SPACE': 'Space',
        'STOP': 'Stop',
        'TRLR': 'Trlr', 'TRAILER': 'Trlr',
        'UPPR': 'Upper', 'UPPER': 'Upper',
        'LOWR': 'Lower', 'LOWER': 'Lower',
        'FRNT': 'Front', 'FRONT': 'Front',
    }

    def normalize(self, row: Dict[str, Any]) -> NormalizedAddress:
        """Normalize an address row."""
        warnings = []

        # Check for PO Box
        address_str = self._safe_str(row.get('address', '')) or self._safe_str(row.get('raw_address', ''))
        if self._is_po_box(address_str):
            return self._normalize_po_box(row)

        # Normalize each component
        house_number = self._normalize_house_number(row.get('house_number'))
        pre_dir = self._normalize_direction(row.get('pre_direction'))
        street_name = self._normalize_street_name(row.get('street_name'))
        post_dir = self._normalize_direction(row.get('post_direction'))
        street_type, st_warning = self._normalize_street_type(row.get('street_type'))
        if st_warning:
            warnings.append(st_warning)

        # Handle unit
        unit, unit_type, unit_position = self._normalize_unit(
            row.get('unit'),
            row.get('unit_type')
        )

        city = self._normalize_city(row.get('city'))
        state = 'IL'
        zip_code = self._normalize_zip(row.get('zip'))

        # Get geocode info
        lat = self._safe_float(row.get('lat'))
        lon = self._safe_float(row.get('lon'))

        # Build canonical strings
        canonical_street = self._build_canonical_street(
            house_number, pre_dir, street_name, post_dir, street_type
        )
        canonical_full = self._build_canonical_full(
            canonical_street, unit, unit_type, unit_position, city, state, zip_code
        )

        # Build match keys
        match_key_exact = self._build_match_key(
            zip_code, house_number, pre_dir, street_name, post_dir,
            street_type, unit
        )
        match_key_no_unit = self._build_match_key(
            zip_code, house_number, pre_dir, street_name, post_dir,
            street_type, None
        )

        return NormalizedAddress(
            id=str(row.get('id', '')),
            house_number=house_number,
            pre_direction=pre_dir,
            street_name=street_name,
            post_direction=post_dir,
            street_type=street_type,
            unit=unit,
            unit_type=unit_type,
            unit_position=unit_position,
            city=city,
            state=state,
            zip_code=zip_code,
            lat=lat,
            lon=lon,
            external_source=self._safe_str(row.get('external_source')),
            canonical_street=canonical_street,
            canonical_full=canonical_full,
            match_key_exact=match_key_exact,
            match_key_no_unit=match_key_no_unit,
            normalization_warnings=warnings
        )

    def _safe_str(self, val) -> Optional[str]:
        """Convert value to string, handling None and NaN."""
        if val is None:
            return None
        val_str = str(val)
        if val_str.lower() in ('nan', 'none', ''):
            return None
        return val_str

    def _safe_float(self, val) -> Optional[float]:
        """Convert value to float, handling None and NaN."""
        if val is None:
            return None
        try:
            f = float(val)
            if f != f:  # NaN check
                return None
            return f
        except (ValueError, TypeError):
            return None

    def _normalize_house_number(self, val) -> str:
        """Normalize house number."""
        val = self._safe_str(val)
        if not val:
            return ''
        return val.strip().upper()

    def _normalize_direction(self, val) -> Optional[str]:
        """Normalize direction to single letter (N, S, E, W, etc.)"""
        val = self._safe_str(val)
        if not val:
            return None
        return self.DIRECTIONS.get(val.upper().strip())

    def _normalize_street_name(self, val) -> str:
        """Normalize street name with proper casing."""
        val = self._safe_str(val)
        if not val:
            return ''

        val = val.strip()

        # Check if it's an ordinal number street (18th, 115th, etc.)
        ordinal_match = re.match(r'^(\d+)(st|nd|rd|th)?$', val, re.IGNORECASE)
        if ordinal_match:
            num = ordinal_match.group(1)
            suffix = self._get_ordinal_suffix(int(num))
            return f"{num}{suffix}"

        return self._smart_title_case(val)

    def _get_ordinal_suffix(self, n: int) -> str:
        """Get the ordinal suffix for a number."""
        if 11 <= n % 100 <= 13:
            return 'th'
        return {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')

    def _smart_title_case(self, s: str) -> str:
        """Title case that handles special cases like 'MLK', 'Le Moyne'."""
        uppercase_words = {'MLK', 'JFK', 'FDR', 'US', 'IL'}
        lowercase_words = {'of', 'the', 'and', 'de', 'la', 'le', 'du', 'van', 'von'}

        words = s.split()
        result = []
        for i, word in enumerate(words):
            upper = word.upper()
            if upper in uppercase_words:
                result.append(upper)
            elif i > 0 and word.lower() in lowercase_words:
                result.append(word.lower())
            else:
                result.append(word.capitalize())

        return ' '.join(result)

    def _normalize_street_type(self, val) -> tuple:
        """Normalize street type. Returns (normalized_type, warning_message)."""
        val = self._safe_str(val)
        if not val:
            return (None, None)

        lookup = self.STREET_TYPES.get(val.upper().strip())
        if lookup:
            return (lookup, None)
        else:
            return (val.strip().title(), f"Unknown street type: {val}")

    def _normalize_unit(self, unit, unit_type) -> tuple:
        """Normalize unit number and type. Returns (unit_number, unit_type, position_indicator)."""
        unit = self._safe_str(unit)
        unit_type = self._safe_str(unit_type)

        if not unit:
            return (None, None, None)

        # Normalize the unit_type if provided
        norm_unit_type = None
        if unit_type:
            norm_unit_type = self.UNIT_TYPES.get(unit_type.upper().strip(), unit_type.strip().title())

        # Parse the unit string
        parsed = parse_unit(unit, norm_unit_type)

        return (parsed.number, parsed.unit_type, parsed.position_indicator)

    def _normalize_city(self, val) -> str:
        """Normalize city name."""
        val = self._safe_str(val)
        if not val:
            return 'Chicago'
        return val.strip().title()

    def _normalize_zip(self, val) -> str:
        """Normalize ZIP code to 5 digits."""
        val = self._safe_str(val)
        if not val:
            return ''
        match = re.search(r'(\d{5})', str(val))
        return match.group(1) if match else str(val).strip()

    def _is_po_box(self, address: str) -> bool:
        """Check if address is a PO Box."""
        if not address:
            return False
        return bool(re.search(r'\bP\.?O\.?\s*BOX\b', address, re.IGNORECASE))

    def _normalize_po_box(self, row: Dict[str, Any]) -> NormalizedAddress:
        """Handle PO Box addresses specially."""
        address = self._safe_str(row.get('address', '')) or self._safe_str(row.get('raw_address', ''))

        match = re.search(r'P\.?O\.?\s*BOX\s*(\d+)', address or '', re.IGNORECASE)
        box_number = match.group(1) if match else self._safe_str(row.get('house_number')) or ''

        city = self._normalize_city(row.get('city'))
        zip_code = self._normalize_zip(row.get('zip'))

        canonical = f"PO Box {box_number}, {city}, IL {zip_code}"
        match_key = f"{zip_code}|POBOX|{box_number}"

        return NormalizedAddress(
            id=str(row.get('id', '')),
            house_number=box_number,
            pre_direction=None,
            street_name='PO Box',
            post_direction=None,
            street_type=None,
            unit=None,
            unit_type=None,
            unit_position=None,
            city=city,
            state='IL',
            zip_code=zip_code,
            lat=self._safe_float(row.get('lat')),
            lon=self._safe_float(row.get('lon')),
            external_source=self._safe_str(row.get('external_source')),
            canonical_street=f"PO Box {box_number}",
            canonical_full=canonical,
            match_key_exact=match_key,
            match_key_no_unit=match_key,
            is_po_box=True,
            normalization_warnings=[]
        )

    def _build_canonical_street(self, house, pre_dir, street, post_dir, st_type) -> str:
        """Build canonical street address string."""
        parts = [house]
        if pre_dir:
            parts.append(pre_dir)
        parts.append(street)
        if post_dir:
            parts.append(post_dir)
        if st_type:
            parts.append(st_type)
        return ' '.join(filter(None, parts))

    def _build_canonical_full(self, street, unit, unit_type, unit_pos, city, state, zip_code) -> str:
        """Build full canonical address string."""
        parts = [street]

        if unit:
            unit_str = f"{unit_type} {unit}" if unit_type else f"Unit {unit}"
            if unit_pos:
                unit_str += f" ({unit_pos})"
            parts.append(unit_str)

        parts.append(f"{city}, {state} {zip_code}")
        return ', '.join(parts)

    def _build_match_key(self, zip_code, house, pre_dir, street, post_dir, st_type, unit) -> str:
        """Build a match key for duplicate detection."""
        components = [
            zip_code or '',
            house or '',
            pre_dir or '',
            (street or '').upper(),
            post_dir or '',
            (st_type or '').upper()[:3] if st_type else '',
            (unit or '').upper() if unit else ''
        ]
        return '|'.join(components)
