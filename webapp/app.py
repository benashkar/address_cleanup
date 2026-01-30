"""
Address Merge Review Web Application

A simple Flask app to review and approve/deny address merge suggestions.
Uses PostgreSQL for persistent storage.
"""

import os
import re
import csv
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, jsonify, g, send_file, Response
from pathlib import Path
from io import StringIO

app = Flask(__name__)

# PostgreSQL connection - use DATABASE_URL for Render, fallback to SQLite-style path for local
DATABASE_URL = os.environ.get('DATABASE_URL', '')
MERGES_CSV = os.environ.get('MERGES_CSV', '../reports/high_confidence_merges_20260130_001351.csv')


def get_db():
    """Get database connection."""
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
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
    cur = db.cursor()

    # Create tables
    cur.execute('''
        CREATE TABLE IF NOT EXISTS merges (
            id SERIAL PRIMARY KEY,
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            confidence REAL,
            source_address TEXT,
            target_address TEXT,
            source_raw TEXT,
            source_original TEXT,
            source_unit TEXT,
            source_unit_type TEXT,
            source_ext_source TEXT,
            target_raw TEXT,
            target_original TEXT,
            target_unit TEXT,
            target_unit_type TEXT,
            target_ext_source TEXT,
            category TEXT,
            subcategory TEXT,
            category_desc TEXT,
            status TEXT DEFAULT 'pending',
            reviewed_at TIMESTAMP,
            reviewer_notes TEXT
        )
    ''')

    cur.execute('''
        CREATE TABLE IF NOT EXISTS review_rules (
            id SERIAL PRIMARY KEY,
            category TEXT,
            subcategory TEXT,
            action TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            applied_count INTEGER DEFAULT 0
        )
    ''')

    # Create indexes if they don't exist
    cur.execute('CREATE INDEX IF NOT EXISTS idx_merges_status ON merges(status)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_merges_category ON merges(category)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_merges_subcategory ON merges(subcategory)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_merges_source ON merges(source_id)')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_merges_target ON merges(target_id)')

    db.commit()


