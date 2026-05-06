from dataclasses import dataclass, field
from pathlib import Path
import os


def get_data_dir() -> Path:
    """数据目录，存放 SQLite、配置文件等。可通过 JM_DATA_DIR 环境变量覆盖。"""
    env = os.environ.get('JM_DATA_DIR', '').strip()
    if env:
        p = Path(env)
    else:
        p = Path.home() / '.jmcomic'
    p.mkdir(parents=True, exist_ok=True)
    return p


def get_download_dir() -> Path:
    """下载目录，可通过 JM_DOWNLOAD_DIR 环境变量覆盖。"""
    env = os.environ.get('JM_DOWNLOAD_DIR', '').strip()
    if env:
        p = Path(env)
    else:
        p = Path(os.getcwd())
    return p


@dataclass
class WebUIConfig:
    host: str = '0.0.0.0'
    port: int = 9801
    web_password: str = ''
    db_path: str = ''
    debug: bool = False

    def get_db_path(self) -> str:
        if self.db_path:
            return self.db_path
        return str(get_data_dir() / 'webui.db')
