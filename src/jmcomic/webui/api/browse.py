import asyncio

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pathlib import Path
import httpx

from ..services.browse_service import BrowseService
from ..services.subscription_service import SubscriptionService

router = APIRouter()


def _get_service(request: Request) -> BrowseService:
    # Reuse cached instance for photo_dir_cache to persist across requests
    svc = getattr(request.app.state, 'browse_service', None)
    if svc is None:
        svc = BrowseService(request.app.state.jm_option)
        request.app.state.browse_service = svc
    return svc


@router.get('/bookshelf')
async def list_bookshelf(request: Request):
    """统一书架：合并订阅和已下载数据"""
    browse_svc = _get_service(request)
    sub_svc = SubscriptionService(request.app.state.jm_option)
    subscriptions = await sub_svc.list_subscriptions()
    return await browse_svc.list_bookshelf(subscriptions)


@router.get('/albums')
async def list_albums(request: Request):
    service = _get_service(request)
    return service.list_albums()


@router.get('/albums/{album_id}')
async def get_album(album_id: str, request: Request):
    """Read album detail from local DB only. No remote API calls."""
    browse_svc = _get_service(request)
    sub_svc = SubscriptionService(request.app.state.jm_option)
    download_svc = request.app.state.download_service

    sub_info = await sub_svc.get_subscription(album_id)
    chapters = browse_svc.get_cached_chapters(album_id)

    album = {
        'album_id': album_id,
        'title': (sub_info or {}).get('title') or album_id,
        'author': (sub_info or {}).get('author', ''),
        'pub_date': (sub_info or {}).get('pub_date', '') or '',
        'update_date': (sub_info or {}).get('update_date', '') or '',
        'description': (sub_info or {}).get('description', '') or '',
        'is_completed': (sub_info or {}).get('is_completed', False),
        'is_downloaded': any(ch['is_downloaded'] for ch in chapters) if chapters else False,
        'chapter_count': sum(1 for ch in chapters if ch['is_downloaded']) if chapters else 0,
        'chapters': chapters,
        'has_cached_chapters': len(chapters) > 0,
        'is_subscribed': sub_info is not None,
    }

    # Get download queue status
    queue = await download_svc.get_queue()
    album['download_status'] = None
    for item in queue:
        if item['jm_id'] == album_id and item['status'] in ('pending', 'downloading'):
            album['download_status'] = {
                'status': item['status'],
                'progress_pct': item['progress_pct'],
                'current_photo': item.get('current_photo', ''),
                'current_image_index': item.get('current_image_index', 0),
                'total_images': item.get('total_images', 0),
            }
            break

    return album


@router.post('/albums/{album_id}/sync-chapters')
async def sync_chapters(album_id: str, request: Request):
    """Fetch full chapter list from JM API and persist to DB cache."""
    browse_svc = _get_service(request)
    sub_svc = SubscriptionService(request.app.state.jm_option)

    # Get subscription info and update title if available
    sub_info = await sub_svc.get_subscription(album_id)

    photo_dir_map = await browse_svc._async_get_photo_dir_map(album_id)
    loop = asyncio.get_event_loop()
    chapters = await loop.run_in_executor(
        None, browse_svc.get_chapters_from_server, album_id, photo_dir_map, True
    )

    # Re-read subscription to get updated metadata
    sub_info = await sub_svc.get_subscription(album_id)

    return {
        'ok': True,
        'chapter_count': len(chapters),
        'title': (sub_info or {}).get('title') or album_id,
        'pub_date': (sub_info or {}).get('pub_date', '') or '',
        'update_date': (sub_info or {}).get('update_date', '') or '',
        'description': (sub_info or {}).get('description', '') or '',
    }


@router.get('/albums/{album_id}/download-progress')
async def get_download_progress(album_id: str, request: Request):
    """Lightweight endpoint: only returns download status from DB.
    No remote API calls, no filesystem scans.
    """
    browse_svc = _get_service(request)
    download_svc = request.app.state.download_service

    # Get downloaded photo_ids from DB
    downloaded_ids = browse_svc.get_downloaded_photo_ids(album_id)

    # Get queue status
    queue = await download_svc.get_queue()
    download_status = None
    for item in queue:
        if item['jm_id'] == album_id and item['status'] in ('pending', 'downloading'):
            download_status = {
                'status': item['status'],
                'progress_pct': item['progress_pct'],
                'current_photo': item.get('current_photo', ''),
                'current_image_index': item.get('current_image_index', 0),
                'total_images': item.get('total_images', 0),
            }
            break

    return {
        'downloaded_photo_ids': downloaded_ids,
        'download_status': download_status,
    }


@router.get('/albums/{album_id}/chapters/{chapter_name}/images')
async def get_chapter_images(album_id: str, chapter_name: str, request: Request):
    service = _get_service(request)
    return await service.get_chapter_images(album_id, chapter_name)


@router.get('/cover/{album_id}')
async def get_cover_image(album_id: str, request: Request):
    """Proxy cover image from JM server to avoid CORS issues."""
    try:
        # JM comic cover URL pattern
        cover_url = f"https://cdn-msp.jmapiproxy1.cc/media/albums/{album_id}_3x4.jpg"
        async with httpx.AsyncClient() as client:
            resp = await client.get(cover_url, timeout=10.0, follow_redirects=True)
            if resp.status_code == 200:
                return StreamingResponse(
                    iter([resp.content]),
                    media_type=resp.headers.get('content-type', 'image/jpeg'),
                    headers={'Cache-Control': 'public, max-age=86400'}
                )
    except Exception:
        pass
    raise HTTPException(status_code=404, detail='Cover not found')


@router.get('/images/{album_id}/{chapter_name}/{image_name}')
async def serve_image(album_id: str, chapter_name: str, image_name: str, request: Request):
    service = _get_service(request)
    path = await service.get_image_path(album_id, chapter_name, image_name)
    if path is None:
        raise HTTPException(status_code=404, detail='Image not found')
    return FileResponse(path)


@router.post('/repair')
async def repair_data(request: Request):
    """一键修复数据一致性"""
    service = _get_service(request)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, service.repair_data)
    return result
