import asyncio
import sqlite3
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler

_scheduler: BackgroundScheduler | None = None
_config_cache: dict = {}


def _load_config(app) -> dict:
    """Read scheduler config from DB. Falls back to defaults."""
    try:
        db_path = app.state.config.get_db_path()
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.execute("SELECT key, value FROM scheduler_config")
            config = {row[0]: row[1] for row in cursor.fetchall()}
            return {
                'check_interval_minutes': int(config.get('check_interval_minutes', '60')),
                'skip_completed': config.get('skip_completed', 'false').lower() == 'true',
            }
        finally:
            conn.close()
    except Exception:
        return {'check_interval_minutes': 60, 'skip_completed': False}


def start_scheduler(app):
    global _scheduler
    config = _load_config(app)
    interval = config['check_interval_minutes']

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _check_updates,
        'interval',
        minutes=interval,
        id='subscription_checker',
        args=[app],
    )
    _scheduler.start()

    from jmcomic import jm_log
    jm_log('webui.scheduler', f'Scheduler started (interval={interval}min, skip_completed={config["skip_completed"]})')


def reload_scheduler(app):
    """Reload scheduler with updated config. Called after settings change."""
    global _scheduler
    stop_scheduler()
    start_scheduler(app)


def stop_scheduler():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def _check_updates(app):
    """Run subscription update check, skipping completed albums if configured."""
    option = app.state.jm_option
    if option is None:
        return

    config = _load_config(app)

    from jmcomic import jm_log
    jm_log('webui.scheduler', f'Checking subscription updates at {datetime.now()} '
           f'(skip_completed={config["skip_completed"]})')

    try:
        from ..services.subscription_service import SubscriptionService
        service = SubscriptionService(option)
        loop = asyncio.new_event_loop()
        try:
            subscriptions = loop.run_until_complete(service.list_subscriptions())
            results = []
            for sub in subscriptions:
                # Skip completed albums if configured
                if config['skip_completed'] and sub.get('is_completed'):
                    continue
                try:
                    has_update, new_ids = loop.run_until_complete(
                        service.check_update(sub['album_id'])
                    )
                    results.append({
                        'album_id': sub['album_id'],
                        'has_update': has_update,
                        'new_photo_ids': new_ids,
                    })
                except Exception as e:
                    jm_log('webui.scheduler.error',
                           f"Check failed for {sub['album_id']}: {e}")

            updated = [r for r in results if r.get('has_update')]
            if updated:
                jm_log('webui.scheduler', f'Found {len(updated)} updated albums')
                dl_service = app.state.download_service
                for item in updated:
                    # Find subscription to check auto_download
                    sub = next((s for s in subscriptions
                               if s['album_id'] == item['album_id']), None)
                    if sub and sub.get('auto_download'):
                        loop.run_until_complete(
                            dl_service.add_to_queue(item['album_id'], 'album')
                        )
        finally:
            loop.close()
    except Exception as e:
        jm_log('webui.scheduler.error', e)
