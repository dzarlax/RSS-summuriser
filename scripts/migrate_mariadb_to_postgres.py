#!/usr/bin/env python3
"""
Migrate data from MariaDB to PostgreSQL.

Usage:
    python scripts/migrate_mariadb_to_postgres.py \
        --mysql-url "mysql+pymysql://dzarlax:MangoTalker2017!@192.168.50.5:3306/newsdb" \
        --pg-url "postgresql://newsuser:newspass123@localhost:5432/newsdb"

Requirements:
    pip install pymysql psycopg2-binary
"""

import argparse
import sys
from datetime import datetime
from urllib.parse import urlparse

import pymysql
import psycopg2
import psycopg2.extras
import json


# Tables to migrate (in order, respecting foreign keys)
# Excluded: news_clusters, cluster_articles, task_queue (dead tables)
TABLES_ORDERED = [
    "sources",
    "articles",
    "categories",
    "article_categories",
    "daily_summaries",
    "settings",
    "processing_stats",
    "schedule_settings",
    "category_mapping",
    "extraction_patterns",
    "domain_stability",
    "ai_usage_tracking",
    "extraction_attempts",
]

# Tables with SERIAL (auto-increment) primary keys that need sequence reset
SERIAL_TABLES = [
    ("sources", "id"),
    ("articles", "id"),
    ("categories", "id"),
    ("article_categories", "id"),
    ("daily_summaries", "id"),
    ("processing_stats", "id"),
    ("schedule_settings", "id"),
    ("category_mapping", "id"),
    ("extraction_patterns", "id"),
    ("domain_stability", "id"),
    ("ai_usage_tracking", "id"),
    ("extraction_attempts", "id"),
]

# Skip these tables entirely
SKIP_TABLES = {"news_clusters", "cluster_articles", "task_queue"}

# Columns that are JSON in MariaDB and should be JSONB in PostgreSQL
JSON_COLUMNS = {
    "sources": ["config"],
    "articles": ["media_files", "ad_markers"],
    "schedule_settings": ["weekdays", "task_config"],
    "settings": ["value"],
    "extraction_patterns": [],
    "domain_stability": ["reanalysis_triggers"],
    "extraction_attempts": ["ai_analysis"],
    "ai_usage_tracking": ["analysis_result"],
}


def parse_mysql_url(url: str):
    """Parse MySQL URL into connection params."""
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 3306,
        "user": parsed.username or "root",
        "password": parsed.password or "",
        "database": parsed.path.lstrip("/") or "newsdb",
        "charset": "utf8mb4",
    }


def parse_pg_url(url: str):
    """Parse PostgreSQL URL into connection string."""
    # Remove driver prefix if present
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    return url


def get_mysql_columns(mysql_cur, table: str) -> list:
    """Get column names for a table."""
    mysql_cur.execute(f"DESCRIBE `{table}`")
    return [row[0] for row in mysql_cur.fetchall()]


_PG_BOOLEAN_COLS: dict[str, set[str]] = {}


def load_pg_boolean_columns(pg_cur):
    """Detect all boolean columns from PostgreSQL information_schema."""
    pg_cur.execute("""
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND data_type = 'boolean'
    """)
    for table_name, col_name in pg_cur.fetchall():
        _PG_BOOLEAN_COLS.setdefault(table_name, set()).add(col_name)


def convert_value(value, col_name: str, table: str):
    """Convert a MySQL value for PostgreSQL compatibility."""
    if value is None:
        return None

    # Handle JSON columns
    json_cols = JSON_COLUMNS.get(table, [])
    if col_name in json_cols:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                return json.dumps(parsed)
            except (json.JSONDecodeError, TypeError):
                return value
        elif isinstance(value, (dict, list)):
            return json.dumps(value)

    # Handle boolean columns (MariaDB tinyint(1) → Python bool)
    if col_name in _PG_BOOLEAN_COLS.get(table, set()) and isinstance(value, int):
        return bool(value)

    return value


