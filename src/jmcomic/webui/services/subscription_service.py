import json
from datetime import datetime
from typing import List, Optional, Tuple

from ..database import get_db


class SubscriptionService:
    def __init__(self, option):
        self.option = option

    async def get_subscription(self, album_id: str) -> Optional[dict]:
        db = await get_db()
        cursor = await db.execute(
            'SELECT * FROM subscription WHERE album_id = ? AND status != ?',
            (album_id, 'removed')
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._row_to_dict(row)

    async def list_subscriptions(self) -> List[dict]:
        db = await get_db()
        cursor = await db.execute(
            'SELECT * FROM subscription WHERE status != ? ORDER BY created_at DESC',
            ('removed',)
        )
        rows = await cursor.fetchall()
        return [self._row_to_dict(row) for row in rows]

    async def add_subscription(self, album_id: str, auto_download: bool = True,
                               download_service=None) -> dict:
        title, author, latest_photo_id = '', '', ''
        pub_date, update_date, description = '', '', ''
        is_completed = False
        try:
            client = self.option.new_jm_client()
            album = client.get_album_detail(album_id)
            title = album.name
            author = album.author
            pub_date = album.pub_date or ''
            update_date = album.update_date or ''
            description = album.description or ''
            is_completed = album.is_completed
            if len(album.episode_list) > 0:
                latest_photo_id = album.episode_list[-1][0]
        except Exception:
            pass

        db = await get_db()
        await db.execute(
            '''INSERT OR REPLACE INTO subscription
               (album_id, title, author, last_known_photo_id, auto_download,
                pub_date, update_date, description, is_completed, created_at, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')''',
            (album_id, title, author, latest_photo_id, int(auto_download),
             pub_date, update_date, description, int(is_completed),
             datetime.now().isoformat())
        )
        await db.commit()

        # 添加订阅后自动触发下载
        if auto_download and download_service is not None:
            await download_service.add_to_queue(album_id, 'album')

        return {'album_id': album_id, 'title': title, 'author': author}

    async def remove_subscription(self, album_id: str) -> None:
        db = await get_db()
        await db.execute(
            'UPDATE subscription SET status = ? WHERE album_id = ?',
            ('removed', album_id)
        )
        await db.commit()

    async def update_subscription(self, album_id: str, **kwargs) -> None:
        db = await get_db()
        sets, values = [], []
        for key in ('auto_download', 'check_interval_minutes', 'status'):
            if key in kwargs and kwargs[key] is not None:
                val = kwargs[key]
                if key == 'auto_download':
                    val = int(val)
                sets.append(f'{key} = ?')
                values.append(val)
        if not sets:
            return
        values.append(album_id)
        await db.execute(
            f'UPDATE subscription SET {", ".join(sets)} WHERE album_id = ?',
            values
        )
        await db.commit()

    async def check_update(self, album_id: str) -> Tuple[bool, List[str]]:
        db = await get_db()
        cursor = await db.execute(
            'SELECT last_known_photo_id FROM subscription WHERE album_id = ?',
            (album_id,)
        )
        row = await cursor.fetchone()
        if not row or not row['last_known_photo_id']:
            return False, []

        photo_id = row['last_known_photo_id']
        client = self.option.new_jm_client()
        album = client.get_album_detail(album_id)

        photo_new_list = []
        is_new_photo = False
        sentinel = int(photo_id)
        for photo in album:
            if is_new_photo:
                photo_new_list.append(photo.photo_id)
            if int(photo.photo_id) == sentinel:
                is_new_photo = True

        has_update = len(photo_new_list) != 0
        now = datetime.now().isoformat()

        pub_date = album.pub_date or ''
        update_date = album.update_date or ''
        description = album.description or ''
        is_completed = album.is_completed

        if has_update:
            await db.execute(
                '''UPDATE subscription SET has_update = 1, new_photo_ids = ?,
                   last_checked_at = ?, title = ?, author = ?,
                   pub_date = ?, update_date = ?, description = ?,
                   is_completed = ?
                   WHERE album_id = ?''',
                (json.dumps(photo_new_list), now, album.name, album.author,
                 pub_date, update_date, description, int(is_completed), album_id)
            )
        else:
            await db.execute(
                '''UPDATE subscription SET has_update = 0, new_photo_ids = '[]',
                   last_checked_at = ?, title = ?, author = ?,
                   pub_date = ?, update_date = ?, description = ?,
                   is_completed = ?
                   WHERE album_id = ?''',
                (now, album.name, album.author,
                 pub_date, update_date, description, int(is_completed), album_id)
            )
        await db.commit()
        return has_update, photo_new_list

    async def check_all_updates(self) -> List[dict]:
        db = await get_db()
        cursor = await db.execute(
            'SELECT album_id FROM subscription WHERE status = ?',
            ('active',)
        )
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            try:
                has_update, new_ids = await self.check_update(row['album_id'])
                results.append({
                    'album_id': row['album_id'],
                    'has_update': has_update,
                    'new_photo_ids': new_ids,
                })
            except Exception as e:
                results.append({
                    'album_id': row['album_id'],
                    'has_update': False,
                    'error': str(e),
                })
        return results

    async def clear_update_flag(self, album_id: str) -> None:
        """Clear has_update flag and advance last_known_photo_id past downloaded chapters."""
        db = await get_db()
        cursor = await db.execute(
            'SELECT last_known_photo_id, new_photo_ids FROM subscription WHERE album_id = ?',
            (album_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return

        new_ids = json.loads(row['new_photo_ids'] or '[]')
        if not new_ids:
            await db.execute(
                "UPDATE subscription SET has_update = 0, new_photo_ids = '[]' WHERE album_id = ?",
                (album_id,)
            )
            await db.commit()
            return

        # Advance last_known_photo_id to the latest downloaded photo
        all_ids = [int(pid) for pid in ([row['last_known_photo_id']] + new_ids) if pid and pid.isdigit()]
        new_last = str(max(all_ids)) if all_ids else row['last_known_photo_id']

        await db.execute(
            '''UPDATE subscription SET has_update = 0, new_photo_ids = '[]',
               last_known_photo_id = ? WHERE album_id = ?''',
            (new_last, album_id)
        )
        await db.commit()

    async def import_favorites(self, download_service=None) -> List[dict]:
        client = self.option.new_jm_client()
        imported = []
        async for page in self._iter_favorite_pages(client):
            for aid, ainfo in page.content:
                latest_ep_aid = ainfo.get('latest_ep_aid', '') or ''
                await self.add_subscription(aid, auto_download=True,
                                          download_service=download_service)
                if latest_ep_aid:
                    db = await get_db()
                    await db.execute(
                        'UPDATE subscription SET last_known_photo_id = ? WHERE album_id = ?',
                        (latest_ep_aid, aid)
                    )
                    await db.commit()
                imported.append({'album_id': aid, 'title': ainfo.get('name', '')})
        return imported

    async def _iter_favorite_pages(self, client):
        for page in client.favorite_folder_gen(folder_id='0'):
            yield page

    def _row_to_dict(self, row) -> dict:
        return {
            'album_id': row['album_id'],
            'title': row['title'],
            'author': row['author'],
            'last_known_photo_id': row['last_known_photo_id'],
            'auto_download': bool(row['auto_download']),
            'check_interval_minutes': row['check_interval_minutes'],
            'last_checked_at': row['last_checked_at'],
            'has_update': bool(row['has_update']),
            'new_photo_ids': json.loads(row['new_photo_ids'] or '[]'),
            'pub_date': (row['pub_date'] or '') if 'pub_date' in row.keys() else '',
            'update_date': (row['update_date'] or '') if 'update_date' in row.keys() else '',
            'description': (row['description'] or '') if 'description' in row.keys() else '',
            'is_completed': bool(row['is_completed']) if 'is_completed' in row.keys() else False,
            'created_at': row['created_at'],
            'status': row['status'],
        }

    async def update_album_meta(self, album_id: str, title: str = '', author: str = '',
                                 pub_date: str = '', update_date: str = '',
                                 description: str = '', is_completed: bool = None) -> None:
        """Update album metadata fields for an existing subscription."""
        db = await get_db()
        sets, values = [], []
        for col, val in [('title', title), ('author', author),
                          ('pub_date', pub_date), ('update_date', update_date),
                          ('description', description)]:
            if val:
                sets.append(f'{col} = ?')
                values.append(val)
        if is_completed is not None:
            sets.append('is_completed = ?')
            values.append(int(is_completed))
        if not sets:
            return
        values.append(album_id)
        await db.execute(
            f'UPDATE subscription SET {", ".join(sets)} WHERE album_id = ?',
            values
        )
        await db.commit()