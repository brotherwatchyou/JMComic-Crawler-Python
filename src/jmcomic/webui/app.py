from fastapi import FastAPI, Request, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pathlib import Path

from .config import WebUIConfig
from .database import init_db, close_db

_base_dir = Path(__file__).parent


def create_app(option=None, web_password: str = '', db_path: str = '') -> FastAPI:
    config = WebUIConfig(
        web_password=web_password,
        db_path=db_path,
    )

    app = FastAPI(title='JMComic WebUI', version='0.1.0')

    app.state.jm_option = option
    app.state.config = config
    app.state.progress_queue = None

    app.add_middleware(SessionMiddleware, secret_key='jm_webui_session_key')

    @app.on_event('startup')
    async def startup():
        from .services.download_service import DownloadService
        import asyncio
        app.state.progress_queue = asyncio.Queue()
        app.state.download_service = DownloadService(option, app.state.progress_queue)
        await init_db(config.get_db_path())

        from .scheduler.subscription_checker import start_scheduler
        start_scheduler(app)

    @app.on_event('shutdown')
    async def shutdown():
        from .scheduler.subscription_checker import stop_scheduler
        stop_scheduler()
        await close_db()

    # Static files and templates
    static_dir = _base_dir / 'static'
    if static_dir.exists():
        app.mount('/static', StaticFiles(directory=str(static_dir)), name='static')

    templates = Jinja2Templates(directory=str(_base_dir / 'templates'))
    app.state.templates = templates

    # Register API routers
    from .api import auth, subscriptions, downloads, browse, search, settings
    app.include_router(auth.router, prefix='/api/auth', tags=['auth'])
    app.include_router(subscriptions.router, prefix='/api/subscriptions', tags=['subscriptions'])
    app.include_router(downloads.router, prefix='/api/downloads', tags=['downloads'])
    app.include_router(browse.router, prefix='/api/browse', tags=['browse'])
    app.include_router(search.router, prefix='/api/search', tags=['search'])
    app.include_router(settings.router, prefix='/api/settings', tags=['settings'])

    # WebSocket
    from .ws.handlers import router as ws_router
    app.include_router(ws_router)

    # Page routes
    from .api import pages
    app.include_router(pages.router)

    return app
