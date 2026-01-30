"""
Multi-strategy duplicate detection.

Strategies:
1. EXACT: Identical match_key_exact (same address with same unit)
2. SAME_BUILDING: Same match_key_no_unit (different units in same building)
3. FUZZY_STREET: Same zip/house, similar street name (catches typos)
4. GEOCODE_CLUSTER: Addresses within threshold distance with same house number

NOTE: Geocodes are estimated ~98% accurate, so geocode matching is used as
      supporting evidence rather than primary detection.
"""

import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import defaultdict
from enum import Enum

try:
    import Levenshtein
    HAS_LEVENSHTEIN = True
except ImportError:
    HAS_LEVENSHTEIN = False


class DuplicateType(Enum):
    EXACT = "exact"
    SAME_BUILDING = "same_building"
    FUZZY_STREET = "fuzzy_street"
    GEOCODE_CLUSTER = "geocode_cluster"


@dataclass
class DuplicateGroup:
    group_id: int
    duplicate_type: DuplicateType
    address_ids: List[str]
    canonical_id: Optional[str]
    confidence: float
    details: Dict = field(default_factory=dict)


@dataclass
class MergeSuggestion:
    """A suggestion to merge one address into another."""
    source_id: str
    target_id: str
    confidence: float
    duplicate_type: str
    reason: str
    source_address: str
    target_address: str


