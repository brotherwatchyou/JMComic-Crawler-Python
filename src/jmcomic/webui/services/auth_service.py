import json
from datetime import datetime
from typing import Optional

from ..database import get_db


class AuthService:
    def __init__(self, option):
        self.option = option

    async def login(self, username: str, password: str) -> dict:
        client = self.option.build_jm_client()
        client.login(username, password)
        cookies = dict(client['cookies'])

        self.option.update_cookies(cookies)
        from jmcomic import JmModuleConfig
        JmModuleConfig.APP_COOKIES = cookies

        db = await get_db()
        await db.execute(
            'DELETE FROM account WHERE is_active = 1'
        )
        await db.execute(
            '''INSERT INTO account (username, cookies, last_login_at, is_active)
               VALUES (?, ?, ?, 1)''',
            (username, json.dumps(cookies), datetime.now().isoformat())
        )
        await db.commit()
        return {'username': username, 'cookies': cookies}

    async def logout(self) -> None:
        db = await get_db()
        await db.execute('UPDATE account SET is_active = 0 WHERE is_active = 1')
        await db.commit()

    async def get_status(self) -> dict:
        db = await get_db()
        cursor = await db.execute(
            'SELECT username, is_active FROM account WHERE is_active = 1 LIMIT 1'
        )
        row = await cursor.fetchone()
        if row:
            return {'is_logged_in': bool(row['is_active']), 'username': row['username']}
        return {'is_logged_in': False, 'username': ''}

    async def restore_cookies(self) -> Optional[dict]:
        db = await get_db()
        cursor = await db.execute(
            'SELECT cookies FROM account WHERE is_active = 1 LIMIT 1'
        )
        row = await cursor.fetchone()
        if row and row['cookies']:
            cookies = json.loads(row['cookies'])
            self.option.update_cookies(cookies)
            from jmcomic import JmModuleConfig
            JmModuleConfig.APP_COOKIES = cookies
            return cookies
        return None
