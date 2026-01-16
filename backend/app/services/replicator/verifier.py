"""
検証サービス

生成されたHTML/CSS/JSをPlaywrightで検証します。
"""
import base64
import logging
import os
from typing import Dict, Any
from playwright.async_api import async_playwright

from .image_comparator import ImageComparator

logger = logging.getLogger(__name__)

# 固定ビューポートサイズ（スクレイパーと同じ）
VIEWPORT_WIDTH = 1366
VIEWPORT_HEIGHT = 768


class VerificationError(Exception):
    """検証エラー"""
    pass


class Verifier:
    """検証クラス"""

    def __init__(self):
        self.comparator = ImageComparator()

    async def verify(
        self,
        original_url: str,
        generated_html_path: str,
        iteration: int
    ) -> Dict[str, Any]:
        """
        オリジナルと生成サイトを比較

        Args:
            original_url: オリジナルサイトURL
            generated_html_path: 生成されたHTMLファイルの絶対パス
            iteration: 検証イテレーション番号 (1-3)

        Returns:
            {
                "similarity_score": float,
                "diff_report": str,
                "diff_regions": list,
                "original_screenshot": str (base64),
                "generated_screenshot": str (base64)
            }

        Raises:
            VerificationError: 検証失敗時
        """
        logger.info(f"Verification iteration {iteration}: {original_url} vs {generated_html_path}")

        # ファイル存在確認
        if not os.path.exists(generated_html_path):
            raise VerificationError(f"Generated HTML not found: {generated_html_path}")

        async with async_playwright() as p:
            browser = None
            try:
                browser = await p.chromium.launch(headless=True)
                viewport = {"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}

                # オリジナルのスクリーンショット
                original_screenshot = await self._capture_screenshot(
                    browser, original_url, viewport, is_file=False
                )

                # 生成サイトのスクリーンショット
                generated_screenshot = await self._capture_screenshot(
                    browser, generated_html_path, viewport, is_file=True
                )

            except VerificationError:
                raise
            except Exception as e:
                raise VerificationError(f"Screenshot capture failed: {e}")
            finally:
                if browser:
                    await browser.close()

        # 画像比較
        comparison = self.comparator.compare(original_screenshot, generated_screenshot)

        # 差分レポート生成
        diff_report = self.comparator.generate_diff_report(comparison, iteration)

        return {
            "similarity_score": comparison["similarity"],
            "diff_report": diff_report,
            "diff_regions": comparison["diff_regions"],
            "diff_pixels": comparison["diff_pixels"],
            "original_screenshot": base64.b64encode(original_screenshot).decode(),
            "generated_screenshot": base64.b64encode(generated_screenshot).decode(),
        }

    async def _capture_screenshot(
        self,
        browser,
        url_or_path: str,
        viewport: Dict[str, int],
        is_file: bool = False
    ) -> bytes:
        """
        スクリーンショットを撮影

        Args:
            browser: Playwrightブラウザインスタンス
            url_or_path: URLまたはファイルパス
            viewport: ビューポートサイズ
            is_file: ファイルパスの場合True

        Returns:
            スクリーンショットのバイトデータ

        Raises:
            VerificationError: 撮影失敗時
        """
        context = await browser.new_context(viewport=viewport)
        page = await context.new_page()

        try:
            if is_file:
                # ローカルファイルの場合
                url = f"file://{url_or_path}"
            else:
                url = url_or_path

            await page.goto(url, wait_until="networkidle", timeout=30000)

            # 追加待機（レンダリング完了）
            await page.wait_for_timeout(1000)

            # フルページスクリーンショット
            screenshot = await page.screenshot(full_page=True)

            return screenshot

        except Exception as e:
            target = "file" if is_file else "URL"
            raise VerificationError(f"Failed to capture {target} screenshot: {e}")
        finally:
            await context.close()

    async def quick_check(self, html_path: str) -> bool:
        """
        HTMLファイルが正しく表示できるかクイックチェック

        Args:
            html_path: HTMLファイルパス

        Returns:
            表示できればTrue
        """
        if not os.path.exists(html_path):
            return False

        async with async_playwright() as p:
            browser = None
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                await page.goto(f"file://{html_path}", wait_until="domcontentloaded", timeout=10000)

                # ページにコンテンツがあるか確認
                content = await page.content()
                return len(content) > 100

            except Exception as e:
                logger.warning(f"Quick check failed: {e}")
                return False
            finally:
                if browser:
                    await browser.close()
