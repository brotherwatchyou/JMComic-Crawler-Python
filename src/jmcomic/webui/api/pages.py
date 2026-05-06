from fastapi import APIRouter, Request

router = APIRouter()


@router.get('/')
async def index(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('bookshelf.html', {'request': request})


@router.get('/login')
async def login_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('login.html', {'request': request})


@router.get('/bookshelf')
async def bookshelf_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('bookshelf.html', {'request': request})


@router.get('/browse')
async def browse_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('browse.html', {'request': request})


@router.get('/browse/{album_id}')
async def browse_album_page(album_id: str, request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('browse_album.html', {
        'request': request, 'album_id': album_id
    })


@router.get('/reader/{album_id}/{chapter_name}')
async def reader_page(album_id: str, chapter_name: str, request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('reader.html', {
        'request': request, 'album_id': album_id, 'chapter_name': chapter_name
    })


@router.get('/search')
async def search_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('search.html', {'request': request})


@router.get('/downloads')
async def downloads_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('downloads.html', {'request': request})


@router.get('/settings')
async def settings_page(request: Request):
    templates = request.app.state.templates
    return templates.TemplateResponse('settings.html', {'request': request})