#!/usr/bin/env python3
"""
Main analysis script for address deduplication.

This script:
1. Reads the Chicago addresses CSV
2. Normalizes all addresses
3. Detects duplicates using multiple strategies
4. Generates merge suggestions with confidence scores
5. Outputs reports for review

Usage:
    python scripts/run_analysis.py --input ../chicago_addresses.csv --sample 10000
    python scripts/run_analysis.py --input ../chicago_addresses.csv  # Full dataset
"""

import argparse
import csv
import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
from tqdm import tqdm

from src.normalizer import AddressNormalizer
from src.duplicate_detector import DuplicateDetector, DuplicateType
from config import SOURCE_PRIORITY, FUZZY_MATCH_THRESHOLD, GEOCODE_DISTANCE_METERS


def load_addresses(input_path: str, sample_size: int = None) -> pd.DataFrame:
    """Load addresses from CSV file."""
    print(f"Loading addresses from {input_path}...")

    if sample_size:
        # Read in chunks and take a sample
        df = pd.read_csv(input_path, nrows=sample_size)
        print(f"Loaded {len(df):,} addresses (sample)")
    else:
        df = pd.read_csv(input_path)
        print(f"Loaded {len(df):,} addresses")

    return df


def normalize_addresses(df: pd.DataFrame) -> list:
    """Normalize all addresses in the dataframe."""
    print("Normalizing addresses...")
    normalizer = AddressNormalizer()
    normalized = []

    for _, row in tqdm(df.iterrows(), total=len(df), desc="Normalizing"):
        try:
            norm_addr = normalizer.normalize(row.to_dict())
            normalized.append(norm_addr)
        except Exception as e:
            print(f"Error normalizing {row.get('id', 'unknown')}: {e}")

    print(f"Successfully normalized {len(normalized):,} addresses")
    return normalized


def detect_duplicates(normalized: list) -> tuple:
    """Run duplicate detection and return groups and suggestions."""
    print("Detecting duplicates...")

    detector = DuplicateDetector(
        normalized,
        fuzzy_threshold=FUZZY_MATCH_THRESHOLD,
        geocode_distance_meters=GEOCODE_DISTANCE_METERS
    )

    groups = detector.find_all_duplicates()
    print(f"Found {len(groups):,} duplicate groups")

    # Count by type
    type_counts = {}
    for g in groups:
        t = g.duplicate_type.value
        type_counts[t] = type_counts.get(t, 0) + 1

    for t, c in sorted(type_counts.items()):
        print(f"  - {t}: {c:,} groups")

    print("Generating merge suggestions...")
    suggestions = detector.generate_merge_suggestions(groups, SOURCE_PRIORITY)
    print(f"Generated {len(suggestions):,} merge suggestions")

    return groups, suggestions


