from fastapi import APIRouter, Request, HTTPException

from ..models import SubscriptionCreate, SubscriptionUpdate
from ..services.subscription_service import SubscriptionService

router = APIRouter()


def _get_service(request: Request) -> SubscriptionService:
    return SubscriptionService(request.app.state.jm_option)


def _get_download_service(request: Request):
    return request.app.state.download_service


@router.get('')
async def list_subscriptions(request: Request):
    service = _get_service(request)
    return await service.list_subscriptions()


@router.post('')
async def add_subscription(req: SubscriptionCreate, request: Request):
    service = _get_service(request)
    dl_service = _get_download_service(request)
    try:
        return await service.add_subscription(req.album_id, req.auto_download,
                                              download_service=dl_service)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete('/{album_id}')
async def remove_subscription(album_id: str, request: Request):
    service = _get_service(request)
    dl_service = _get_download_service(request)
    await service.remove_subscription(album_id)
    await dl_service.delete_album(album_id)
    return {'ok': True}


@router.put('/{album_id}')
async def update_subscription(album_id: str, req: SubscriptionUpdate, request: Request):
    service = _get_service(request)
    await service.update_subscription(album_id, **req.model_dump())
    return {'ok': True}


@router.post('/check-all')
async def check_all(request: Request):
    service = _get_service(request)
    return await service.check_all_updates()


@router.post('/{album_id}/check')
async def check_one(album_id: str, request: Request):
    service = _get_service(request)
    try:
        has_update, new_ids = await service.check_update(album_id)
        return {'album_id': album_id, 'has_update': has_update, 'new_photo_ids': new_ids}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/{album_id}/clear-update')
async def clear_update(album_id: str, request: Request):
    service = _get_service(request)
    await service.clear_update_flag(album_id)
    return {'ok': True}


@router.post('/import-favorites')
async def import_favorites(request: Request):
    service = _get_service(request)
    dl_service = _get_download_service(request)
    try:
        result = await service.import_favorites(download_service=dl_service)
        return {'ok': True, 'imported': result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))