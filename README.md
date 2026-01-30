# Address Deduplication Project

A Python tool for normalizing and deduplicating address data. Identifies duplicate addresses and generates merge suggestions with confidence scores.

## Features

- **Address Normalization**: Standardizes street types, directions, unit formats, and casing
- **Multi-Strategy Duplicate Detection**:
  - **Exact**: Identical normalized addresses
  - **Fuzzy Street**: Similar street names (catches typos)
  - **Geocode Cluster**: Addresses within ~15 meters with same house number
  - **Same Building**: Different units at the same address (identified but not merged)
- **Merge Suggestions**: Ranked by confidence with source priority weighting
- **Chicago-Specific**: Handles Chicago address patterns (1R=Rear unit, 1FL=Floor 1, etc.)

## Installation

```bash
cd address-dedup-project
pip install -r requirements.txt
```

## Usage

### Quick Start (Sample Analysis)

```bash
# Run on a sample of 10,000 addresses for testing
python scripts/run_analysis.py --input ../chicago_addresses.csv --sample 10000
```

### Full Analysis

```bash
# Run on the complete dataset
python scripts/run_analysis.py --input ../chicago_addresses.csv
```

### Output Reports

Reports are written to the `reports/` directory:

| File | Description |
|------|-------------|
| `merge_suggestions_*.csv` | All merge suggestions with confidence scores |
| `high_confidence_merges_*.csv` | Exact matches safe for automated merging |
| `needs_manual_review_*.csv` | Fuzzy/geocode matches requiring human review |
| `same_building_addresses_*.csv` | Different units at same address (not duplicates) |
| `summary_*.txt` | Statistics summary |

## Merge Suggestion Format

Each merge suggestion identifies:
- `source_id`: The duplicate address ID to merge FROM
- `target_id`: The canonical address ID to merge INTO
- `confidence`: Confidence score (0.0-1.0)
- `duplicate_type`: Detection method used
- `reason`: Human-readable explanation

## Configuration

Edit `config.py` to customize:

```python
# Source authority ranking (lower = more trusted)
SOURCE_PRIORITY = {
    'db01_voters_raw': 1,      # Government records
    'cook_county_assessor': 2, # County property records
    'azure_2024': 5,           # Recent commercial import
    'azure_2023': 6,           # Older commercial import
}

# Detection thresholds
FUZZY_MATCH_THRESHOLD = 0.85  # Street name similarity
GEOCODE_DISTANCE_METERS = 15  # Max distance for geo clustering
AUTO_MERGE_CONFIDENCE = 0.95  # Min confidence for auto-merge
```

## Project Structure

```
address-dedup-project/
├── config.py              # Configuration settings
├── requirements.txt       # Python dependencies
├── src/
│   ├── __init__.py
│   ├── normalizer.py      # Address normalization
│   ├── duplicate_detector.py  # Duplicate detection
│   └── unit_patterns.py   # Unit number parsing
├── scripts/
│   └── run_analysis.py    # Main analysis script
├── reports/               # Generated reports
└── sql/                   # SQL scripts for database use
```

## How It Works

### 1. Normalization

Each address is normalized to a canonical form:
- Street types: `St` → `Street`, `Ave` → `Avenue`
- Directions: `North`, `N.` → `N`
- Unit types: `#`, `Apt` → normalized format
- Case: Proper title case
- ZIP codes: 5-digit format

### 2. Match Key Generation

Two match keys are generated:
- `match_key_exact`: Includes unit number (for exact duplicates)
- `match_key_no_unit`: Excludes unit (for same-building detection)

### 3. Duplicate Detection

Four strategies with different confidence levels:
| Strategy | Confidence | Use Case |
|----------|------------|----------|
| Exact | 1.0 | Identical normalized addresses |
| Same Building | 0.95 | Different units, same building |
| Fuzzy Street | 0.85-0.99 | Typos in street names |
| Geocode | 0.50-0.85 | Close coordinates, same house # |

### 4. Canonical Selection

When duplicates are found, the "best" address is selected based on:
1. Source priority (government > commercial)
2. Data completeness
3. Has geocode
4. No normalization warnings

## License

Internal use only.
