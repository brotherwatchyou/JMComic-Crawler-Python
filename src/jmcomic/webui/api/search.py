from fastapi import APIRouter, Request, HTTPException

from ..services.search_service import SearchService

router = APIRouter()


def _get_service(request: Request) -> SearchService:
    return SearchService(request.app.state.jm_option)


@router.get('')
async def search(request: Request, q: str = '', page: int = 1,
                 order: str = 'mr', category: str = '', sub: str = ''):
    service = _get_service(request)
    try:
        return service.search(q, page, order, category, sub)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/categories')
async def categories(request: Request):
    service = _get_service(request)
    return service.search_categories()