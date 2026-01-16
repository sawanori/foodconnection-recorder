"""
スクレイピングサービス

Playwrightを使用してWebページからデータを抽出します。
"""
import re
from typing import List, Dict, Optional
from playwright.async_api import async_playwright, Page
from app.config import settings
from app.utils.filename import sanitize_filename
from app.services.errors import NetworkError, TimeoutError, ElementNotFoundError

# 除外するパス（ポートフォリオ以外のページ）
EXCLUDED_PATHS = {
    'category', 'page', 'post-district', 'tokushu', 'reason',
    'effort', 'number', 'info', 'siryo', 'otherreview', 'dl_file_form',
    'dl_helpful_index', 'plan', 'faq', 'privacy', 'cookie'
}


class ScraperService:
    """スクレイピングサービスクラス"""

    def _is_valid_shop_url(self, href: str) -> bool:
        """
        URLがショップポートフォリオページかどうかを判定

        Args:
            href: チェックするURL

        Returns:
            ショップURLの場合True
        """
        # 単一セグメントのパス（/shopname/）のみ許可
        match = re.match(r'https?://f-webdesign\.biz/([^/]+)/$', href)
        if not match:
            return False

        slug = match.group(1)
        # 除外パスをチェック
        if slug in EXCLUDED_PATHS:
            return False

        # URLエンコードされた日本語も許可（%で始まる場合）
        return True

    async def extract_detail_urls(self, list_url: str) -> List[str]:
        """
        一覧ページから詳細ページURLを抽出

        Args:
            list_url: 一覧ページのURL

        Returns:
            詳細ページURLのリスト

        Raises:
            NetworkError: ネットワークエラー
            TimeoutError: タイムアウトエラー
        """
        async with async_playwright() as p:
            browser = None
            try:
                browser = await p.chromium.launch(
                    headless=settings.PLAYWRIGHT_HEADLESS
                )
                context = await browser.new_context()
                page = await context.new_page()

                # ページ遷移
                try:
                    await page.goto(
                        list_url,
                        wait_until="networkidle",
                        timeout=settings.PLAYWRIGHT_TIMEOUT
                    )
                except Exception as e:
                    if "timeout" in str(e).lower():
                        raise TimeoutError(f"Page load timeout: {list_url}") from e
                    raise NetworkError(f"Failed to load page: {list_url}") from e

                # 全リンク取得してフィルタリング
                links = await page.query_selector_all("a[href*='f-webdesign.biz']")

                urls = []
                for link in links:
                    href = await link.get_attribute("href")
                    if href and self._is_valid_shop_url(href):
                        if href not in urls:
                            urls.append(href)

                return urls

            except (NetworkError, TimeoutError):
                raise
            except Exception as e:
                raise NetworkError(f"Unexpected error during URL extraction: {e}") from e
            finally:
                if browser:
                    await browser.close()

    async def extract_shop_data(self, detail_url: str) -> Dict[str, Optional[str]]:
        """
        詳細ページから店舗データを抽出

        Args:
            detail_url: 詳細ページURL

        Returns:
            店舗データ辞書
            {
                "shop_name": str | None,
                "shop_name_sanitized": str | None,
                "shop_url": str | None
            }

        Raises:
            NetworkError: ネットワークエラー
            TimeoutError: タイムアウトエラー
            ElementNotFoundError: 要素未検出エラー
        """
        async with async_playwright() as p:
            browser = None
            try:
                browser = await p.chromium.launch(
                    headless=settings.PLAYWRIGHT_HEADLESS
                )
                context = await browser.new_context()
                page = await context.new_page()

                # ページ遷移
                try:
                    await page.goto(
                        detail_url,
                        wait_until="networkidle",
                        timeout=settings.PLAYWRIGHT_TIMEOUT
                    )
                    # 追加待機（動的コンテンツの読み込み）
                    await page.wait_for_timeout(1000)
                except Exception as e:
                    if "timeout" in str(e).lower():
                        raise TimeoutError(f"Page load timeout: {detail_url}") from e
                    raise NetworkError(f"Failed to load page: {detail_url}") from e

                # 店舗名取得
                shop_name = await self._extract_shop_name(page)
                if not shop_name:
                    raise ElementNotFoundError(f"Shop name not found: {detail_url}")

                # 店舗URL取得
                shop_url = await self._extract_shop_url(page)

                return {
                    "shop_name": shop_name,
                    "shop_name_sanitized": sanitize_filename(shop_name) if shop_name else None,
                    "shop_url": shop_url,
                }

            except (NetworkError, TimeoutError, ElementNotFoundError):
                raise
            except Exception as e:
                raise NetworkError(f"Unexpected error during data extraction: {e}") from e
            finally:
                if browser:
                    await browser.close()

    async def _extract_shop_name(self, page: Page) -> Optional[str]:
        """
        店舗名抽出（パンくずリストから取得）

        Args:
            page: Playwrightページオブジェクト

        Returns:
            店舗名（見つからない場合はNone）
        """
        try:
            # パンくずリスト（「トップ」を含むリスト）を探して最後のliを取得
            lists = await page.query_selector_all("ol, ul")
            for list_el in lists:
                items = await list_el.query_selector_all("li")
                if len(items) >= 2 and len(items) <= 5:
                    first_item = items[0]
                    first_text = await first_item.inner_text()
                    if "トップ" in first_text:
                        last_item = items[-1]
                        shop_name = await last_item.inner_text()
                        return shop_name.strip()
        except Exception:
            # エラーは無視してNoneを返す
            pass
        return None

    async def _extract_shop_url(self, page: Page) -> Optional[str]:
        """
        店舗URL抽出（dt「URL」の隣のddからリンクを取得）

        Args:
            page: Playwrightページオブジェクト

        Returns:
            店舗URL（見つからない場合はNone）
        """
        try:
            # dt要素から「URL」というテキストを持つものを探す
            dt_elements = await page.query_selector_all("dt")
            for dt in dt_elements:
                text = await dt.inner_text()
                if "URL" in text:
                    # 次のdd要素を取得
                    dd = await dt.evaluate_handle(
                        "el => el.nextElementSibling"
                    )
                    if dd:
                        dd_element = dd.as_element()
                        if dd_element:
                            link = await dd_element.query_selector("a")
                            if link:
                                href = await link.get_attribute("href")
                                if href:
                                    return href
        except Exception:
            # エラーは無視
            pass

        # 代替: 外部URLへのリンクを探す（f-webdesign以外）
        try:
            links = await page.query_selector_all("a[href^='http']")
            for link in links:
                href = await link.get_attribute("href")
                if href and "f-webdesign" not in href and "lin.ee" not in href:
                    return href
        except Exception:
            pass

        return None
