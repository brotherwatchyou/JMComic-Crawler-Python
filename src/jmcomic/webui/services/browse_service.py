import os
import re
import time
from pathlib import Path
from typing import List, Optional

from ..database import get_db


class BrowseService:
    # In-memory cache for chapter lists fetched from JM server
    _chapters_cache: dict = {}  # {album_id: {'chapters': [...], 'timestamp': float}}
    _cache_ttl = 300  # 5 minutes

    def __init__(self, option):
        self.option = option

    async def list_bookshelf(self, subscriptions: list) -> List[dict]:
        """统一书架：合并订阅数据和已下载数据。纯 DB 读取，无磁盘扫描。"""
        # Single aggregate query: get chapter count per album from photo_download
        dl_counts = self._get_all_download_counts()

        bookshelf = []
        for sub in subscriptions:
            album_id = sub['album_id']
            count = dl_counts.get(album_id, 0)

            bookshelf.append({
                'album_id': album_id,
                'title': sub['title'] or album_id,
                'author': sub['author'] or '',
                'is_downloaded': count > 0,
                'chapter_count': count,
                'has_update': sub.get('has_update', False),
                'auto_download': sub.get('auto_download', False),
                'new_photo_ids': sub.get('new_photo_ids', []),
                'is_completed': sub.get('is_completed', False),
                'status': sub.get('status', 'active'),
            })

        # Add downloaded albums not in subscriptions
        sub_ids = {sub['album_id'] for sub in subscriptions}
        for album_id, count in dl_counts.items():
            if album_id not in sub_ids and album_id:
                # Get title from chapter_cache if available
                title = self._get_cached_album_title(album_id) or album_id
                bookshelf.append({
                    'album_id': album_id,
                    'title': title,
                    'author': '',
                    'is_downloaded': True,
                    'chapter_count': count,
                    'has_update': False,
                    'auto_download': False,
                    'is_completed': False,
                    'status': 'downloaded',
                })

        return bookshelf

    def list_albums(self) -> List[dict]:
        base_dir = self._get_base_dir()
        disk_dirs = self._scan_image_dirs(base_dir) if base_dir else {}
        albums = []
        for album_id, chapters in self._discover_album_dirs(disk_dirs).items():
            albums.append({
                'album_id': album_id,
                'title': chapters[0].get('album_title', album_id) if chapters else album_id,
                'author': '',
                'chapter_count': len(chapters),
                'path': '',
            })
        return albums

    async def get_album(self, album_id: str, sub_info: Optional[dict] = None) -> Optional[dict]:
        base_dir = self._get_base_dir()
        disk_dirs = self._scan_image_dirs(base_dir) if base_dir else {}
        chapters = await self._match_chapters_for_album(album_id, disk_dirs)

        title = album_id
        author = ''
        if sub_info:
            title = sub_info.get('title') or album_id
            author = sub_info.get('author', '')

        return {
            'album_id': album_id,
            'title': title,
            'author': author,
            'is_downloaded': any(ch['is_downloaded'] for ch in chapters),
            'chapter_count': sum(1 for ch in chapters if ch['is_downloaded']),
            'chapters': chapters,
            'path': '',
        }

    def get_chapters_from_server(self, album_id: str, photo_dir_map: dict = None,
                                 force_refresh: bool = False) -> List[dict]:
        """Fetch chapter list from JM server with in-memory cache.
        photo_dir_map is pre-loaded in async context to avoid aiosqlite conflicts.
        """
        if photo_dir_map is None:
            photo_dir_map = {}

        # Check cache (unless forced refresh)
        cached = self._chapters_cache.get(album_id)
        if not force_refresh and cached and (time.time() - cached['timestamp']) < self._cache_ttl:
            return self._refresh_download_status(cached['chapters'], photo_dir_map)

        chapters = []
        try:
            client = self.option.new_jm_client()
            album = client.get_album_detail(album_id)
            base_dir = self._get_base_dir()

            # Save album metadata to subscription table (if subscribed)
            self._upsert_album_meta(album_id, album)

            if self._has_album_level_in_rule():
                # With album level: base_dir/album_id/photo_id
                for idx, episode in enumerate(album.episode_list):
                    photo_id = episode[0]
                    sort_order = episode[1] if len(episode) > 1 else str(idx + 1)
                    photo_title = episode[2] if len(episode) > 2 else ''
                    if not photo_title:
                        photo_title = f'第{sort_order}话'
                    chapter_path = Path(base_dir) / album_id / photo_id if base_dir else None
                    is_downloaded = chapter_path and chapter_path.is_dir() and self._dir_has_images(chapter_path)
                    image_count = self._count_images(chapter_path) if is_downloaded else 0

                    chapters.append({
                        'photo_id': photo_id,
                        'title': photo_title,
                        'index': int(sort_order) if str(sort_order).isdigit() else idx + 1,
                        'image_count': image_count,
                        'is_downloaded': is_downloaded,
                        'path': str(chapter_path) if is_downloaded else '',
                    })
            else:
                # Without album level: use pre-loaded DB mapping first, then disk scan
                disk_dirs = self._scan_image_dirs(base_dir) if base_dir else {}

                for idx, episode in enumerate(album.episode_list):
                    photo_id = episode[0]
                    sort_order = episode[1] if len(episode) > 1 else str(idx + 1)
                    photo_title = episode[2] if len(episode) > 2 else ''
                    if not photo_title:
                        photo_title = f'第{sort_order}话'

                    # 1. Check DB mapping first (fast, no API)
                    if photo_id in photo_dir_map:
                        dir_name = photo_dir_map[photo_id]
                        chapter_path = Path(base_dir) / dir_name if base_dir else None
                        is_downloaded = chapter_path and chapter_path.is_dir() and self._dir_has_images(chapter_path)
                    # 2. Check disk_dirs by photo_id
                    elif photo_id in disk_dirs:
                        chapter_path = disk_dirs[photo_id]
                        is_downloaded = True
                    else:
                        # 3. Try candidate name patterns
                        chapter_path, is_downloaded = self._find_chapter_by_dir_rule(
                            album, photo_id, idx, base_dir, disk_dirs
                        )

                    image_count = self._count_images(chapter_path) if is_downloaded else 0
                    chapters.append({
                        'photo_id': photo_id,
                        'title': photo_title,
                        'index': int(sort_order) if str(sort_order).isdigit() else idx + 1,
                        'image_count': image_count,
                        'is_downloaded': is_downloaded,
                        'path': str(chapter_path) if is_downloaded else '',
                    })

                    # Backfill DB mapping for future fast lookups (skip album-level dirs)
                    if is_downloaded and chapter_path and photo_id not in photo_dir_map:
                        dir_name = chapter_path.name
                        album_title = (album.title or '').strip().lower()
                        if dir_name.strip().lower() != album_title:
                            self._backfill_photo_dir(photo_id, album_id, dir_name, photo_title, image_count)
        except Exception:
            pass

        # Cache the result (memory + DB)
        if chapters:
            self._chapters_cache[album_id] = {
                'chapters': chapters,
                'timestamp': time.time(),
            }
            self.save_chapters_to_cache(album_id, chapters)
        return chapters

    def _backfill_photo_dir(self, photo_id, album_id, dir_name, title, image_count):
        """Write photo_id → dir_name mapping to DB using sync sqlite3.
        Called from run_in_executor, so must not use aiosqlite.
        """
        import sqlite3
        try:
            db_path = self._get_db_path()
            if not db_path:
                return
            conn = sqlite3.connect(db_path)
            try:
                conn.execute(
                    '''INSERT OR IGNORE INTO photo_download
                       (photo_id, album_id, dir_name, title, image_count)
                       VALUES (?, ?, ?, ?, ?)''',
                    (photo_id, album_id, dir_name, title or dir_name, image_count)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def _get_db_path(self) -> Optional[str]:
        """Get the database file path from the app config."""
        try:
            import os
            path = os.path.expanduser('~/.jmcomic/webui.db')
            if os.path.exists(path):
                return path
        except Exception:
            pass
        return None

    def _refresh_download_status(self, cached_chapters: List[dict], photo_dir_map: dict) -> List[dict]:
        """Re-check disk/download status for cached chapters without hitting JM API."""
        base_dir = self._get_base_dir()
        if not base_dir:
            return cached_chapters

        for ch in cached_chapters:
            photo_id = ch['photo_id']
            # Check DB mapping first
            if photo_id in photo_dir_map:
                dir_name = photo_dir_map[photo_id]
                chapter_path = Path(base_dir) / dir_name
                ch['is_downloaded'] = chapter_path.is_dir() and self._dir_has_images(chapter_path)
            elif ch.get('path'):
                chapter_path = Path(ch['path'])
                ch['is_downloaded'] = chapter_path.is_dir() and self._dir_has_images(chapter_path)
            if ch['is_downloaded'] and ch.get('path'):
                ch['image_count'] = self._count_images(Path(ch['path']))
        return cached_chapters

    def get_downloaded_photo_ids(self, album_id: str) -> List[str]:
        """Get list of downloaded photo_ids for an album from DB. Lightweight, no API call."""
        import sqlite3
        try:
            db_path = self._get_db_path()
            if not db_path:
                return []
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    'SELECT photo_id FROM photo_download WHERE album_id = ?',
                    (album_id,)
                )
                return [row['photo_id'] for row in cursor.fetchall()]
            finally:
                conn.close()
        except Exception:
            return []

    def save_chapters_to_cache(self, album_id: str, chapters: List[dict]):
        """Persist chapter list to DB chapter_cache table."""
        import sqlite3
        try:
            db_path = self._get_db_path()
            if not db_path:
                return
            conn = sqlite3.connect(db_path)
            try:
                conn.execute('DELETE FROM chapter_cache WHERE album_id = ?', (album_id,))
                for ch in chapters:
                    conn.execute(
                        '''INSERT INTO chapter_cache (album_id, photo_id, title, sort_order)
                           VALUES (?, ?, ?, ?)''',
                        (album_id, ch['photo_id'], ch.get('title', ''), ch.get('index', 0))
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def get_cached_chapters(self, album_id: str) -> List[dict]:
        """Read chapter list from DB cache, merged with download status.
        Pure DB read, no remote API, no filesystem scan.
        """
        import sqlite3
        try:
            db_path = self._get_db_path()
            if not db_path:
                return []
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                # Read cached chapter list
                cursor = conn.execute(
                    'SELECT photo_id, title, sort_order FROM chapter_cache WHERE album_id = ? ORDER BY sort_order',
                    (album_id,)
                )
                cached = cursor.fetchall()
                if not cached:
                    return []

                # Read download status
                cursor = conn.execute(
                    'SELECT photo_id, dir_name, image_count FROM photo_download WHERE album_id = ?',
                    (album_id,)
                )
                dl_map = {row['photo_id']: dict(row) for row in cursor.fetchall()}

                base_dir = self._get_base_dir()
                chapters = []
                for row in cached:
                    photo_id = row['photo_id']
                    dl = dl_map.get(photo_id)
                    is_downloaded = dl is not None
                    image_count = dl['image_count'] if dl else 0
                    path = ''
                    if dl:
                        dir_name = dl['dir_name']
                        path = str(Path(base_dir) / dir_name) if base_dir else ''

                    chapters.append({
                        'photo_id': photo_id,
                        'title': row['title'] or photo_id,
                        'index': row['sort_order'],
                        'image_count': image_count,
                        'is_downloaded': is_downloaded,
                        'path': path,
                    })
                return chapters
            finally:
                conn.close()
        except Exception:
            return []

    def _get_photo_dir_map_from_db(self, album_id: str) -> dict:
        """Synchronous DB lookup: photo_id → dir_name for a given album.
        Uses sync sqlite3 to avoid aiosqlite event loop conflicts.
        """
        import sqlite3
        try:
            db_path = self._get_db_path()
            if not db_path:
                return {}
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    'SELECT photo_id, dir_name FROM photo_download WHERE album_id = ?',
                    (album_id,)
                )
                rows = cursor.fetchall()
                return {row['photo_id']: row['dir_name'] for row in rows}
            finally:
                conn.close()
        except Exception:
            return {}

    async def _async_get_photo_dir_map(self, album_id: str) -> dict:
        """Query photo_download table for photo_id → dir_name mapping."""
        db = await get_db()
        cursor = await db.execute(
            'SELECT photo_id, dir_name FROM photo_download WHERE album_id = ?',
            (album_id,)
        )
        rows = await cursor.fetchall()
        return {row['photo_id']: row['dir_name'] for row in rows}

    def _find_chapter_by_dir_rule(self, album, photo_id: str, episode_idx: int,
                                   base_dir: str, disk_dirs: dict):
        """Try to find a chapter directory using dir_rule path computation.
        Returns (Path_or_None, is_downloaded)."""
        album_name = album.title or album.album_id
        sort_order = ''
        episode = album.episode_list[episode_idx] if episode_idx < len(album.episode_list) else None
        if episode:
            sort_order = episode[1] if len(episode) > 1 else str(episode_idx + 1)

        # Build strict candidates - must contain chapter number or title
        candidates = []
        if episode and len(episode) > 2 and episode[2]:
            candidates.append(episode[2])

        if sort_order and str(sort_order).isdigit():
            idx = int(sort_order)
            candidates.extend([
                f'{album_name}第{idx}话',
                f'{album_name} 第{idx}话',
                f'{album_name} {idx}',
                f'{album_name}{idx}',
                f'{album_name}-{idx}',
                f'{album_name}第{idx}话 ',
            ])

        album_dir_name = album_name.lower()
        for candidate in candidates:
            # Skip if candidate is just the album name (not a chapter dir)
            if candidate.strip().lower() == album_dir_name:
                continue
            p = Path(base_dir) / candidate
            if p.is_dir() and self._dir_has_images(p):
                return p, True
            if candidate in disk_dirs:
                return disk_dirs[candidate], True

        return None, False

    async def get_chapter_images(self, album_id: str, chapter_name: str) -> List[str]:
        """Find images for a chapter. chapter_name is photo_id or dir name."""
        chapter_dir = await self._find_chapter_dir_async(album_id, chapter_name)
        if not chapter_dir or not chapter_dir.is_dir():
            return []
        images = []
        for f in sorted(chapter_dir.iterdir()):
            if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'):
                images.append(f.name)
        return images

    async def get_image_path(self, album_id: str, chapter_name: str, image_name: str) -> Optional[str]:
        chapter_dir = await self._find_chapter_dir_async(album_id, chapter_name)
        if not chapter_dir:
            return None
        path = chapter_dir / image_name
        if path.is_file():
            return str(path)
        return None

    # --- Filesystem scanning (fast, no API calls) ---

    def _scan_image_dirs(self, base_dir: str) -> dict:
        """Scan base_dir for all directories containing images.
        Returns {dir_name: Path} for up to 2 levels deep.
        """
        result = {}
        if not base_dir or not os.path.isdir(base_dir):
            return result

        base = Path(base_dir)
        try:
            for entry in base.iterdir():
                if not entry.is_dir() or entry.name.startswith('.'):
                    continue
                if self._dir_has_images(entry):
                    result[entry.name] = entry
                # Second level (for album-level rules like Bd_Aid_Ptitle)
                try:
                    for sub in entry.iterdir():
                        if not sub.is_dir() or sub.name.startswith('.'):
                            continue
                        if self._dir_has_images(sub):
                            result[sub.name] = sub
                except (OSError, PermissionError):
                    pass
        except (OSError, PermissionError):
            pass
        return result

    async def _match_chapters_for_album(self, album_id: str, disk_dirs: dict) -> List[dict]:
        """Match downloaded chapter directories to an album."""
        base_dir = self._get_base_dir()
        if not base_dir:
            return []

        if self._has_album_level_in_rule():
            # Rules like Bd_Aid_Ptitle: base_dir/album_id/...
            album_dir = Path(base_dir) / album_id
            if album_dir.is_dir():
                return self._scan_chapter_dirs(album_dir)
            return []
        else:
            # Flat rules: use photo_download DB mapping
            return await self._find_chapters_from_db(album_id, base_dir, disk_dirs)

    async def _find_chapters_from_db(self, album_id: str, base_dir: str, disk_dirs: dict) -> List[dict]:
        """Find downloaded chapters for a flat dir_rule using DB mapping."""
        db = await get_db()
        cursor = await db.execute(
            'SELECT photo_id, dir_name, title, image_count FROM photo_download WHERE album_id = ?',
            (album_id,)
        )
        rows = await cursor.fetchall()

        if rows:
            chapters = []
            for idx, row in enumerate(rows):
                dir_name = row['dir_name']
                chapter_path = Path(base_dir) / dir_name
                is_downloaded = chapter_path.is_dir() and self._dir_has_images(chapter_path)
                image_count = self._count_images(chapter_path) if is_downloaded else 0

                chapters.append({
                    'photo_id': row['photo_id'],
                    'title': row['title'] or dir_name,
                    'index': idx + 1,
                    'image_count': image_count,
                    'is_downloaded': is_downloaded,
                    'path': str(chapter_path) if is_downloaded else '',
                })
            return chapters

        # No DB records — check if album_id itself is a directory name
        album_dir = Path(base_dir) / album_id
        if album_dir.is_dir() and self._dir_has_images(album_dir):
            image_count = self._count_images(album_dir)
            return [{
                'photo_id': album_id,
                'title': album_id,
                'index': 1,
                'image_count': image_count,
                'is_downloaded': True,
                'path': str(album_dir),
            }]

        # No DB records and no direct match — return empty.
        # Chapters will be populated when user opens the album detail page
        # (get_chapters_from_server will be called then).
        return []

    async def _find_chapter_dir_async(self, album_id: str, chapter_name: str) -> Optional[Path]:
        """Find the actual directory for a chapter on disk (async version)."""
        base_dir = self._get_base_dir()
        if not base_dir:
            return None

        # 1. Direct path with album level: base_dir/album_id/chapter_name
        p = Path(base_dir) / album_id / chapter_name
        if p.is_dir() and self._dir_has_images(p):
            return p

        # 2. Direct path without album level: base_dir/chapter_name
        p = Path(base_dir) / chapter_name
        if p.is_dir() and self._dir_has_images(p):
            return p

        # 3. Try DB mapping: chapter_name might be a photo_id, look up its dir_name
        dir_name = await self._async_lookup_dir_name(chapter_name)
        if dir_name:
            p = Path(base_dir) / dir_name
            if p.is_dir() and self._dir_has_images(p):
                return p

        # 4. Search in disk dirs
        disk_dirs = self._scan_image_dirs(base_dir)
        if chapter_name in disk_dirs:
            return disk_dirs[chapter_name]

        # 5. Only do fuzzy match for non-numeric names (avoid photo_id false matches)
        if not chapter_name.isdigit():
            for name, path in disk_dirs.items():
                if chapter_name in name and len(chapter_name) > len(name) * 0.5:
                    return path

        return None

    async def _async_lookup_dir_name(self, photo_id: str) -> Optional[str]:
        """Look up dir_name from photo_download table by photo_id."""
        try:
            db = await get_db()
            cursor = await db.execute(
                'SELECT dir_name FROM photo_download WHERE photo_id = ?',
                (photo_id,)
            )
            row = await cursor.fetchone()
            return row['dir_name'] if row else None
        except Exception:
            return None

    def _discover_album_dirs(self, disk_dirs: dict) -> dict:
        """Discover downloaded albums from filesystem (for unsubscribed albums)."""
        base_dir = self._get_base_dir()
        if not base_dir:
            return {}

        result = {}
        if self._has_album_level_in_rule():
            for entry in sorted(Path(base_dir).iterdir()):
                if not entry.is_dir() or entry.name.startswith('.'):
                    continue
                chapters = self._scan_chapter_dirs(entry)
                if chapters:
                    result[entry.name] = chapters
        return result

    def _scan_chapter_dirs(self, album_dir: Path) -> List[dict]:
        """Scan an album directory for chapter subdirectories."""
        chapters = []
        entries = []
        try:
            for entry in album_dir.iterdir():
                if not entry.is_dir() or entry.name.startswith('.'):
                    continue
                image_count = self._count_images(entry)
                if image_count == 0:
                    continue
                entries.append((entry, image_count))
        except (OSError, PermissionError):
            return []

        def sort_key(item):
            name = item[0].name
            nums = re.findall(r'\d+', name)
            if nums:
                return (0, int(nums[-1]), name)
            return (1, 0, name)
        entries.sort(key=sort_key)

        for idx, (entry, image_count) in enumerate(entries):
            chapters.append({
                'photo_id': entry.name,
                'title': entry.name,
                'index': idx + 1,
                'image_count': image_count,
                'is_downloaded': True,
                'path': str(entry),
            })
        return chapters

    # --- Helpers ---

    def _has_album_level_in_rule(self) -> bool:
        dr = self.option.dir_rule
        parts = dr.split_rule_dsl(dr.rule_dsl)
        return any(p.startswith('A') for p in parts)

    def _dir_has_images(self, dir_path: Path) -> bool:
        try:
            return any(
                f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
                for f in dir_path.iterdir()
            )
        except (OSError, PermissionError):
            return False

    def _count_images(self, dir_path: Optional[Path]) -> int:
        if not dir_path or not dir_path.is_dir():
            return 0
        try:
            return sum(
                1 for f in dir_path.iterdir()
                if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp')
            )
        except (OSError, PermissionError):
            return 0

    def repair_data(self) -> dict:
        """一键修复: 扫描磁盘与DB的一致性，修复不匹配的记录"""
        import sqlite3
        import hashlib

        base_dir = self._get_base_dir()
        if not base_dir:
            return {'ok': False, 'error': '未配置下载目录'}

        db_path = self._get_db_path()
        if not db_path:
            return {'ok': False, 'error': '数据库不存在'}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Phase 1: 获取所有 DB 记录
            cursor = conn.execute(
                'SELECT photo_id, album_id, dir_name, title, image_count FROM photo_download'
            )
            db_records = cursor.fetchall()

            scanned_dirs = 0
            added = []
            updated = []
            removed = []
            duplicates = []

            # Phase 2: 检查 DB 记录对应的磁盘目录
            disk_dirs = self._scan_image_dirs(base_dir)
            scanned_dirs = len(disk_dirs)

            # 建立 dir_name → photo_id 的反向映射，检测重复
            dir_to_photos = {}
            for row in db_records:
                dn = row['dir_name']
                dir_to_photos.setdefault(dn, []).append(row['photo_id'])

            for dn, pids in dir_to_photos.items():
                if len(pids) > 1:
                    duplicates.append({'dir_name': dn, 'photo_ids': pids})

            for row in db_records:
                dir_name = row['dir_name']
                album_id = row['album_id']
                photo_id = row['photo_id']

                # 检查磁盘目录是否存在
                chapter_path = Path(base_dir) / dir_name
                album_chapter_path = Path(base_dir) / album_id / dir_name

                if chapter_path.is_dir() and self._dir_has_images(chapter_path):
                    continue
                if album_chapter_path.is_dir() and self._dir_has_images(album_chapter_path):
                    continue

                # 尝试模糊匹配
                matched = self._try_match_disk_dir(dir_name, album_id, disk_dirs)
                if matched:
                    conn.execute(
                        'UPDATE photo_download SET dir_name = ? WHERE photo_id = ?',
                        (matched.name, photo_id)
                    )
                    updated.append({'photo_id': photo_id, 'old_dir': dir_name, 'new_dir': matched.name})
                else:
                    conn.execute(
                        'DELETE FROM photo_download WHERE photo_id = ?', (photo_id,)
                    )
                    removed.append({'photo_id': photo_id, 'dir_name': dir_name})

            conn.commit()

            # Phase 3: 检查磁盘有但 DB 无记录的目录
            db_dir_names = {row['dir_name'] for row in db_records}
            db_photo_ids = {row['photo_id'] for row in db_records}

            for dir_name, dir_path in disk_dirs.items():
                if dir_name in db_dir_names:
                    continue

                # 推断 album_id: 检查父目录是否是 album_id
                parent_name = dir_path.parent.name
                album_id = parent_name if parent_name != Path(base_dir).name else ''

                if not album_id:
                    # 尝试从订阅表推断
                    album_id = self._infer_album_id(dir_name, conn)

                if not album_id:
                    continue

                # 生成 recovery photo_id
                h = hashlib.md5(dir_name.encode()).hexdigest()[:8]
                recovery_pid = f'recovered_{h}'
                if recovery_pid in db_photo_ids:
                    recovery_pid = f'recovered_{h}_{len(added)}'

                image_count = self._count_images(dir_path)
                conn.execute(
                    '''INSERT OR IGNORE INTO photo_download
                       (photo_id, album_id, dir_name, title, image_count)
                       VALUES (?, ?, ?, ?, ?)''',
                    (recovery_pid, album_id, dir_name, dir_name, image_count)
                )
                added.append({'photo_id': recovery_pid, 'album_id': album_id, 'dir_name': dir_name})
                db_photo_ids.add(recovery_pid)

            conn.commit()
        finally:
            conn.close()

        return {
            'ok': True,
            'scanned_dirs': scanned_dirs,
            'db_records': len(db_records),
            'added': added,
            'updated': updated,
            'removed': removed,
            'duplicates': duplicates,
        }

    def _try_match_disk_dir(self, dir_name: str, album_id: str, disk_dirs: dict):
        """尝试模糊匹配磁盘目录，只做高置信度匹配"""
        # 精确匹配
        if dir_name in disk_dirs:
            return disk_dirs[dir_name]

        # 数字 ID 匹配 (photo_id 可能是纯数字)
        if dir_name.isdigit():
            for name, path in disk_dirs.items():
                if dir_name in name:
                    return path

        # 只做较长字符串的包含匹配，避免误匹配
        if len(dir_name) >= 6:
            for name, path in disk_dirs.items():
                if dir_name in name and len(dir_name) > len(name) * 0.5:
                    return path

        return None

    def _infer_album_id(self, dir_name: str, conn) -> str:
        """从订阅表推断 album_id，通过目录名匹配标题"""
        # 从订阅表获取 album_id → title 映射
        cursor = conn.execute('SELECT album_id, title FROM subscription')
        rows = cursor.fetchall()

        # 精确匹配：目录名以订阅标题开头
        for row in rows:
            title = row['title'] or ''
            if title and (dir_name.startswith(title) or dir_name == title):
                return row['album_id']

        # 模糊匹配：订阅标题是目录名的子串（至少4个字符）
        for row in rows:
            title = row['title'] or ''
            if len(title) >= 4 and title in dir_name:
                return row['album_id']

        # 从 photo_download 表推断：查找包含相同关键词的已知映射
        cursor = conn.execute(
            'SELECT album_id, dir_name FROM photo_download WHERE album_id != "" LIMIT 500'
        )
        known = cursor.fetchall()

        # 尝试最长公共子串匹配
        best_album = ''
        best_len = 0
        for row in known:
            known_dir = row['dir_name'] or ''
            # 找公共前缀
            common = 0
            for a, b in zip(dir_name, known_dir):
                if a == b:
                    common += 1
                else:
                    break
            if common > best_len and common >= 4:
                best_len = common
                best_album = row['album_id']

        return best_album

    def _get_base_dir(self) -> Optional[str]:
        try:
            return self.option.dir_rule.base_dir
        except Exception:
            return None

    def _get_all_download_counts(self) -> dict:
        """Get chapter count per album from photo_download. Single query, no filesystem."""
        import sqlite3
        try:
            db_path = self._get_db_path()
            if not db_path:
                return {}
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    'SELECT album_id, COUNT(*) as cnt FROM photo_download GROUP BY album_id'
                )
                return {row['album_id']: row['cnt'] for row in cursor.fetchall()}
            finally:
                conn.close()
        except Exception:
            return {}

    def _upsert_album_meta(self, album_id: str, album) -> None:
        """Save album metadata (pub_date, update_date, description) to subscription table
        using sync sqlite3. No-op if the album is not subscribed."""
        import sqlite3
        try:
            db_path = self._get_db_path()
            if not db_path:
                return
            conn = sqlite3.connect(db_path)
            try:
                pub_date = album.pub_date or ''
                update_date = album.update_date or ''
                description = album.description or ''
                is_completed = album.is_completed
                conn.execute(
                    '''UPDATE subscription
                       SET pub_date = ?, update_date = ?, description = ?,
                           title = ?, author = ?, is_completed = ?
                       WHERE album_id = ?''',
                    (pub_date, update_date, description,
                     album.name or '', album.author or '',
                     int(is_completed), album_id)
                )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

    def _get_cached_album_title(self, album_id: str) -> str:
        """Get album title from chapter_cache table."""
        import sqlite3
        try:
            db_path = self._get_db_path()
            if not db_path:
                return ''
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(
                    "SELECT title FROM chapter_cache WHERE album_id = ? AND title != '' LIMIT 1",
                    (album_id,)
                )
                row = cursor.fetchone()
                return row['title'] if row else ''
            finally:
                conn.close()
        except Exception:
            return ''
