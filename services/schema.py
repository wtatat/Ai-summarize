import sqlite3

USER_COLUMNS = {
    'summary_notify_enabled': 'BOOLEAN DEFAULT 0',
    'summary_notify_interval_hours': 'INTEGER DEFAULT 2',
    'summary_notify_topics': "VARCHAR DEFAULT 'all'",
    'summary_notify_site': 'BOOLEAN DEFAULT 1',
    'summary_notify_last_sent_at': 'DATETIME',
    'ai_dialog_summary': "TEXT DEFAULT ''",
    'ai_dialog_history': "TEXT DEFAULT '[]'",
    'ai_dialog_updated_at': 'DATETIME',
}

def migrate_database(db_path):
    conn = sqlite3.connect(db_path)
    try:
        existing = {row[1] for row in conn.execute('PRAGMA table_info(users)')}
        for name, ddl in USER_COLUMNS.items():
            if name not in existing:
                conn.execute(f'ALTER TABLE users ADD COLUMN {name} {ddl}')
        conn.commit()
    finally:
        conn.close()
