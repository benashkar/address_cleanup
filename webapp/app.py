"""
Address Merge Review Web Application

A simple Flask app to review and approve/deny address merge suggestions.
"""

import os
import re
import csv
import sqlite3
from flask import Flask, render_template, request, jsonify, g, send_file
from pathlib import Path

app = Flask(__name__)

DATABASE = os.environ.get('DATABASE_PATH', 'review.db')
MERGES_CSV = os.environ.get('MERGES_CSV', '../reports/high_confidence_merges_20260130_001351.csv')
ORIGINAL_CSV = os.environ.get('ORIGINAL_CSV', '../../chicago_addresses.csv')


def get_db():
    """Get database connection."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    """Close database connection."""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def classify_merge(source_addr, target_addr):
    """
    Classify the type of merge based on address differences.

    Returns: (category, subcategory, description)
    """
    if not source_addr or not target_addr:
        return ('empty', 'missing_data', 'One or both addresses empty')

    source = source_addr.lower().strip()
    target = target_addr.lower().strip()

    # Exact match
    if source == target:
        return ('exact', 'identical', 'Identical addresses')

    # Check for position indicator differences (Front/Rear/East/West)
    position_pattern = r'\((front|rear|east|west)\)'
    source_no_pos = re.sub(position_pattern, '', source).strip()
    target_no_pos = re.sub(position_pattern, '', target).strip()

    source_pos = re.search(position_pattern, source)
    target_pos = re.search(position_pattern, target)

    if source_no_pos == target_no_pos and source_pos and target_pos:
        if source_pos.group(1) != target_pos.group(1):
            return ('position_diff', 'front_rear_east_west',
                    f'Position differs: {source_pos.group(1)} vs {target_pos.group(1)}')

    # Check for unit type differences (Unit vs Floor vs Apt)
    unit_types = ['unit', 'floor', 'apt', 'apartment', 'ste', 'suite']
    for ut1 in unit_types:
        for ut2 in unit_types:
            if ut1 != ut2:
                if ut1 in source and ut2 in target:
                    # Check if rest is the same
                    s_clean = source.replace(ut1, 'UNIT_PLACEHOLDER')
                    t_clean = target.replace(ut2, 'UNIT_PLACEHOLDER')
                    if s_clean == t_clean:
                        return ('unit_type_diff', f'{ut1}_vs_{ut2}',
                                f'Unit type differs: {ut1} vs {ut2}')

    # Check for empty/incomplete addresses
    if source.startswith(', chicago') or target.startswith(', chicago'):
        return ('incomplete', 'no_street', 'Missing street address')

    # Check if only case differs
    if source == target:
        return ('exact', 'case_diff', 'Only case difference')

    # Similar but not exact
    return ('similar', 'minor_diff', 'Minor formatting differences')


def init_db():
    """Initialize the database with merge suggestions."""
    db = get_db()

    # Create tables
    db.execute('''
        CREATE TABLE IF NOT EXISTS merges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            confidence REAL,
            source_address TEXT,
            target_address TEXT,
            category TEXT,
            subcategory TEXT,
            category_desc TEXT,
            status TEXT DEFAULT 'pending',
            reviewed_at TIMESTAMP,
            reviewer_notes TEXT
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS original_addresses (
            id TEXT PRIMARY KEY,
            address TEXT,
            raw_address TEXT,
            house_number TEXT,
            pre_direction TEXT,
            street_name TEXT,
            street_type TEXT,
            unit TEXT,
            unit_type TEXT,
            city TEXT,
            zip TEXT,
            lat REAL,
            lon REAL,
            external_source TEXT
        )
    ''')

    db.execute('''
        CREATE TABLE IF NOT EXISTS review_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            subcategory TEXT,
            action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            applied_count INTEGER DEFAULT 0
        )
    ''')

    db.execute('CREATE INDEX IF NOT EXISTS idx_merges_status ON merges(status)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_merges_category ON merges(category)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_merges_subcategory ON merges(subcategory)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_merges_source ON merges(source_id)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_merges_target ON merges(target_id)')

    db.commit()


def load_merges_if_needed():
    """Load merge suggestions from CSV if not already loaded."""
    db = get_db()
    count = db.execute('SELECT COUNT(*) FROM merges').fetchone()[0]

    if count == 0 and os.path.exists(MERGES_CSV):
        print(f"Loading merges from {MERGES_CSV}...")
        with open(MERGES_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            batch = []
            for i, row in enumerate(reader):
                # Classify the merge
                category, subcategory, desc = classify_merge(
                    row['source_address'],
                    row['target_address']
                )

                batch.append((
                    row['source_id'],
                    row['target_id'],
                    float(row['confidence']),
                    row['source_address'],
                    row['target_address'],
                    category,
                    subcategory,
                    desc
                ))
                if len(batch) >= 1000:
                    db.executemany('''
                        INSERT INTO merges (source_id, target_id, confidence,
                            source_address, target_address, category, subcategory, category_desc)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', batch)
                    batch = []
                    if i % 10000 == 0:
                        print(f"  Loaded {i} records...")
            if batch:
                db.executemany('''
                    INSERT INTO merges (source_id, target_id, confidence,
                        source_address, target_address, category, subcategory, category_desc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', batch)
        db.commit()
        final_count = db.execute('SELECT COUNT(*) FROM merges').fetchone()[0]
        print(f"Loaded {final_count} merge suggestions")


def load_original_sample():
    """Load a sample of original addresses for comparison."""
    db = get_db()
    count = db.execute('SELECT COUNT(*) FROM original_addresses').fetchone()[0]

    if count == 0 and os.path.exists(ORIGINAL_CSV):
        print(f"Loading original addresses from {ORIGINAL_CSV}...")

        # Get IDs we need
        merge_ids = db.execute('''
            SELECT DISTINCT source_id FROM merges
            UNION
            SELECT DISTINCT target_id FROM merges
        ''').fetchall()
        needed_ids = set(row[0] for row in merge_ids)

        with open(ORIGINAL_CSV, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            batch = []
            loaded = 0
            for row in reader:
                if row['id'] in needed_ids:
                    batch.append((
                        row['id'],
                        row.get('address', ''),
                        row.get('raw_address', ''),
                        row.get('house_number', ''),
                        row.get('pre_direction', ''),
                        row.get('street_name', ''),
                        row.get('street_type', ''),
                        row.get('unit', ''),
                        row.get('unit_type', ''),
                        row.get('city', ''),
                        row.get('zip', ''),
                        float(row['lat']) if row.get('lat') else None,
                        float(row['lon']) if row.get('lon') else None,
                        row.get('external_source', '')
                    ))
                    loaded += 1
                    if len(batch) >= 1000:
                        db.executemany('''
                            INSERT OR IGNORE INTO original_addresses
                            (id, address, raw_address, house_number, pre_direction,
                             street_name, street_type, unit, unit_type, city, zip,
                             lat, lon, external_source)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''', batch)
                        batch = []
                        if loaded % 10000 == 0:
                            print(f"  Loaded {loaded} original addresses...")
            if batch:
                db.executemany('''
                    INSERT OR IGNORE INTO original_addresses
                    (id, address, raw_address, house_number, pre_direction,
                     street_name, street_type, unit, unit_type, city, zip,
                     lat, lon, external_source)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', batch)
        db.commit()
        print(f"Loaded {loaded} original addresses")


@app.route('/')
def index():
    """Main review interface."""
    return render_template('index.html')


@app.route('/api/stats')
def get_stats():
    """Get review statistics."""
    db = get_db()
    stats = {}

    for status in ['pending', 'approved', 'rejected']:
        count = db.execute(
            'SELECT COUNT(*) FROM merges WHERE status = ?', (status,)
        ).fetchone()[0]
        stats[status] = count

    stats['total'] = sum(stats.values())
    return jsonify(stats)


@app.route('/api/categories')
def get_categories():
    """Get all categories with counts."""
    db = get_db()

    categories = db.execute('''
        SELECT category, subcategory, category_desc, COUNT(*) as count,
               SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
               SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
               SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
        FROM merges
        GROUP BY category, subcategory
        ORDER BY count DESC
    ''').fetchall()

    return jsonify([dict(row) for row in categories])


@app.route('/api/merges')
def get_merges():
    """Get paginated merge suggestions."""
    db = get_db()

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    status_filter = request.args.get('status', 'pending')
    category_filter = request.args.get('category', '')
    subcategory_filter = request.args.get('subcategory', '')

    offset = (page - 1) * per_page

    # Build query
    where_clauses = ['status = ?']
    params = [status_filter]

    if category_filter:
        where_clauses.append('category = ?')
        params.append(category_filter)

    if subcategory_filter:
        where_clauses.append('subcategory = ?')
        params.append(subcategory_filter)

    where_sql = ' AND '.join(where_clauses)

    # Get total count for pagination
    total = db.execute(
        f'SELECT COUNT(*) FROM merges WHERE {where_sql}', params
    ).fetchone()[0]

    # Get merges with original address data
    merges = db.execute(f'''
        SELECT
            m.id,
            m.source_id,
            m.target_id,
            m.confidence,
            m.source_address,
            m.target_address,
            m.category,
            m.subcategory,
            m.category_desc,
            m.status,
            m.reviewer_notes,
            os.raw_address as source_raw,
            os.address as source_original,
            os.external_source as source_ext_source,
            ot.raw_address as target_raw,
            ot.address as target_original,
            ot.external_source as target_ext_source
        FROM merges m
        LEFT JOIN original_addresses os ON m.source_id = os.id
        LEFT JOIN original_addresses ot ON m.target_id = ot.id
        WHERE {where_sql}
        ORDER BY m.id
        LIMIT ? OFFSET ?
    ''', params + [per_page, offset]).fetchall()

    return jsonify({
        'merges': [dict(row) for row in merges],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if total > 0 else 1
    })


@app.route('/api/merges/<int:merge_id>/approve', methods=['POST'])
def approve_merge(merge_id):
    """Approve a merge suggestion."""
    db = get_db()
    notes = request.json.get('notes', '') if request.json else ''

    db.execute('''
        UPDATE merges
        SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP, reviewer_notes = ?
        WHERE id = ?
    ''', (notes, merge_id))
    db.commit()

    return jsonify({'success': True})


@app.route('/api/merges/<int:merge_id>/reject', methods=['POST'])
def reject_merge(merge_id):
    """Reject a merge suggestion."""
    db = get_db()
    notes = request.json.get('notes', '') if request.json else ''

    db.execute('''
        UPDATE merges
        SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP, reviewer_notes = ?
        WHERE id = ?
    ''', (notes, merge_id))
    db.commit()

    return jsonify({'success': True})


@app.route('/api/merges/bulk', methods=['POST'])
def bulk_action():
    """Bulk approve/reject merges."""
    db = get_db()
    data = request.json
    action = data.get('action')  # 'approve' or 'reject'
    merge_ids = data.get('ids', [])

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'Invalid action'}), 400

    status = 'approved' if action == 'approve' else 'rejected'

    placeholders = ','.join('?' * len(merge_ids))
    db.execute(f'''
        UPDATE merges
        SET status = ?, reviewed_at = CURRENT_TIMESTAMP
        WHERE id IN ({placeholders})
    ''', [status] + merge_ids)
    db.commit()

    return jsonify({'success': True, 'updated': len(merge_ids)})


@app.route('/api/rules/apply', methods=['POST'])
def apply_rule():
    """Apply a rule to all matching merges in a category."""
    db = get_db()
    data = request.json

    action = data.get('action')  # 'approve' or 'reject'
    category = data.get('category')
    subcategory = data.get('subcategory')

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'Invalid action'}), 400

    status = 'approved' if action == 'approve' else 'rejected'

    # Build query
    where_clauses = ['status = ?']
    params = ['pending']

    if category:
        where_clauses.append('category = ?')
        params.append(category)

    if subcategory:
        where_clauses.append('subcategory = ?')
        params.append(subcategory)

    where_sql = ' AND '.join(where_clauses)

    # Count how many will be affected
    count = db.execute(
        f'SELECT COUNT(*) FROM merges WHERE {where_sql}', params
    ).fetchone()[0]

    # Apply the rule
    db.execute(f'''
        UPDATE merges
        SET status = ?, reviewed_at = CURRENT_TIMESTAMP, reviewer_notes = 'Bulk rule applied'
        WHERE {where_sql}
    ''', [status] + params)

    # Save the rule
    db.execute('''
        INSERT INTO review_rules (category, subcategory, action, applied_count)
        VALUES (?, ?, ?, ?)
    ''', (category, subcategory, action, count))

    db.commit()

    return jsonify({'success': True, 'updated': count})


@app.route('/api/rules')
def get_rules():
    """Get all saved rules."""
    db = get_db()
    rules = db.execute('''
        SELECT * FROM review_rules ORDER BY created_at DESC
    ''').fetchall()
    return jsonify([dict(row) for row in rules])


@app.route('/api/export/approved')
def export_approved():
    """Export approved merges as CSV."""
    db = get_db()

    merges = db.execute('''
        SELECT source_id, target_id, confidence, source_address, target_address, category, subcategory
        FROM merges WHERE status = 'approved'
    ''').fetchall()

    # Write to temp file
    export_path = '/tmp/approved_merges.csv'
    with open(export_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['source_id', 'target_id', 'confidence', 'source_address', 'target_address', 'category', 'subcategory'])
        for row in merges:
            writer.writerow(row)

    return send_file(export_path, as_attachment=True, download_name='approved_merges.csv')


@app.cli.command('init-db')
def init_db_command():
    """Initialize the database."""
    init_db()
    load_merges_if_needed()
    load_original_sample()
    print('Database initialized.')


@app.cli.command('reclassify')
def reclassify_command():
    """Reclassify all merges."""
    db = get_db()
    merges = db.execute('SELECT id, source_address, target_address FROM merges').fetchall()

    for merge in merges:
        category, subcategory, desc = classify_merge(merge['source_address'], merge['target_address'])
        db.execute('''
            UPDATE merges SET category = ?, subcategory = ?, category_desc = ?
            WHERE id = ?
        ''', (category, subcategory, desc, merge['id']))

    db.commit()
    print(f'Reclassified {len(merges)} merges')


with app.app_context():
    init_db()
    load_merges_if_needed()
    load_original_sample()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
