-- account: JM account info
CREATE TABLE IF NOT EXISTS account (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    password_encrypted TEXT,
    cookies TEXT DEFAULT '{}',
    last_login_at DATETIME,
    is_active BOOLEAN DEFAULT 0
);

-- subscription: manga subscriptions
CREATE TABLE IF NOT EXISTS subscription (
    album_id TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    author TEXT DEFAULT '',
    last_known_photo_id TEXT DEFAULT '',
    auto_download BOOLEAN DEFAULT 1,
    check_interval_minutes INTEGER DEFAULT 60,
    last_checked_at DATETIME,
    has_update BOOLEAN DEFAULT 0,
    new_photo_ids TEXT DEFAULT '[]',
    pub_date TEXT DEFAULT '',
    update_date TEXT DEFAULT '',
    description TEXT DEFAULT '',
    is_completed BOOLEAN DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active'
);

-- scheduler_config: key-value config for scheduler
CREATE TABLE IF NOT EXISTS scheduler_config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- download_history: completed downloads
CREATE TABLE IF NOT EXISTS download_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jm_id TEXT NOT NULL,
    jm_type TEXT NOT NULL DEFAULT 'album',
    title TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    total_images INTEGER DEFAULT 0,
    downloaded_images INTEGER DEFAULT 0,
    file_path TEXT DEFAULT '',
    error_message TEXT,
    started_at DATETIME,
    completed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- download_queue: pending/active downloads
CREATE TABLE IF NOT EXISTS download_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jm_id TEXT NOT NULL,
    jm_type TEXT NOT NULL DEFAULT 'album',
    title TEXT DEFAULT '',
    priority INTEGER DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    progress_pct INTEGER DEFAULT 0,
    current_photo TEXT,
    current_image_index INTEGER,
    total_images INTEGER DEFAULT 0,
    error_message TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    started_at DATETIME,
    completed_at DATETIME
);

-- photo_download: maps photo_id to its album and directory name on disk
-- Enables fast "is_downloaded" checks for flat dir_rules (e.g. Bd_Pname)
CREATE TABLE IF NOT EXISTS photo_download (
    photo_id TEXT PRIMARY KEY,
    album_id TEXT NOT NULL,
    dir_name TEXT NOT NULL,
    title TEXT DEFAULT '',
    image_count INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO schema_version (version) VALUES (1);
