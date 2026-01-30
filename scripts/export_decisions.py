"""
Export review decisions from the Render app to local files.

Run this script to save your approved/rejected decisions to git.

Usage:
    python scripts/export_decisions.py
"""

import os
import json
import urllib.request
from datetime import datetime
from pathlib import Path

# Render app URL
APP_URL = "https://address-merge-review.onrender.com"

def fetch_json(url):
    """Fetch JSON from URL."""
    with urllib.request.urlopen(url) as response:
        return json.loads(response.read().decode('utf-8'))

def fetch_csv(url):
    """Fetch CSV from URL."""
    with urllib.request.urlopen(url) as response:
        return response.read().decode('utf-8')

def main():
    project_root = Path(__file__).parent.parent
    exports_dir = project_root / "exports"
    exports_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("Fetching review statistics...")
    stats = fetch_json(f"{APP_URL}/api/stats")
    print(f"  Approved: {stats['approved']}")
    print(f"  Rejected: {stats['rejected']}")
    print(f"  Pending:  {stats['pending']}")
    print(f"  Total:    {stats['total']}")
    print()

    # Export approved merges
    if stats['approved'] > 0:
        print(f"Exporting {stats['approved']} approved merges...")

        # CSV format
        csv_data = fetch_csv(f"{APP_URL}/api/export/approved")
        csv_path = exports_dir / f"approved_merges_{timestamp}.csv"
        csv_path.write_text(csv_data, encoding='utf-8')
        print(f"  Saved: {csv_path}")

        # JSON format (for API)
        json_data = fetch_json(f"{APP_URL}/api/export/approved/json")
        json_path = exports_dir / f"approved_merges_{timestamp}.json"
        json_path.write_text(json.dumps(json_data, indent=2), encoding='utf-8')
        print(f"  Saved: {json_path}")

        # Also save a "latest" version for easy access
        latest_csv = exports_dir / "approved_merges_latest.csv"
        latest_csv.write_text(csv_data, encoding='utf-8')
        latest_json = exports_dir / "approved_merges_latest.json"
        latest_json.write_text(json.dumps(json_data, indent=2), encoding='utf-8')
        print(f"  Updated: approved_merges_latest.csv/json")
    else:
        print("No approved merges to export.")

    print()

    # Export rejected merges
    if stats['rejected'] > 0:
        print(f"Exporting {stats['rejected']} rejected merges...")

        csv_data = fetch_csv(f"{APP_URL}/api/export/rejected")
        csv_path = exports_dir / f"rejected_merges_{timestamp}.csv"
        csv_path.write_text(csv_data, encoding='utf-8')
        print(f"  Saved: {csv_path}")

        latest_csv = exports_dir / "rejected_merges_latest.csv"
        latest_csv.write_text(csv_data, encoding='utf-8')
        print(f"  Updated: rejected_merges_latest.csv")
    else:
        print("No rejected merges to export.")

    print()

    # Save summary
    summary = {
        "exported_at": datetime.now().isoformat(),
        "stats": stats,
        "files": {
            "approved_csv": f"approved_merges_{timestamp}.csv" if stats['approved'] > 0 else None,
            "approved_json": f"approved_merges_{timestamp}.json" if stats['approved'] > 0 else None,
            "rejected_csv": f"rejected_merges_{timestamp}.csv" if stats['rejected'] > 0 else None,
        }
    }
    summary_path = exports_dir / "export_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(f"Summary saved: {summary_path}")

    print()
    print("Done! To commit to git:")
    print("  git add exports/")
    print('  git commit -m "Export review decisions"')
    print("  git push")

if __name__ == "__main__":
    main()