def write_reports(groups: list, suggestions: list, normalized: list, output_dir: str):
    """Write output reports."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Create address lookup for reporting
    addr_lookup = {addr.id: addr for addr in normalized}

    # 1. Write merge suggestions report
    suggestions_file = os.path.join(output_dir, f"merge_suggestions_{timestamp}.csv")
    print(f"Writing merge suggestions to {suggestions_file}...")

    with open(suggestions_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'source_id', 'target_id', 'confidence', 'duplicate_type',
            'reason', 'source_address', 'target_address'
        ])
        for s in suggestions:
            writer.writerow([
                s.source_id, s.target_id, round(s.confidence, 3),
                s.duplicate_type, s.reason, s.source_address, s.target_address
            ])

    # 2. Write high-confidence merges (exact matches only)
    high_conf_file = os.path.join(output_dir, f"high_confidence_merges_{timestamp}.csv")
    print(f"Writing high-confidence merges to {high_conf_file}...")

    high_conf = [s for s in suggestions if s.confidence >= 0.95 and s.duplicate_type == 'exact']
    with open(high_conf_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'source_id', 'target_id', 'confidence',
            'source_address', 'target_address'
        ])
        for s in high_conf:
            writer.writerow([
                s.source_id, s.target_id, round(s.confidence, 3),
                s.source_address, s.target_address
            ])

    # 3. Write needs-review report (lower confidence or fuzzy/geocode matches)
    review_file = os.path.join(output_dir, f"needs_manual_review_{timestamp}.csv")
    print(f"Writing needs-review items to {review_file}...")

    needs_review = [s for s in suggestions
                    if s.confidence < 0.95 or s.duplicate_type in ('fuzzy_street', 'geocode_cluster')]
    with open(review_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            'source_id', 'target_id', 'confidence', 'duplicate_type',
            'reason', 'source_address', 'target_address'
        ])
        for s in needs_review:
            writer.writerow([
                s.source_id, s.target_id, round(s.confidence, 3),
                s.duplicate_type, s.reason, s.source_address, s.target_address
            ])

    # 4. Write same-building report (not duplicates, but related addresses)
    building_file = os.path.join(output_dir, f"same_building_addresses_{timestamp}.csv")
    print(f"Writing same-building addresses to {building_file}...")

    building_groups = [g for g in groups if g.duplicate_type == DuplicateType.SAME_BUILDING]
    with open(building_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['group_id', 'address_id', 'unit', 'canonical_address'])
        for g in building_groups:
            for addr_id in g.address_ids:
                addr = addr_lookup.get(addr_id)
                if addr:
                    writer.writerow([g.group_id, addr_id, addr.unit, addr.canonical_full])

    # 5. Write summary statistics
    summary_file = os.path.join(output_dir, f"summary_{timestamp}.txt")
    print(f"Writing summary to {summary_file}...")

    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("Address Deduplication Analysis Summary\n")
        f.write("=" * 50 + "\n\n")
        f.write(f"Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Total Addresses Analyzed: {len(normalized):,}\n\n")

        f.write("Duplicate Groups Found:\n")
        type_counts = {}
        for g in groups:
            t = g.duplicate_type.value
            type_counts[t] = type_counts.get(t, 0) + 1
        for t, c in sorted(type_counts.items()):
            f.write(f"  - {t}: {c:,} groups\n")

        f.write(f"\nTotal Merge Suggestions: {len(suggestions):,}\n")
        f.write(f"  - High Confidence (auto-merge candidates): {len(high_conf):,}\n")
        f.write(f"  - Needs Manual Review: {len(needs_review):,}\n")
        f.write(f"  - Same Building (not duplicates): {len(building_groups):,} groups\n")

    print(f"\nReports written to {output_dir}/")
    print(f"  - merge_suggestions_{timestamp}.csv: All merge suggestions")
    print(f"  - high_confidence_merges_{timestamp}.csv: Safe for auto-merge ({len(high_conf):,})")
    print(f"  - needs_manual_review_{timestamp}.csv: Requires review ({len(needs_review):,})")
    print(f"  - same_building_addresses_{timestamp}.csv: Related addresses ({len(building_groups):,} groups)")
    print(f"  - summary_{timestamp}.txt: Statistics summary")


def main():
    parser = argparse.ArgumentParser(description='Address Deduplication Analysis')
    parser.add_argument('--input', '-i', required=True, help='Input CSV file path')
    parser.add_argument('--output', '-o', default='reports', help='Output directory for reports')
    parser.add_argument('--sample', '-s', type=int, help='Sample size (for testing)')

    args = parser.parse_args()

    # Resolve paths
    script_dir = Path(__file__).parent.parent
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = script_dir / input_path

    output_dir = Path(args.output)
    if not output_dir.is_absolute():
        output_dir = script_dir / output_dir

    # Run analysis
    df = load_addresses(str(input_path), args.sample)
    normalized = normalize_addresses(df)
    groups, suggestions = detect_duplicates(normalized)
    write_reports(groups, suggestions, normalized, str(output_dir))

    print("\nAnalysis complete!")


if __name__ == '__main__':
    main()