class DuplicateDetector:
    """Detects duplicate addresses using multiple strategies."""

    def __init__(self, normalized_addresses: List, fuzzy_threshold: float = 0.85,
                 geocode_distance_meters: int = 15):
        """
        Initialize with a list of normalized addresses.

        Args:
            normalized_addresses: List of NormalizedAddress objects
            fuzzy_threshold: Minimum similarity for fuzzy street name matches
            geocode_distance_meters: Maximum distance for geocode clustering
        """
        self.addresses = {addr.id: addr for addr in normalized_addresses}
        self.fuzzy_threshold = fuzzy_threshold
        self.geocode_distance_meters = geocode_distance_meters

    def find_all_duplicates(self) -> List[DuplicateGroup]:
        """Run all duplicate detection strategies."""
        groups = []
        group_counter = 0

        # 1. Exact duplicates (highest confidence)
        exact = self._find_exact_duplicates()
        for g in exact:
            group_counter += 1
            g.group_id = group_counter
        groups.extend(exact)

        # 2. Same building (high confidence)
        building = self._find_same_building()
        for g in building:
            group_counter += 1
            g.group_id = group_counter
        groups.extend(building)

        # 3. Fuzzy street name matches (medium confidence)
        if HAS_LEVENSHTEIN:
            fuzzy = self._find_fuzzy_street_duplicates()
            for g in fuzzy:
                group_counter += 1
                g.group_id = group_counter
            groups.extend(fuzzy)

        # 4. Geocode clusters (supporting evidence)
        geo = self._find_geocode_duplicates()
        for g in geo:
            group_counter += 1
            g.group_id = group_counter
        groups.extend(geo)

        return groups

    def generate_merge_suggestions(self, groups: List[DuplicateGroup] = None,
                                    source_priority: Dict = None) -> List[MergeSuggestion]:
        """
        Generate merge suggestions from duplicate groups.

        For each group, identifies which address should be the canonical one
        and suggests merging others into it.
        """
        if groups is None:
            groups = self.find_all_duplicates()

        if source_priority is None:
            source_priority = {}

        suggestions = []

        for group in groups:
            if group.duplicate_type == DuplicateType.SAME_BUILDING:
                # Same building addresses are NOT duplicates - different units
                continue

            if len(group.address_ids) < 2:
                continue

            # Score each address to find the canonical one
            scored = []
            for addr_id in group.address_ids:
                addr = self.addresses.get(addr_id)
                if addr:
                    score = self._score_address(addr, source_priority)
                    scored.append((addr_id, addr, score))

            # Sort by score descending - highest score is canonical
            scored.sort(key=lambda x: x[2], reverse=True)

            if len(scored) < 2:
                continue

            canonical_id, canonical_addr, _ = scored[0]

            # Generate merge suggestions for non-canonical addresses
            for source_id, source_addr, _ in scored[1:]:
                suggestions.append(MergeSuggestion(
                    source_id=source_id,
                    target_id=canonical_id,
                    confidence=group.confidence,
                    duplicate_type=group.duplicate_type.value,
                    reason=self._build_reason(group, source_addr, canonical_addr),
                    source_address=source_addr.canonical_full,
                    target_address=canonical_addr.canonical_full
                ))

        return suggestions

    def _score_address(self, addr, source_priority: Dict) -> float:
        """Score an address based on quality criteria."""
        score = 0.0

        # Has geocode (0.20 weight - reduced due to 98% accuracy)
        if addr.lat is not None and addr.lon is not None:
            score += 0.20

        # Source priority (0.30 weight)
        source = addr.external_source
        priority = source_priority.get(source, 10) if source else 10
        score += 0.30 * (11 - priority) / 10

        # Data completeness (0.25 weight)
        key_fields = ['house_number', 'street_name', 'city', 'zip_code']
        optional_fields = ['pre_direction', 'street_type', 'unit']

        key_present = sum(1 for f in key_fields if getattr(addr, f))
        key_score = key_present / len(key_fields)

        opt_present = sum(1 for f in optional_fields if getattr(addr, f))
        opt_score = opt_present / len(optional_fields) * 0.2

        score += 0.25 * min(1.0, key_score + opt_score)

        # No warnings (0.10 weight)
        if not addr.normalization_warnings:
            score += 0.10

        return score

    def _build_reason(self, group: DuplicateGroup, source, target) -> str:
        """Build a human-readable reason for the merge suggestion."""
        if group.duplicate_type == DuplicateType.EXACT:
            return f"Exact match on normalized address"
        elif group.duplicate_type == DuplicateType.FUZZY_STREET:
            return f"Similar street names: '{source.street_name}' vs '{target.street_name}'"
        elif group.duplicate_type == DuplicateType.GEOCODE_CLUSTER:
            return f"Within {self.geocode_distance_meters}m with same house number"
        return "Duplicate detected"

    def _find_exact_duplicates(self) -> List[DuplicateGroup]:
        """Find addresses with identical match keys."""
        groups = []
        key_to_ids = defaultdict(list)

        for addr_id, addr in self.addresses.items():
            if addr.match_key_exact:
                key_to_ids[addr.match_key_exact].append(addr_id)

        for match_key, ids in key_to_ids.items():
            if len(ids) > 1:
                groups.append(DuplicateGroup(
                    group_id=0,
                    duplicate_type=DuplicateType.EXACT,
                    address_ids=ids,
                    canonical_id=None,
                    confidence=1.0,
                    details={"match_key": match_key, "count": len(ids)}
                ))

        return groups

    def _find_same_building(self) -> List[DuplicateGroup]:
        """Find addresses that are different units in the same building."""
        groups = []
        key_to_data = defaultdict(list)

        for addr_id, addr in self.addresses.items():
            if addr.match_key_no_unit and addr.unit:
                key_to_data[addr.match_key_no_unit].append((addr_id, addr.unit))

        for match_key, data in key_to_data.items():
            if len(data) > 1:
                ids = [d[0] for d in data]
                units = list(set(d[1] for d in data if d[1]))
                if len(units) > 1:  # Only if actually different units
                    groups.append(DuplicateGroup(
                        group_id=0,
                        duplicate_type=DuplicateType.SAME_BUILDING,
                        address_ids=ids,
                        canonical_id=None,
                        confidence=0.95,
                        details={
                            "match_key": match_key,
                            "units": units,
                            "count": len(ids),
                            "note": "Different units in same building - not true duplicates"
                        }
                    ))

        return groups

    def _find_fuzzy_street_duplicates(self) -> List[DuplicateGroup]:
        """Find addresses with similar street names (catches typos)."""
        groups = []
        seen_pairs = set()

        # Group by zip + house number
        zip_house_groups = defaultdict(list)
        for addr_id, addr in self.addresses.items():
            if addr.zip_code and addr.house_number and addr.street_name:
                key = (addr.zip_code, addr.house_number)
                zip_house_groups[key].append((addr_id, addr))

        for (zip_code, house_num), addr_list in zip_house_groups.items():
            if len(addr_list) < 2:
                continue

            # Compare each pair
            for i in range(len(addr_list)):
                for j in range(i + 1, len(addr_list)):
                    id1, addr1 = addr_list[i]
                    id2, addr2 = addr_list[j]

                    # Skip if same street name (already caught by exact match)
                    if addr1.street_name.upper() == addr2.street_name.upper():
                        continue

                    pair_key = tuple(sorted([id1, id2]))
                    if pair_key in seen_pairs:
                        continue

                    similarity = Levenshtein.ratio(
                        addr1.street_name.lower(),
                        addr2.street_name.lower()
                    )

                    if similarity >= self.fuzzy_threshold:
                        seen_pairs.add(pair_key)
                        groups.append(DuplicateGroup(
                            group_id=0,
                            duplicate_type=DuplicateType.FUZZY_STREET,
                            address_ids=[id1, id2],
                            canonical_id=None,
                            confidence=similarity,
                            details={
                                "street1": addr1.street_name,
                                "street2": addr2.street_name,
                                "similarity": round(similarity, 3),
                                "address1": addr1.canonical_full,
                                "address2": addr2.canonical_full
                            }
                        ))

        return groups

    def _find_geocode_duplicates(self) -> List[DuplicateGroup]:
        """Find addresses that are geographically very close with same house number."""
        groups = []
        seen_pairs = set()

        # Group by house number
        house_groups = defaultdict(list)
        for addr_id, addr in self.addresses.items():
            if addr.lat is not None and addr.lon is not None and addr.house_number:
                house_groups[addr.house_number].append((addr_id, addr))

        for house_num, addr_list in house_groups.items():
            if len(addr_list) < 2:
                continue

            # Compare each pair
            for i in range(len(addr_list)):
                for j in range(i + 1, len(addr_list)):
                    id1, addr1 = addr_list[i]
                    id2, addr2 = addr_list[j]

                    # Skip if canonical addresses are the same
                    if addr1.canonical_full == addr2.canonical_full:
                        continue

                    pair_key = tuple(sorted([id1, id2]))
                    if pair_key in seen_pairs:
                        continue

                    distance = self._haversine_distance(
                        addr1.lat, addr1.lon,
                        addr2.lat, addr2.lon
                    )

                    if distance <= self.geocode_distance_meters:
                        seen_pairs.add(pair_key)
                        # Confidence reduced due to geocode uncertainty
                        base_confidence = 0.85
                        confidence = max(0.5, base_confidence - (distance / self.geocode_distance_meters) * 0.35)

                        groups.append(DuplicateGroup(
                            group_id=0,
                            duplicate_type=DuplicateType.GEOCODE_CLUSTER,
                            address_ids=[id1, id2],
                            canonical_id=None,
                            confidence=round(confidence, 3),
                            details={
                                "address1": addr1.canonical_full,
                                "address2": addr2.canonical_full,
                                "distance_meters": round(distance, 2),
                                "coords1": (addr1.lat, addr1.lon),
                                "coords2": (addr2.lat, addr2.lon),
                                "note": "Geocode-based match - verify with other criteria"
                            }
                        ))

        return groups

    def _haversine_distance(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in meters using Haversine formula."""
        R = 6371000  # Earth's radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (math.sin(delta_phi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c
