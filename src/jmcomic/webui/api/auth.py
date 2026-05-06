from fastapi import APIRouter, Request, HTTPException

from ..models import LoginRequest, AuthStatus
from ..services.auth_service import AuthService

router = APIRouter()


def _get_service(request: Request) -> AuthService:
    return AuthService(request.app.state.jm_option)


@router.post('/login')
async def login(req: LoginRequest, request: Request):
    service = _get_service(request)
    try:
        result = await service.login(req.username, req.password)
        return {'ok': True, 'data': result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/logout')
async def logout(request: Request):
    service = _get_service(request)
    await service.logout()
    return {'ok': True}


@router.get('/status', response_model=AuthStatus)
async def get_status(request: Request):
    service = _get_service(request)
    return await service.get_status()