def load_merges_if_needed():
    """Load merge suggestions from CSV if not already loaded."""
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT COUNT(*) as count FROM merges')
    count = cur.fetchone()['count']

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
                    row.get('source_raw', ''),
                    row.get('source_original', ''),
                    row.get('source_unit', ''),
                    row.get('source_unit_type', ''),
                    row.get('source_ext_source', ''),
                    row.get('target_raw', ''),
                    row.get('target_original', ''),
                    row.get('target_unit', ''),
                    row.get('target_unit_type', ''),
                    row.get('target_ext_source', ''),
                    category,
                    subcategory,
                    desc
                ))
                if len(batch) >= 1000:
                    cur.executemany('''
                        INSERT INTO merges (source_id, target_id, confidence,
                            source_address, target_address,
                            source_raw, source_original, source_unit, source_unit_type, source_ext_source,
                            target_raw, target_original, target_unit, target_unit_type, target_ext_source,
                            category, subcategory, category_desc)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ''', batch)
                    db.commit()
                    batch = []
                    if i % 10000 == 0:
                        print(f"  Loaded {i} records...")
            if batch:
                cur.executemany('''
                    INSERT INTO merges (source_id, target_id, confidence,
                        source_address, target_address,
                        source_raw, source_original, source_unit, source_unit_type, source_ext_source,
                        target_raw, target_original, target_unit, target_unit_type, target_ext_source,
                        category, subcategory, category_desc)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', batch)
        db.commit()
        cur.execute('SELECT COUNT(*) as count FROM merges')
        final_count = cur.fetchone()['count']
        print(f"Loaded {final_count} merge suggestions")


@app.route('/')
def index():
    """Main review interface."""
    return render_template('index.html')


@app.route('/api/stats')
def get_stats():
    """Get review statistics."""
    db = get_db()
    cur = db.cursor()
    stats = {}

    for status in ['pending', 'approved', 'rejected']:
        cur.execute('SELECT COUNT(*) as count FROM merges WHERE status = %s', (status,))
        stats[status] = cur.fetchone()['count']

    stats['total'] = sum(stats.values())
    return jsonify(stats)


@app.route('/api/categories')
def get_categories():
    """Get all categories with counts."""
    db = get_db()
    cur = db.cursor()

    cur.execute('''
        SELECT category, subcategory, category_desc, COUNT(*) as count,
               SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
               SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved,
               SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected
        FROM merges
        GROUP BY category, subcategory, category_desc
        ORDER BY count DESC
    ''')

    return jsonify([dict(row) for row in cur.fetchall()])


@app.route('/api/merges')
def get_merges():
    """Get paginated merge suggestions."""
    db = get_db()
    cur = db.cursor()

    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 20))
    status_filter = request.args.get('status', 'pending')
    category_filter = request.args.get('category', '')
    subcategory_filter = request.args.get('subcategory', '')

    offset = (page - 1) * per_page

    # Build query
    where_clauses = ['status = %s']
    params = [status_filter]

    if category_filter:
        where_clauses.append('category = %s')
        params.append(category_filter)

    if subcategory_filter:
        where_clauses.append('subcategory = %s')
        params.append(subcategory_filter)

    where_sql = ' AND '.join(where_clauses)

    # Get total count for pagination
    cur.execute(f'SELECT COUNT(*) as count FROM merges WHERE {where_sql}', params)
    total = cur.fetchone()['count']

    # Get merges (all data is now in the merges table)
    cur.execute(f'''
        SELECT
            id,
            source_id,
            target_id,
            confidence,
            source_address,
            target_address,
            category,
            subcategory,
            category_desc,
            status,
            reviewer_notes,
            source_raw,
            source_original,
            source_ext_source,
            source_unit,
            source_unit_type,
            target_raw,
            target_original,
            target_ext_source,
            target_unit,
            target_unit_type
        FROM merges
        WHERE {where_sql}
        ORDER BY id
        LIMIT %s OFFSET %s
    ''', params + [per_page, offset])

    return jsonify({
        'merges': [dict(row) for row in cur.fetchall()],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': (total + per_page - 1) // per_page if total > 0 else 1
    })


@app.route('/api/merges/<int:merge_id>/approve', methods=['POST'])
def approve_merge(merge_id):
    """Approve a merge suggestion."""
    db = get_db()
    cur = db.cursor()
    notes = request.json.get('notes', '') if request.json else ''

    cur.execute('''
        UPDATE merges
        SET status = 'approved', reviewed_at = CURRENT_TIMESTAMP, reviewer_notes = %s
        WHERE id = %s
    ''', (notes, merge_id))
    db.commit()

    return jsonify({'success': True})


@app.route('/api/merges/<int:merge_id>/reject', methods=['POST'])
def reject_merge(merge_id):
    """Reject a merge suggestion."""
    db = get_db()
    cur = db.cursor()
    notes = request.json.get('notes', '') if request.json else ''

    cur.execute('''
        UPDATE merges
        SET status = 'rejected', reviewed_at = CURRENT_TIMESTAMP, reviewer_notes = %s
        WHERE id = %s
    ''', (notes, merge_id))
    db.commit()

    return jsonify({'success': True})


@app.route('/api/merges/bulk', methods=['POST'])
def bulk_action():
    """Bulk approve/reject merges."""
    db = get_db()
    cur = db.cursor()
    data = request.json
    action = data.get('action')  # 'approve' or 'reject'
    merge_ids = data.get('ids', [])

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'Invalid action'}), 400

    status = 'approved' if action == 'approve' else 'rejected'

    # Use ANY for PostgreSQL array
    cur.execute('''
        UPDATE merges
        SET status = %s, reviewed_at = CURRENT_TIMESTAMP
        WHERE id = ANY(%s)
    ''', (status, merge_ids))
    db.commit()

    return jsonify({'success': True, 'updated': len(merge_ids)})


@app.route('/api/rules/apply', methods=['POST'])
def apply_rule():
    """Apply a rule to all matching merges in a category."""
    db = get_db()
    cur = db.cursor()
    data = request.json

    action = data.get('action')  # 'approve' or 'reject'
    category = data.get('category')
    subcategory = data.get('subcategory')

    if action not in ('approve', 'reject'):
        return jsonify({'error': 'Invalid action'}), 400

    status = 'approved' if action == 'approve' else 'rejected'

    # Build query
    where_clauses = ['status = %s']
    params = ['pending']

    if category:
        where_clauses.append('category = %s')
        params.append(category)

    if subcategory:
        where_clauses.append('subcategory = %s')
        params.append(subcategory)

    where_sql = ' AND '.join(where_clauses)

    # Count how many will be affected
    cur.execute(f'SELECT COUNT(*) as count FROM merges WHERE {where_sql}', params)
    count = cur.fetchone()['count']

    # Apply the rule
    cur.execute(f'''
        UPDATE merges
        SET status = %s, reviewed_at = CURRENT_TIMESTAMP, reviewer_notes = 'Bulk rule applied'
        WHERE {where_sql}
    ''', [status] + params)

    # Save the rule
    cur.execute('''
        INSERT INTO review_rules (category, subcategory, action, applied_count)
        VALUES (%s, %s, %s, %s)
    ''', (category, subcategory, action, count))

    db.commit()

    return jsonify({'success': True, 'updated': count})


@app.route('/api/rules')
def get_rules():
    """Get all saved rules."""
    db = get_db()
    cur = db.cursor()
    cur.execute('SELECT * FROM review_rules ORDER BY created_at DESC')
    return jsonify([dict(row) for row in cur.fetchall()])


@app.route('/api/export/approved')
def export_approved():
    """Export approved merges as CSV formatted for merge API."""
    db = get_db()
    cur = db.cursor()

    cur.execute('''
        SELECT source_id, target_id, confidence, source_address, target_address,
               category, subcategory, reviewed_at
        FROM merges WHERE status = 'approved'
        ORDER BY reviewed_at
    ''')
    merges = cur.fetchall()

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['merge_from_id', 'merge_to_id', 'confidence', 'source_address', 'target_address', 'category', 'subcategory', 'reviewed_at'])
    for row in merges:
        writer.writerow([row['source_id'], row['target_id'], row['confidence'],
                        row['source_address'], row['target_address'],
                        row['category'], row['subcategory'], row['reviewed_at']])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=approved_merges.csv'}
    )


@app.route('/api/export/approved/json')
def export_approved_json():
    """Export approved merges as JSON formatted for merge API."""
    db = get_db()
    cur = db.cursor()

    cur.execute('''
        SELECT source_id as merge_from_id, target_id as merge_to_id
        FROM merges WHERE status = 'approved'
        ORDER BY reviewed_at
    ''')
    merges = [dict(row) for row in cur.fetchall()]

    return jsonify({
        'total': len(merges),
        'merges': merges
    })


@app.route('/api/export/rejected')
def export_rejected():
    """Export rejected merges as CSV."""
    db = get_db()
    cur = db.cursor()

    cur.execute('''
        SELECT source_id, target_id, confidence, source_address, target_address,
               category, subcategory, reviewed_at
        FROM merges WHERE status = 'rejected'
        ORDER BY reviewed_at
    ''')
    merges = cur.fetchall()

    # Create CSV in memory
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['source_id', 'target_id', 'confidence', 'source_address', 'target_address', 'category', 'subcategory', 'reviewed_at'])
    for row in merges:
        writer.writerow([row['source_id'], row['target_id'], row['confidence'],
                        row['source_address'], row['target_address'],
                        row['category'], row['subcategory'], row['reviewed_at']])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-Disposition': 'attachment; filename=rejected_merges.csv'}
    )


with app.app_context():
    init_db()
    load_merges_if_needed()


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
