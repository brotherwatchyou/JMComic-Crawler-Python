from fastapi import APIRouter, Request

from ..models import DownloadSettings, ClientSettings, PluginSettings

router = APIRouter()


def _get_option(request: Request):
    return request.app.state.jm_option


@router.get('')
async def get_settings(request: Request):
    option = _get_option(request)
    proxies = option.client.postman.meta_data.proxies if hasattr(option.client, 'postman') else {}
    proxy_str = ''
    if isinstance(proxies, dict):
        proxy_str = proxies.get('http', '') or proxies.get('https', '') or ''
    elif isinstance(proxies, str):
        proxy_str = proxies

    return {
        'download': {
            'base_dir': str(option.dir_rule.base_dir) if option.dir_rule else '',
            'dir_rule': option.dir_rule.rule_dsl if option.dir_rule else '',
            'normalize_zh': option.dir_rule.normalize_zh if option.dir_rule else None,
            'image_decode': option.download.image.decode if hasattr(option.download, 'image') else True,
            'image_suffix': option.download.image.suffix if hasattr(option.download, 'image') else None,
            'image_thread_count': option.download.threading.image if hasattr(option.download, 'threading') else 30,
            'photo_thread_count': option.download.threading.photo if hasattr(option.download, 'threading') else 4,
            'download_cache': option.download.cache if hasattr(option.download, 'cache') else True,
        },
        'client': {
            'impl': option.client.impl if hasattr(option, 'client') else 'api',
            'retry_times': option.client.retry_times if hasattr(option, 'client') else 5,
            'domain': option.client.domain if hasattr(option, 'client') else [],
            'proxy': proxy_str,
            'impersonate': option.client.postman.meta_data.impersonate if hasattr(option.client, 'postman') else 'chrome',
        },
        'plugin': {
            'valid': option.plugins.valid if hasattr(option, 'plugins') else 'log',
        },
    }


@router.put('/download')
async def update_download_settings(req: DownloadSettings, request: Request):
    option = _get_option(request)
    if req.base_dir is not None:
        from jmcomic.jm_toolkit import JmcomicText
        option.dir_rule.base_dir = JmcomicText.parse_to_abspath(req.base_dir)
    if req.dir_rule is not None:
        option.dir_rule.rule_dsl = req.dir_rule
        option.dir_rule.parser_list = option.dir_rule.get_rule_parser_list(req.dir_rule)
    if req.normalize_zh is not None:
        option.dir_rule.normalize_zh = req.normalize_zh if req.normalize_zh else None
    if req.image_decode is not None:
        option.download.image.decode = req.image_decode
    if req.image_suffix is not None:
        option.download.image.suffix = req.image_suffix if req.image_suffix else None
    if req.image_thread_count is not None:
        option.download.threading.image = req.image_thread_count
    if req.photo_thread_count is not None:
        option.download.threading.photo = req.photo_thread_count
    if req.download_cache is not None:
        option.download.cache = req.download_cache
    option.to_file()
    return {'ok': True}


@router.put('/client')
async def update_client_settings(req: ClientSettings, request: Request):
    option = _get_option(request)
    if req.impl is not None:
        option.client.impl = req.impl
    if req.retry_times is not None:
        option.client.retry_times = req.retry_times
    if req.domain is not None:
        domain_list = [d.strip() for d in req.domain.split(',') if d.strip()]
        option.client.domain = domain_list
    if req.proxy is not None:
        proxy_val = req.proxy if req.proxy else None
        if proxy_val:
            option.client.postman.meta_data.proxies = {'http': proxy_val, 'https': proxy_val}
        else:
            option.client.postman.meta_data.proxies = None
    if req.impersonate is not None:
        option.client.postman.meta_data.impersonate = req.impersonate
    option.to_file()
    return {'ok': True}


@router.put('/plugin')
async def update_plugin_settings(req: PluginSettings, request: Request):
    option = _get_option(request)
    if req.valid is not None:
        option.plugins.valid = req.valid
    option.to_file()
    return {'ok': True}


@router.get('/scheduler')
async def get_scheduler_settings(request: Request):
    """Read scheduler config from DB."""
    import sqlite3
    try:
        db_path = request.app.state.config.get_db_path()
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


@router.put('/scheduler')
async def update_scheduler_settings(request: Request):
    """Update scheduler config and reload the scheduler."""
    import json
    import sqlite3
    try:
        body = await request.json()
    except Exception:
        body = {}

    check_interval = body.get('check_interval_minutes', None)
    skip_completed = body.get('skip_completed', None)

    try:
        db_path = request.app.state.config.get_db_path()
        conn = sqlite3.connect(db_path)
        try:
            if check_interval is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO scheduler_config (key, value) VALUES (?, ?)",
                    ('check_interval_minutes', str(int(check_interval)))
                )
            if skip_completed is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO scheduler_config (key, value) VALUES (?, ?)",
                    ('skip_completed', 'true' if skip_completed else 'false')
                )
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        return {'ok': False, 'error': str(e)}

    # Reload scheduler with new config
    from ..scheduler.subscription_checker import reload_scheduler
    reload_scheduler(request.app)

    return {'ok': True}