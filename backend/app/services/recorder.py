"""
録画サービス

Playwrightを使用してページを録画します。
タイムフィット・スクロールアルゴリズムを実装しています。
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright, Page
from app.config import settings
from app.utils.filename import sanitize_filename, get_unique_filename
from app.services.errors import NetworkError, TimeoutError, FileSystemError


class RecorderService:
    """録画サービスクラス"""

    async def record_page(
        self,
        url: str,
        shop_name: str,
        output_dir: str
    ) -> dict:
        """
        ページを録画

        Args:
            url: 録画するページのURL
            shop_name: 店舗名（ファイル名に使用）
            output_dir: 出力ディレクトリ名

        Returns:
            生成された動画ファイル名とスクリーンショットファイル名の辞書
            {"video_filename": str, "screenshot_filename": str}

        Raises:
            NetworkError: ネットワークエラー
            TimeoutError: タイムアウトエラー
            FileSystemError: ファイル保存エラー
        """
        # 出力パス準備
        try:
            video_dir = Path(settings.OUTPUT_BASE_DIR) / output_dir / "videos"
            screenshot_dir = Path(settings.OUTPUT_BASE_DIR) / output_dir / "screenshots"
            video_dir.mkdir(parents=True, exist_ok=True)
            screenshot_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise FileSystemError(f"Failed to create output directory: {e}") from e

        # ファイル名生成（重複チェック）
        sanitized_name = sanitize_filename(shop_name)
        existing_videos = {f.stem for f in video_dir.glob("*.webm")}
        existing_screenshots = {f.stem for f in screenshot_dir.glob("*.png")}
        unique_name = get_unique_filename(sanitized_name, existing_videos | existing_screenshots)
        video_filename = f"{unique_name}.webm"
        screenshot_filename = f"{unique_name}_screenshot.png"

        async with async_playwright() as p:
            browser = None
            temp_video_path = None
            try:
                browser = await p.chromium.launch(
                    headless=settings.PLAYWRIGHT_HEADLESS
                )
                context = await browser.new_context(
                    viewport={
                        "width": settings.RECORDING_WIDTH,
                        "height": settings.RECORDING_HEIGHT
                    },
                    record_video_dir=str(video_dir),
                    record_video_size={
                        "width": settings.RECORDING_WIDTH,
                        "height": settings.RECORDING_HEIGHT
                    }
                )
                page = await context.new_page()

                # ページ読み込み
                try:
                    await page.goto(
                        url,
                        wait_until="networkidle",
                        timeout=settings.PLAYWRIGHT_TIMEOUT
                    )
                    # 画像読み込み完了を待機
                    await asyncio.sleep(1)
                except Exception as e:
                    if "timeout" in str(e).lower():
                        raise TimeoutError(f"Page load timeout: {url}") from e
                    raise NetworkError(f"Failed to load page: {url}") from e

                # フルページスクリーンショット撮影（録画開始前）
                screenshot_path = screenshot_dir / screenshot_filename
                try:
                    await page.screenshot(full_page=True, path=str(screenshot_path))
                except Exception as e:
                    raise FileSystemError(f"Failed to save screenshot: {e}") from e

                # タイムフィット・スクロール
                await self._timefit_scroll(page)

                # 録画終了（Contextをcloseすると録画が完了する）
                await page.close()
                await context.close()

                # 自動生成された動画ファイルを取得してリネーム
                video_files = sorted(video_dir.glob("*.webm"), key=lambda f: f.stat().st_mtime)
                if video_files:
                    temp_video_path = video_files[-1]  # 最新のファイル
                    final_video_path = video_dir / video_filename
                    temp_video_path.rename(final_video_path)

                return {
                    "video_filename": video_filename,
                    "screenshot_filename": screenshot_filename
                }

            except (NetworkError, TimeoutError):
                raise
            except Exception as e:
                raise FileSystemError(f"Failed to save video: {e}") from e
            finally:
                if browser:
                    await browser.close()

    async def _timefit_scroll(self, page: Page):
        """
        タイムフィット・スクロール実装

        ページ全体を目標時間（27秒）でスムーズにスクロールします。
        60fpsで滑らかなスクロールを実現します。

        Args:
            page: Playwrightページオブジェクト
        """
        # ページ高さ取得
        total_height = await page.evaluate("document.body.scrollHeight")
        viewport_height = settings.RECORDING_HEIGHT

        # スクロール距離計算
        scroll_distance = total_height - viewport_height

        # スクロール不要な短いページ
        if scroll_distance <= 0:
            await asyncio.sleep(3)  # 短いページは3秒表示
            return

        # 目標時間: 27秒でスクロール完了
        target_duration = settings.RECORDING_TARGET_DURATION  # 秒
        step_interval = 1 / settings.RECORDING_FPS  # 60fps
        total_steps = int(target_duration / step_interval)
        step_size = scroll_distance / total_steps

        # スクロール実行
        current_step = 0
        while current_step < total_steps:
            try:
                await page.evaluate(f"window.scrollBy(0, {step_size})")
                await asyncio.sleep(step_interval)
                current_step += 1
            except Exception as e:
                # ページ遷移やクラッシュ時はループ脱出
                print(f"Scroll interrupted: {e}")
                break

        # 最終調整（確実に最下部へ）
        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
        except Exception as e:
            print(f"Final scroll failed: {e}")
