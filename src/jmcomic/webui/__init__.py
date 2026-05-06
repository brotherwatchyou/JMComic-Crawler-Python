"""plugin_jm_webui - Web management UI for jmcomic"""

__version__ = '0.1.0'


def create_app(option=None, web_password: str = '', db_path: str = ''):
    from .app import create_app as _create_app
    return _create_app(option=option, web_password=web_password, db_path=db_path)
