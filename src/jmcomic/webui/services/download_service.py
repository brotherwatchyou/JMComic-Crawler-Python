import asyncio
import shutil
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from jmcomic import JmDownloader, jm_log

from ..database import get_db, get_db_path


class WebUiDownloader(JmDownloader):
    """Downloader that updates DB progress in real-time for the web UI."""

    def __init__(self, option, task_id: int = 0, progress_queue: Optional[asyncio.Queue] = None):
        super().__init__(option)
        self.task_id = task_id
        self.progress_queue = progress_queue
        self._album_title = ''
        self._current_album_id = ''
        # Per-photo progress
        self._current_photo_title = ''
        self._current_photo_id = ''
        self._photo_total_images = 0
        self._photo_downloaded = 0
        # Album-level counters
        self._total_photos = 0
        self._downloaded_photos = 0
        self._total_images_all = 0

    def before_album(self, album):
        super().before_album(album)
        self._album_title = getattr(album, 'name', '') or ''
        self._current_album_id = getattr(album, 'album_id', '') or ''
        self._total_photos = len(getattr(album, 'episode_list', []) or [])
        self._downloaded_photos = 0
        self._total_images_all = 0
        # Set total_photos in DB
        self._update_db_field('total_photos', self._total_photos)

    def before_photo(self, photo):
        super().before_photo(photo)
        self._current_photo_title = getattr(photo, 'title', '') or getattr(photo, 'photo_id', '') or ''
        self._current_photo_id = getattr(photo, 'photo_id', '') or ''
        page_arr = getattr(photo, 'page_arr', None) or []
        self._photo_total_images = len(page_arr)
        self._photo_downloaded = 0

    def after_photo(self, photo):
        super().after_photo(photo)
        self._downloaded_photos += 1
        self._record_photo_dir(photo)

    def after_image(self, image, img_save_path):
        super().after_image(image, img_save_path)
        self._photo_downloaded += 1
        self._total_images_all += 1
        self._update_db_progress()

    def _update_db_progress(self):
        """Update download_queue progress in DB."""
        try:
            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            try:
                # Use album title if available, otherwise use current photo title
                title = self._album_title or self._current_photo_title
                conn.execute(
                    '''UPDATE download_queue SET
                       title = ?,
                       current_photo = ?,
                       current_photo_id = ?,
                       current_image_index = ?,
                       total_images = ?,
                       downloaded_photos = ?,
                       total_photos = ?,
                       progress_pct = ?
                       WHERE id = ?''',
                    (
                        title,
                        self._current_photo_title,
                        self._current_photo_id,
                        self._photo_downloaded,
                        self._photo_total_images,
                        self._downloaded_photos,
                        self._total_photos,
                        self._calc_progress_pct(),
                        self.task_id,
                    )
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def _update_db_field(self, field, value):
        """Update a single field in download_queue."""
        try:
            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    f'UPDATE download_queue SET {field} = ? WHERE id = ?',
                    (value, self.task_id)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def _calc_progress_pct(self):
        """Calculate progress percentage."""
        if self._total_photos > 0:
            # Album download: progress based on completed photos
            photo_pct = (self._downloaded_photos / self._total_photos) * 100
            if self._photo_total_images > 0:
                # Add partial progress from current photo
                photo_pct += (self._photo_downloaded / self._photo_total_images) / self._total_photos * 100
            return min(int(photo_pct), 99)
        elif self._photo_total_images > 0:
            # Single photo download
            return min(int((self._photo_downloaded / self._photo_total_images) * 100), 99)
        return 0

    def _record_photo_dir(self, photo):
        """Record photo_id -> dir_name mapping in photo_download table."""
        try:
            photo_id = getattr(photo, 'photo_id', '')
            album_id = getattr(photo, 'album_id', '') or self._current_album_id
            title = getattr(photo, 'title', '') or ''
            if not photo_id or not album_id:
                return

            dir_name = ''
            image_count = 0
            try:
                from_album = getattr(photo, 'from_album', None)
                save_dir = self.option.dir_rule.decide_image_save_dir(from_album, photo)
                if save_dir:
                    dir_name = Path(save_dir).name
                    if Path(save_dir).is_dir():
                        image_count = sum(
                            1 for f in Path(save_dir).iterdir()
                            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
                        )
            except Exception:
                pass

            if not dir_name:
                dir_name = getattr(photo, 'name', '') or photo_id

            db_path = get_db_path()
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    '''INSERT OR REPLACE INTO photo_download
                       (photo_id, album_id, dir_name, title, image_count)
                       VALUES (?, ?, ?, ?, ?)''',
                    (photo_id, album_id, dir_name, title, image_count)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            jm_log('webui.download', f'Failed to record photo dir: {e}')


class DownloadService:
    def __init__(self, option, progress_queue: Optional[asyncio.Queue] = None):
        self.option = option
        self.progress_queue = progress_queue
        self._active_downloads: dict = {}
        self._lock = threading.Lock()

    async def add_to_queue(self, jm_id: str, jm_type: str = 'album') -> int:
        db = await get_db()

        # Check if already in queue (pending or downloading)
        cursor = await db.execute(
            '''SELECT id FROM download_queue
               WHERE jm_id = ? AND status IN ('pending', 'downloading')''',
            (jm_id,)
        )
        existing = await cursor.fetchone()
        if existing:
            return existing['id']

        # For photo type, check if already downloaded
        if jm_type == 'photo':
            cursor = await db.execute(
                'SELECT photo_id FROM photo_download WHERE photo_id = ?',
                (jm_id,)
            )
            downloaded = await cursor.fetchone()
            if downloaded:
                return -1

        # Try to get title from subscription
        title = ''
        cursor = await db.execute(
            'SELECT title FROM subscription WHERE album_id = ?',
            (jm_id,)
        )
        row = await cursor.fetchone()
        if row and row['title']:
            title = row['title']

        cursor = await db.execute(
            '''INSERT INTO download_queue (jm_id, jm_type, status, title)
               VALUES (?, ?, 'pending', ?)''',
            (jm_id, jm_type, title)
        )
        await db.commit()
        task_id = cursor.lastrowid
        self._start_download(task_id, jm_id, jm_type)
        return task_id

    async def get_queue(self) -> list:
        db = await get_db()
        cursor = await db.execute(
            '''SELECT * FROM download_queue
               WHERE status IN ('pending', 'downloading', 'failed')
               ORDER BY
                 CASE status
                   WHEN 'downloading' THEN 0
                   WHEN 'pending' THEN 1
                   WHEN 'failed' THEN 2
                 END,
                 created_at DESC'''
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_active(self) -> list:
        db = await get_db()
        cursor = await db.execute(
            'SELECT * FROM download_queue WHERE status = ?',
            ('downloading',)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def cancel_task(self, task_id: int) -> bool:
        db = await get_db()
        await db.execute(
            'UPDATE download_queue SET status = ? WHERE id = ? AND status IN (?, ?)',
            ('cancelled', task_id, 'pending', 'downloading')
        )
        await db.commit()
        with self._lock:
            if task_id in self._active_downloads:
                self._active_downloads[task_id]['cancel'] = True
        return True

    async def get_history(self, limit: int = 50, offset: int = 0) -> list:
        db = await get_db()
        cursor = await db.execute(
            'SELECT * FROM download_history ORDER BY created_at DESC LIMIT ? OFFSET ?',
            (limit, offset)
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def clear_history(self) -> int:
        """Clear all download history. Returns number of deleted rows."""
        db = await get_db()
        cursor = await db.execute('DELETE FROM download_history')
        await db.commit()
        return cursor.rowcount

    async def cleanup_stale_queue(self) -> int:
        """Mark stale downloading/pending tasks as failed."""
        db = await get_db()
        # Find tasks that are downloading/pending but not in active_downloads
        cursor = await db.execute(
            '''SELECT id, status FROM download_queue
               WHERE status IN ('downloading', 'pending')'''
        )
        rows = await cursor.fetchall()
        cleaned = 0
        for row in rows:
            task_id = row['id']
            with self._lock:
                if task_id not in self._active_downloads:
                    await db.execute(
                        'UPDATE download_queue SET status = ? WHERE id = ?',
                        ('failed', task_id)
                    )
                    cleaned += 1
        if cleaned > 0:
            await db.commit()
        return cleaned

    async def dismiss_task(self, task_id: int) -> bool:
        """Remove a completed/failed/cancelled task from queue."""
        db = await get_db()
        await db.execute(
            'DELETE FROM download_queue WHERE id = ? AND status NOT IN (?, ?)',
            (task_id, 'pending', 'downloading')
        )
        await db.commit()
        return True

    def _start_download(self, task_id: int, jm_id: str, jm_type: str):
        def run():
            with self._lock:
                self._active_downloads[task_id] = {'cancel': False}

            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(self._execute_download(task_id, jm_id, jm_type))
            finally:
                loop.close()

            with self._lock:
                self._active_downloads.pop(task_id, None)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

    async def _execute_download(self, task_id: int, jm_id: str, jm_type: str):
        db = await get_db()
        now = datetime.now().isoformat()
        await db.execute(
            'UPDATE download_queue SET status = ?, started_at = ? WHERE id = ?',
            ('downloading', now, task_id)
        )
        await db.commit()

        try:
            downloader = WebUiDownloader(self.option, task_id, self.progress_queue)
            if jm_type == 'album':
                downloader.download_album(jm_id)
            else:
                downloader.download_photo(jm_id)

            now = datetime.now().isoformat()
            title = downloader._album_title or downloader._current_photo_title
            await db.execute(
                '''UPDATE download_queue SET status = ?, progress_pct = 100, completed_at = ?,
                   title = ?, total_images = ? WHERE id = ?''',
                ('completed', now, title, downloader._total_images_all, task_id)
            )
            await db.commit()

            await self._record_history(jm_id, jm_type, 'success', '', downloader)

        except Exception as e:
            now = datetime.now().isoformat()
            await db.execute(
                '''UPDATE download_queue SET status = ?, error_message = ?, completed_at = ? WHERE id = ?''',
                ('failed', str(e), now, task_id)
            )
            await db.commit()
            await self._record_history(jm_id, jm_type, 'failed', str(e), None)

    async def _record_history(self, jm_id, jm_type, status, error_msg, downloader):
        db = await get_db()
        title = ''
        total_images = 0
        downloaded_images = 0
        file_path = ''

        if downloader is not None:
            title = downloader._album_title
            downloaded_images = downloader._total_images_all

        now = datetime.now().isoformat()
        await db.execute(
            '''INSERT INTO download_history
               (jm_id, jm_type, title, status, total_images, downloaded_images,
                file_path, error_message, started_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (jm_id, jm_type, title, status, total_images, downloaded_images,
             file_path, error_msg, now, now)
        )
        await db.commit()

    # --- Delete methods ---

    def _get_base_dir(self) -> Optional[str]:
        try:
            return self.option.dir_rule.base_dir
        except Exception:
            return None

    def _has_album_level_in_rule(self) -> bool:
        try:
            dr = self.option.dir_rule
            parts = dr.split_rule_dsl(dr.rule_dsl)
            return any(p.startswith('A') for p in parts)
        except Exception:
            return False

    async def delete_photo(self, album_id: str, photo_id: str) -> dict:
        """Delete single chapter: disk files + DB records."""
        db = await get_db()

        cursor = await db.execute(
            'SELECT dir_name FROM photo_download WHERE photo_id = ?',
            (photo_id,)
        )
        row = await cursor.fetchone()

        deleted_files = False
        if row:
            dir_name = row['dir_name']
            base_dir = self._get_base_dir()
            if base_dir:
                for candidate in [
                    Path(base_dir) / album_id / dir_name,
                    Path(base_dir) / dir_name,
                ]:
                    if candidate.is_dir():
                        shutil.rmtree(candidate)
                        deleted_files = True
                        break

        await db.execute('DELETE FROM photo_download WHERE photo_id = ?', (photo_id,))
        await db.commit()

        return {'ok': True, 'deleted_files': deleted_files, 'photo_id': photo_id}

    async def delete_album(self, album_id: str) -> dict:
        """Delete entire album: all chapter files + all DB records."""
        db = await get_db()

        cursor = await db.execute(
            'SELECT photo_id, dir_name FROM photo_download WHERE album_id = ?',
            (album_id,)
        )
        rows = await cursor.fetchall()

        base_dir = self._get_base_dir()
        deleted_dirs = []

        if base_dir:
            if self._has_album_level_in_rule():
                album_dir = Path(base_dir) / album_id
                if album_dir.is_dir():
                    shutil.rmtree(album_dir)
                    deleted_dirs.append(str(album_dir))
            else:
                for row in rows:
                    dir_path = Path(base_dir) / row['dir_name']
                    if dir_path.is_dir():
                        shutil.rmtree(dir_path)
                        deleted_dirs.append(str(dir_path))

        await db.execute('DELETE FROM photo_download WHERE album_id = ?', (album_id,))
        await db.execute(
            "UPDATE download_queue SET status = 'cancelled' WHERE jm_id = ? AND status IN ('pending', 'downloading')",
            (album_id,)
        )
        await db.commit()

        return {'ok': True, 'deleted_dirs': deleted_dirs, 'photo_count': len(rows)}
