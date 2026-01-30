"""
Enrich the high_confidence_merges CSV with unit data from the original addresses.
"""
import csv
import sys
from pathlib import Path

def main():
    project_root = Path(__file__).parent.parent.parent

    original_csv = project_root / "chicago_addresses.csv"
    merges_csv = project_root / "address-dedup-project" / "reports" / "high_confidence_merges_20260130_001351.csv"
    output_csv = project_root / "address-dedup-project" / "reports" / "high_confidence_merges_enriched.csv"

    print(f"Loading original addresses from {original_csv}...")

    # First pass: collect all IDs we need
    needed_ids = set()
    with open(merges_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            needed_ids.add(row['source_id'])
            needed_ids.add(row['target_id'])

    print(f"Need data for {len(needed_ids)} unique address IDs")

    # Load original data for those IDs
    original_data = {}
    with open(original_csv, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if row['id'] in needed_ids:
                original_data[row['id']] = {
                    'raw_address': row.get('raw_address', ''),
                    'address': row.get('address', ''),
                    'unit': row.get('unit', ''),
                    'unit_type': row.get('unit_type', ''),
                    'external_source': row.get('external_source', ''),
                }
            if i % 500000 == 0:
                print(f"  Scanned {i} rows, found {len(original_data)} matches...")

    print(f"Loaded data for {len(original_data)} addresses")

    # Enrich and write output
    print(f"Writing enriched CSV to {output_csv}...")
    with open(merges_csv, 'r', encoding='utf-8') as infile:
        reader = csv.DictReader(infile)

        fieldnames = [
            'source_id', 'target_id', 'confidence', 'source_address', 'target_address',
            'source_raw', 'source_original', 'source_unit', 'source_unit_type', 'source_ext_source',
            'target_raw', 'target_original', 'target_unit', 'target_unit_type', 'target_ext_source'
        ]

        with open(output_csv, 'w', encoding='utf-8', newline='') as outfile:
            writer = csv.DictWriter(outfile, fieldnames=fieldnames)
            writer.writeheader()

            for row in reader:
                source = original_data.get(row['source_id'], {})
                target = original_data.get(row['target_id'], {})

                writer.writerow({
                    'source_id': row['source_id'],
                    'target_id': row['target_id'],
                    'confidence': row['confidence'],
                    'source_address': row['source_address'],
                    'target_address': row['target_address'],
                    'source_raw': source.get('raw_address', ''),
                    'source_original': source.get('address', ''),
                    'source_unit': source.get('unit', ''),
                    'source_unit_type': source.get('unit_type', ''),
                    'source_ext_source': source.get('external_source', ''),
                    'target_raw': target.get('raw_address', ''),
                    'target_original': target.get('address', ''),
                    'target_unit': target.get('unit', ''),
                    'target_unit_type': target.get('unit_type', ''),
                    'target_ext_source': target.get('external_source', ''),
                })

    print("Done!")

if __name__ == '__main__':
    main()
