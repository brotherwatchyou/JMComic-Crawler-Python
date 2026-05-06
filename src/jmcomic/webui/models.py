from pydantic import BaseModel
from typing import Optional


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthStatus(BaseModel):
    is_logged_in: bool
    username: str = ''


class SubscriptionCreate(BaseModel):
    album_id: str
    auto_download: bool = True


class SubscriptionUpdate(BaseModel):
    auto_download: Optional[bool] = None
    check_interval_minutes: Optional[int] = None
    status: Optional[str] = None


class DownloadSettings(BaseModel):
    base_dir: Optional[str] = None
    dir_rule: Optional[str] = None
    normalize_zh: Optional[str] = None
    image_decode: Optional[bool] = None
    image_suffix: Optional[str] = None
    image_thread_count: Optional[int] = None
    photo_thread_count: Optional[int] = None
    download_cache: Optional[bool] = None


class ClientSettings(BaseModel):
    impl: Optional[str] = None
    retry_times: Optional[int] = None
    domain: Optional[str] = None
    proxy: Optional[str] = None
    impersonate: Optional[str] = None


class PluginSettings(BaseModel):
    valid: Optional[str] = None
