from dataclasses import dataclass, field
from pathlib import Path
import os


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
        default_dir = Path.home() / '.jmcomic'
        default_dir.mkdir(parents=True, exist_ok=True)
        return str(default_dir / 'webui.db')
