import aiosqlite
import os
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / 'db' / 'schema.sql'

_db: aiosqlite.Connection | None = None
_db_path: str = ''


async def init_db(db_path: str) -> aiosqlite.Connection:
    global _db, _db_path
    _db_path = db_path
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute('PRAGMA journal_mode=WAL')
    await _db.execute('PRAGMA foreign_keys=ON')

    schema_sql = _SCHEMA_PATH.read_text(encoding='utf-8')
    await _db.executescript(schema_sql)
    await _db.commit()

    await _run_migrations(_db)
    return _db


async def _run_migrations(db: aiosqlite.Connection):
    """Run schema migrations for existing databases."""
    # Migration 2: add title and total_images to download_queue
    cursor = await db.execute(
        "SELECT COUNT(*) FROM pragma_table_info('download_queue') WHERE name='title'"
    )
    row = await cursor.fetchone()
    if row[0] == 0:
        await db.execute("ALTER TABLE download_queue ADD COLUMN title TEXT DEFAULT ''")
        await db.commit()

    cursor = await db.execute(
        "SELECT COUNT(*) FROM pragma_table_info('download_queue') WHERE name='total_images'"
    )
    row = await cursor.fetchone()
    if row[0] == 0:
        await db.execute("ALTER TABLE download_queue ADD COLUMN total_images INTEGER DEFAULT 0")
        await db.commit()

    # Migration 3: add photo_download table for photo_id → dir_name mapping
    cursor = await db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='photo_download'"
    )
    row = await cursor.fetchone()
    if row[0] == 0:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS photo_download (
                photo_id TEXT PRIMARY KEY,
                album_id TEXT NOT NULL,
                dir_name TEXT NOT NULL,
                title TEXT DEFAULT '',
                image_count INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()

    # Migration 4: add progress tracking columns to download_queue
    for col, typ in [
        ('current_photo_id', 'TEXT'),
        ('total_photos', 'INTEGER DEFAULT 0'),
        ('downloaded_photos', 'INTEGER DEFAULT 0'),
    ]:
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM pragma_table_info('download_queue') WHERE name=?",
            (col,)
        )
        row = await cursor.fetchone()
        if row[0] == 0:
            await db.execute(f"ALTER TABLE download_queue ADD COLUMN {col} {typ}")
            await db.commit()

    # Migration 5: add index on photo_download(album_id)
    await db.execute(
        'CREATE INDEX IF NOT EXISTS idx_photo_download_album_id ON photo_download(album_id)'
    )

    # Migration 6: add chapter_cache table for persistent chapter list
    cursor = await db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='chapter_cache'"
    )
    row = await cursor.fetchone()
    if row[0] == 0:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS chapter_cache (
                album_id TEXT NOT NULL,
                photo_id TEXT NOT NULL,
                title TEXT DEFAULT '',
                sort_order INTEGER DEFAULT 0,
                synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (album_id, photo_id)
            )
        ''')
        await db.commit()

    # Migration 7: add pub_date, update_date, description to subscription
    for col in ['pub_date', 'update_date', 'description']:
        cursor = await db.execute(
            f"SELECT COUNT(*) FROM pragma_table_info('subscription') WHERE name=?",
            (col,)
        )
        row = await cursor.fetchone()
        if row[0] == 0:
            await db.execute(f"ALTER TABLE subscription ADD COLUMN {col} TEXT DEFAULT ''")
            await db.commit()

    # Migration 8: add is_completed to subscription
    cursor = await db.execute(
        "SELECT COUNT(*) FROM pragma_table_info('subscription') WHERE name='is_completed'"
    )
    row = await cursor.fetchone()
    if row[0] == 0:
        await db.execute("ALTER TABLE subscription ADD COLUMN is_completed BOOLEAN DEFAULT 0")
        await db.commit()

    # Migration 9: add scheduler_config table
    cursor = await db.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='scheduler_config'"
    )
    row = await cursor.fetchone()
    if row[0] == 0:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS scheduler_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        ''')
        await db.execute(
            "INSERT OR IGNORE INTO scheduler_config (key, value) VALUES ('check_interval_minutes', '60')"
        )
        await db.execute(
            "INSERT OR IGNORE INTO scheduler_config (key, value) VALUES ('skip_completed', 'false')"
        )
        await db.commit()

    # Update schema version
    await db.execute(
        'INSERT OR IGNORE INTO schema_version (version) VALUES (9)'
    )
    await db.commit()


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError('Database not initialized. Call init_db() first.')
    return _db


def get_db_path() -> str:
    """Get DB path for synchronous access (use sqlite3 directly)."""
    if not _db_path:
        raise RuntimeError('Database not initialized. Call init_db() first.')
    return _db_path


async def close_db():
    global _db
    if _db is not None:
        await _db.close()
        _db = None
