"""
Configuration for address deduplication project.
"""

# Source authority ranking - lower number = more authoritative
SOURCE_PRIORITY = {
    'db01_voters_raw': 1,      # Government voter records
    'cook_county_assessor': 2, # County property records
    'usps_validation': 3,      # USPS validated
    'pipeline': 4,             # Internal data pipeline
    'azure_2024': 5,           # Recent commercial import
    'azure_2023': 6,           # Older commercial import
    None: 10,                  # Unknown source - lowest priority
}

# Duplicate detection thresholds
FUZZY_MATCH_THRESHOLD = 0.85  # Minimum similarity for fuzzy street name matches
GEOCODE_DISTANCE_METERS = 15  # Maximum distance for geocode clustering

# Auto-merge threshold
AUTO_MERGE_CONFIDENCE = 0.95  # Minimum confidence for automatic merge suggestions

def get_source_priority(source: str) -> int:
    """Get priority for a source, defaulting to 10 for unknown."""
    if source is None or str(source).lower() == 'nan':
        return 10
    return SOURCE_PRIORITY.get(source, 10)
