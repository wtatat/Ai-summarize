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
    'avatar': "VARCHAR DEFAULT ''",
}

NEWS_COLUMNS = {
    'source_type': "VARCHAR DEFAULT 'website'",
    'source_icon': "VARCHAR DEFAULT '📰'",
    'topic': "VARCHAR DEFAULT 'all'",
    'full_text': "TEXT DEFAULT ''",
}

SOURCE_COLUMNS = {
    'is_active': 'BOOLEAN DEFAULT 1',
    'icon': "VARCHAR DEFAULT ''",
}

NOTIFICATION_COLUMNS = {
    'is_read': 'BOOLEAN DEFAULT 0',
}


def _migrate_table(conn, table, columns):
    existing = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')


def migrate_database(db_path):
    conn = sqlite3.connect(db_path)
    try:
        _migrate_table(conn, 'users', USER_COLUMNS)
        _migrate_table(conn, 'news', NEWS_COLUMNS)
        _migrate_table(conn, 'sources', SOURCE_COLUMNS)
        _migrate_table(conn, 'notifications', NOTIFICATION_COLUMNS)
        conn.commit()
    finally:
        conn.close()