def migrate_table(mysql_cur, pg_cur, table: str, batch_size: int = 1000):
    """Migrate a single table from MariaDB to PostgreSQL."""
    if table in SKIP_TABLES:
        print(f"  SKIP {table} (dead table)")
        return 0

    # Get columns
    columns = get_mysql_columns(mysql_cur, table)

    # Count rows
    mysql_cur.execute(f"SELECT COUNT(*) FROM `{table}`")
    total = mysql_cur.fetchone()[0]

    if total == 0:
        print(f"  {table}: 0 rows (empty)")
        return 0

    # Read all data from MariaDB
    mysql_cur.execute(f"SELECT * FROM `{table}`")
    rows = mysql_cur.fetchall()

    # Convert values
    converted_rows = []
    for row in rows:
        converted = []
        for i, val in enumerate(row):
            converted.append(convert_value(val, columns[i], table))
        converted_rows.append(tuple(converted))

    # Build INSERT statement
    col_list = ", ".join(f'"{c}"' if c == "key" else c for c in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    insert_sql = f'INSERT INTO {table} ({col_list}) VALUES ({placeholders})'

    # Insert in batches
    inserted = 0
    for i in range(0, len(converted_rows), batch_size):
        batch = converted_rows[i : i + batch_size]
        psycopg2.extras.execute_batch(pg_cur, insert_sql, batch)
        inserted += len(batch)

    print(f"  {table}: {inserted}/{total} rows migrated")
    return inserted


def reset_sequences(pg_cur):
    """Reset PostgreSQL sequences to match max IDs."""
    for table, pk in SERIAL_TABLES:
        try:
            pg_cur.execute(f"SELECT MAX({pk}) FROM {table}")
            max_id = pg_cur.fetchone()[0]
            if max_id is not None:
                seq_name = f"{table}_{pk}_seq"
                pg_cur.execute(f"SELECT setval('{seq_name}', {max_id})")
                print(f"  Sequence {seq_name} → {max_id}")
        except Exception as e:
            print(f"  WARNING: Could not reset sequence for {table}: {e}")


def main():
    parser = argparse.ArgumentParser(description="Migrate data from MariaDB to PostgreSQL")
    parser.add_argument("--mysql-url", required=True, help="MySQL connection URL")
    parser.add_argument("--pg-url", required=True, help="PostgreSQL connection URL")
    parser.add_argument("--batch-size", type=int, default=1000, help="Insert batch size")
    parser.add_argument("--skip-extraction-attempts", action="store_true",
                        help="Skip extraction_attempts table (81K+ rows of logs)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be migrated without writing")
    args = parser.parse_args()

    # Connect to MariaDB
    mysql_params = parse_mysql_url(args.mysql_url)
    print(f"Connecting to MariaDB: {mysql_params['host']}:{mysql_params['port']}/{mysql_params['database']}")
    mysql_conn = pymysql.connect(**mysql_params)
    mysql_cur = mysql_conn.cursor()

    # Connect to PostgreSQL
    pg_url = parse_pg_url(args.pg_url)
    print(f"Connecting to PostgreSQL: {pg_url.split('@')[1] if '@' in pg_url else pg_url}")
    pg_conn = psycopg2.connect(pg_url)
    pg_cur = pg_conn.cursor()

    if args.dry_run:
        print("\n=== DRY RUN — no data will be written ===\n")
        for table in TABLES_ORDERED:
            if table in SKIP_TABLES:
                print(f"  SKIP {table}")
                continue
            if args.skip_extraction_attempts and table == "extraction_attempts":
                print(f"  SKIP {table} (--skip-extraction-attempts)")
                continue
            mysql_cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            count = mysql_cur.fetchone()[0]
            print(f"  {table}: {count} rows")
        mysql_conn.close()
        pg_conn.close()
        return

    load_pg_boolean_columns(pg_cur)
    tables_to_migrate = TABLES_ORDERED.copy()
    if args.skip_extraction_attempts:
        tables_to_migrate = [t for t in tables_to_migrate if t != "extraction_attempts"]

    # Disable triggers during import for performance
    pg_cur.execute("SET session_replication_role = 'replica'")

    print(f"\nMigrating {len(tables_to_migrate)} tables...")
    total_rows = 0
    start_time = datetime.now()

    try:
        for table in tables_to_migrate:
            rows = migrate_table(mysql_cur, pg_cur, table, args.batch_size)
            total_rows += rows

        print("\nResetting sequences...")
        reset_sequences(pg_cur)

        # Re-enable triggers
        pg_cur.execute("SET session_replication_role = 'origin'")

        pg_conn.commit()
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\nDone! Migrated {total_rows} rows in {elapsed:.1f}s")

    except Exception as e:
        pg_conn.rollback()
        print(f"\nERROR: Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    finally:
        mysql_cur.close()
        mysql_conn.close()
        pg_cur.close()
        pg_conn.close()


if __name__ == "__main__":
    main()
