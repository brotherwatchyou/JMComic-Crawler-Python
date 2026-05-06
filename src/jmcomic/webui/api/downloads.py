from fastapi import APIRouter, Request

from ..services.download_service import DownloadService

router = APIRouter()


def _get_service(request: Request) -> DownloadService:
    return request.app.state.download_service


@router.post('/album/{album_id}')
async def download_album(album_id: str, request: Request):
    service = _get_service(request)
    task_id = await service.add_to_queue(album_id, 'album')
    return {'ok': True, 'task_id': task_id}


@router.post('/photo/{photo_id}')
async def download_photo(photo_id: str, request: Request):
    service = _get_service(request)
    task_id = await service.add_to_queue(photo_id, 'photo')
    return {'ok': True, 'task_id': task_id}


@router.get('/queue')
async def get_queue(request: Request):
    service = _get_service(request)
    return await service.get_queue()


@router.get('/active')
async def get_active(request: Request):
    service = _get_service(request)
    return await service.get_active()


@router.delete('/queue/{task_id}')
async def cancel_task(task_id: int, request: Request):
    service = _get_service(request)
    await service.cancel_task(task_id)
    return {'ok': True}


@router.delete('/queue/{task_id}/dismiss')
async def dismiss_task(task_id: int, request: Request):
    service = _get_service(request)
    await service.dismiss_task(task_id)
    return {'ok': True}


@router.get('/history')
async def get_history(request: Request, limit: int = 50, offset: int = 0):
    service = _get_service(request)
    return await service.get_history(limit, offset)


@router.delete('/history')
async def clear_history(request: Request):
    service = _get_service(request)
    deleted = await service.clear_history()
    return {'ok': True, 'deleted': deleted}


@router.post('/cleanup')
async def cleanup_stale(request: Request):
    service = _get_service(request)
    cleaned = await service.cleanup_stale_queue()
    return {'ok': True, 'cleaned': cleaned}


@router.delete('/album/{album_id}/photo/{photo_id}')
async def delete_photo(album_id: str, photo_id: str, request: Request):
    service = _get_service(request)
    return await service.delete_photo(album_id, photo_id)


@router.delete('/album/{album_id}')
async def delete_album(album_id: str, request: Request):
    service = _get_service(request)
    return await service.delete_album(album_id)
