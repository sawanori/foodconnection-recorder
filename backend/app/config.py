from pydantic_settings import BaseSettings
from typing import Dict


class Settings(BaseSettings):
    # データベース
    DATABASE_URL: str = "sqlite+aiosqlite:///./food_connection.db"

    # 出力先
    OUTPUT_BASE_DIR: str = "../output"

    # Playwright設定
    PLAYWRIGHT_HEADLESS: bool = True
    PLAYWRIGHT_TIMEOUT: int = 30000  # ミリ秒

    # 録画設定
    RECORDING_WIDTH: int = 1366
    RECORDING_HEIGHT: int = 768
    RECORDING_TARGET_DURATION: int = 27  # 秒
    RECORDING_FPS: int = 60

    # リトライ設定
    MAX_RETRIES: int = 3
    RETRY_BACKOFF_BASE: int = 2  # 指数バックオフの基数

    # セレクタ定義
    SELECTORS: Dict[str, Dict[str, str]] = {
        "list_page": {
            "shop_links": "a[href*='f-webdesign.biz/'][href$='/']:not([href*='category']):not([href*='page'])",
            "pagination": ".pagination a, .page-numbers"
        },
        "detail_page": {
            "shop_name": "listitem:last-child",
            "shop_url": "dt:contains('URL') + dd a",
            "shop_url_alt": "definition a[href^='http']:not([href*='f-webdesign'])"
        }
    }

    # セキュリティ
    ALLOWED_OUTPUT_DIR_PATTERN: str = r"^[a-zA-Z0-9_-]+$"

    # CORS設定
    FRONTEND_URL: str = "http://localhost:3000"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
