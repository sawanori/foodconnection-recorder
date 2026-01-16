"""
サイトスクレイパー

Playwrightを使用してWebサイトの素材を収集します。
"""
import base64
import json
import logging
from typing import Dict, Any
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

# 固定ビューポートサイズ
VIEWPORT_WIDTH = 1366
VIEWPORT_HEIGHT = 768

# データサイズ制限（Claude コンテキスト制限対策）
MAX_DATA_SIZE = 100000  # 100KB
MAX_ELEMENTS = 500
MAX_STYLESHEETS = 5


class ScrapingError(Exception):
    """スクレイピングエラー"""
    pass


class SiteScraper:
    """サイトスクレイパークラス"""

    async def scrape(self, url: str, timeout: int = 30000) -> Dict[str, Any]:
        """
        サイトの素材を収集

        Args:
            url: スクレイピング対象URL
            timeout: タイムアウト（ミリ秒）

        Returns:
            スクレイピングデータ辞書

        Raises:
            ScrapingError: スクレイピング失敗時
        """
        async with async_playwright() as p:
            browser = None
            try:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
                )
                page = await context.new_page()

                logger.info(f"Scraping: {url}")

                # ページ読み込み
                try:
                    await page.goto(url, wait_until="networkidle", timeout=timeout)
                except Exception as e:
                    raise ScrapingError(f"Failed to load page: {url} - {e}")

                # 追加待機（動的コンテンツ）
                await page.wait_for_timeout(2000)

                # データ収集
                data = {
                    "url": url,
                    "title": await page.title(),
                    "html": await page.content(),
                    "viewport": {
                        "width": VIEWPORT_WIDTH,
                        "height": VIEWPORT_HEIGHT
                    },
                }

                # 計算済みスタイル取得
                data["computed_styles"] = await self._extract_computed_styles(page)

                # 外部スタイルシート取得
                data["stylesheets"] = await self._extract_stylesheets(page)

                # スクリーンショット（Base64）
                screenshot_bytes = await page.screenshot(full_page=True)
                data["screenshot_base64"] = base64.b64encode(screenshot_bytes).decode()

                # データサイズチェック・簡略化
                data = self._optimize_data_size(data)

                logger.info(f"Scraping completed: {url}")
                return data

            except ScrapingError:
                raise
            except Exception as e:
                raise ScrapingError(f"Unexpected error during scraping: {e}")
            finally:
                if browser:
                    await browser.close()

    async def _extract_computed_styles(self, page) -> list:
        """計算済みスタイルを抽出"""
        try:
            return await page.evaluate(f"""
                () => {{
                    const elements = document.querySelectorAll('*');
                    const styles = [];
                    const maxElements = {MAX_ELEMENTS};

                    for (let i = 0; i < Math.min(elements.length, maxElements); i++) {{
                        const el = elements[i];
                        const cs = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();

                        styles.push({{
                            tag: el.tagName.toLowerCase(),
                            id: el.id || null,
                            classes: el.className || null,
                            rect: {{
                                x: Math.round(rect.x),
                                y: Math.round(rect.y),
                                width: Math.round(rect.width),
                                height: Math.round(rect.height)
                            }},
                            styles: {{
                                color: cs.color,
                                backgroundColor: cs.backgroundColor,
                                fontSize: cs.fontSize,
                                fontFamily: cs.fontFamily,
                                fontWeight: cs.fontWeight,
                                lineHeight: cs.lineHeight,
                                textAlign: cs.textAlign,
                                margin: cs.margin,
                                padding: cs.padding,
                                border: cs.border,
                                borderRadius: cs.borderRadius,
                                display: cs.display,
                                position: cs.position,
                                top: cs.top,
                                left: cs.left,
                                width: cs.width,
                                height: cs.height,
                                flexDirection: cs.flexDirection,
                                justifyContent: cs.justifyContent,
                                alignItems: cs.alignItems,
                                gap: cs.gap,
                                backgroundImage: cs.backgroundImage,
                                boxShadow: cs.boxShadow,
                                opacity: cs.opacity,
                                transform: cs.transform,
                                zIndex: cs.zIndex
                            }}
                        }});
                    }}
                    return styles;
                }}
            """)
        except Exception as e:
            logger.warning(f"Failed to extract computed styles: {e}")
            return []

    async def _extract_stylesheets(self, page) -> list:
        """外部スタイルシートを抽出"""
        try:
            return await page.evaluate(f"""
                () => {{
                    const sheets = [];
                    const maxSheets = {MAX_STYLESHEETS};

                    for (let i = 0; i < Math.min(document.styleSheets.length, maxSheets); i++) {{
                        const sheet = document.styleSheets[i];
                        try {{
                            const rules = [];
                            for (const rule of sheet.cssRules) {{
                                rules.push(rule.cssText);
                            }}
                            if (rules.length > 0) {{
                                sheets.push(rules.join('\\n'));
                            }}
                        }} catch (e) {{
                            // CORSエラーは無視
                        }}
                    }}
                    return sheets;
                }}
            """)
        except Exception as e:
            logger.warning(f"Failed to extract stylesheets: {e}")
            return []

    def _optimize_data_size(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """データサイズを最適化"""
        # スクリーンショットを除いたサイズをチェック
        data_without_screenshot = {k: v for k, v in data.items() if k != "screenshot_base64"}
        data_str = json.dumps(data_without_screenshot, ensure_ascii=False)

        if len(data_str) > MAX_DATA_SIZE:
            logger.warning(f"Data size ({len(data_str)}) exceeds limit, optimizing...")

            # スタイルを削減
            if len(data.get("computed_styles", [])) > 100:
                data["computed_styles"] = data["computed_styles"][:100]

            # スタイルシートを削減
            if len(data.get("stylesheets", [])) > 3:
                data["stylesheets"] = data["stylesheets"][:3]

            # 再チェック
            data_str = json.dumps(data_without_screenshot, ensure_ascii=False)
            logger.info(f"Optimized data size: {len(data_str)}")

        return data
