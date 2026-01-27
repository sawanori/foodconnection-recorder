"""
マルチセクション画像ジェネレーター

フルページスクリーンショットを複数セクションに分割して生成し、
最後に結合します。
"""
import io
import logging
from typing import Dict, List
from PIL import Image

from .base_image_generator import (
    BaseImageGenerator,
    ImageGenerationError,
    SYSTEM_PROMPT,
)

logger = logging.getLogger(__name__)

# セクション生成プロンプト
SECTION_PROMPT_FIRST = """
添付画像はWebページの**最初のセクション全体**です。
この画像に表示されている**全てのコンテンツを、上から下まで漏れなく**、ピクセル単位で完璧に再現するコードを生成してください。

⚠️ 重要:
- 画像の**上部だけでなく、下部まで含めて全てのセクション**を実装してください
- ヘッダー、ヒーロー、その下の説明文、画像ギャラリー、製品カードなど、**画像に見える全ての要素**を含めてください
- 「一部だけ」や「主要部分のみ」ではなく、**画像全体**を再現してください

## 提供されたリソース
- デザイン要素（優先）:
  - 色: {design_colors}
  - フォント: {design_fonts}

## 実装要件
1. **構造**: `<!DOCTYPE html>` `<html>` `<head>` `<body>` を含む、ページの開始部分を作成してください。
   - 終了タグ `</body>` `</html>` は**絶対に含めないでください**（後続のセクションを連結するため）。
2. **Head情報**:
   - 適切な `<meta name="viewport" ...>`
   - Zoom禁止などの余計な設定はしない
   - CSSリンク: `<link rel="stylesheet" href="styles.css">`
3. **デザイン再現**:
   - ビューポート幅: {viewport_width}px
   - 画像に表示されている**全てのコンテンツ**（上から下まで）を忠実に再現
   - ヘッダーのナビゲーションアイテムの間隔、フォントサイズ、ロゴの位置を正確に再現
   - ヒーロー画像の配置、上に重なるテキストのスタイル（影、太さ）を忠実に再現
   - **ヒーロー以降の全てのセクション**（説明文、画像ギャラリー、製品リストなど）も含める
   - **Box Model**: 全要素に `box-sizing: border-box;`
4. **ヒーローセクション高さの必須ルール**:
   ヒーローセクションには以下のCSS設定を必ず適用してください：

   ```css
   .hero {{
     height: 80vh;  /* PCデバイス: 画面の80% */
   }}

   @media (max-width: 1023px) {{
     .hero {{
       height: 100vh;  /* タブレット・スマホ: 画面の100% */
     }}
   }}
   ```

   重要事項:
   - PC（1024px以上）: height: 80vh
   - タブレット・スマホ（1023px以下）: height: 100vh
   - min-heightではなくheightを使用すること
5. **レスポンシブ**:
   - モバイル（max-width: 768px）表示時の考慮（ハンバーガーメニューのHTML構造など）を含めてください。

## 出力形式（JSONのみ）
{{
  "html": "<!DOCTYPE html>... (</body>なし)",
  "css": "/* 共通設定（:root変数など）とこのセクションのCSS */...",
  "js": "// このセクションに必要なJS..."
}}
"""

SECTION_PROMPT_MIDDLE = """
添付画像はWebページの**中間セクション全体**（{section_num}番目）です。
前のセクションから続くコンテンツとして、この画像に表示されている**全ての要素を上から下まで漏れなく**実装してください。

⚠️ 重要:
- 画像に表示されている**全てのコンテンツ**を含めてください
- 画像の上部だけでなく、**下部まで含めて全体**を実装してください
- 製品カード、説明文、画像、ボタンなど、**見える全ての要素**を再現してください

## 実装要件
1. **構造**:
   - `html`, `head`, `body` タグは**含めないでください**。
   - `<section>` や `<div>` から書き始めてください。
   - 画像に表示されている**全てのセクション**を含めてください
2. **デザインの一貫性**:
   - 提供されたデザイン要素（{design_colors}, {design_fonts}）を使用してください。
   - レイアウト（コンテナ幅、余白）の一貫性を維持してください。
3. **画像処理**:
   - プレースホルダー画像: `https://picsum.photos/幅/高さ?random={image_start_num}`
   - `object-fit` 等を使って画像の表示領域を守ってください。

## 出力形式（JSONのみ）
{{
  "html": "<section class='section-middle'>...</section>",
  "css": "/* このセクション固有のCSS */...",
  "js": "// このセクションに必要なJS（あれば）..."
}}
"""

SECTION_PROMPT_LAST = """
添付画像はWebページの**最終セクション全体（フッター含む）**です。
この画像に表示されている**全ての要素を上から下まで漏れなく**実装し、ページを締めくくってHTMLドキュメントを閉じてください。

⚠️ 重要:
- 画像に表示されている**全てのコンテンツ**を含めてください
- フッターの前にある全てのセクション、コンテンツも含めてください
- 画像の上部から下部まで、**全体**を再現してください

## 実装要件
1. **構造**:
   - コンテンツ（`<section>`や`<footer>`など、画像に表示されている全てのセクション）を作成。
   - 最後に `<script src="script.js"></script>` を挿入。
   - 最期に `</body>` と `</html>` を**必ず含めてください**。
2. **デザイン再現**:
   - 画像に表示されている**全てのセクション**を忠実に再現
   - フッターのカラムレイアウト、コピーライトの配置などを正確に再現。
   - 背景色やテキスト色のコントラストに注意（デザイン要素: {design_colors} 参照）。
3. **画像**:
   - プレースホルダー: `https://picsum.photos/幅/高さ?random={image_start_num}`

## 出力形式（JSONのみ）
{{
  "html": "<footer>...</footer>\\n<script src=\\"script.js\\"></script>\\n</body>\\n</html>",
  "css": "/* フッター等のCSS */...",
  "js": "// フッター等のJS..."
}}
"""


class MultiSectionGenerator:
    """複数セクションに分割して画像から生成するジェネレーター"""

    def __init__(self, base_generator: BaseImageGenerator, num_sections: int = 3):
        """
        Args:
            base_generator: ベースとなる画像ジェネレーター
            num_sections: 分割するセクション数（3-8）
        """
        self.generator = base_generator
        self.num_sections = max(3, min(8, num_sections))
        logger.info(f"Multi-section generator initialized with {self.num_sections} sections")

    def _split_image(self, img: Image.Image) -> List[Image.Image]:
        """
        画像を複数セクションに分割

        Args:
            img: 分割する画像

        Returns:
            分割された画像のリスト
        """
        width, height = img.size
        section_height = height // self.num_sections
        overlap = 50  # オーバーラップを50ピクセルに削減

        sections = []
        for i in range(self.num_sections):
            start_y = max(0, i * section_height - (overlap if i > 0 else 0))
            end_y = min(height, (i + 1) * section_height + (overlap if i < self.num_sections - 1 else 0))

            section = img.crop((0, start_y, width, end_y))
            sections.append(section)

            # 推定サイズをログ出力
            estimated_size = (section.width * section.height * 3) / (1024 * 1024)
            logger.info(f"Section {i+1}: size={section.size}, estimated_size={estimated_size:.2f}MB")

        return sections

    async def generate_from_fullpage(
        self,
        image_path: str,
        design_tokens: dict = None,
        video_path: str = None
    ) -> Dict[str, str]:
        """
        フルページ画像から複数セクションに分割して生成

        Args:
            image_path: 画像ファイルパス
            design_tokens: デザイン要素
            video_path: 動画ファイルパス（オプション）

        Returns:
            統合されたHTML/CSS/JSコード
        """
        img = Image.open(image_path)
        logger.info(f"Full page image size: {img.size}")

        # 画像を分割
        sections = self._split_image(img)
        logger.info(f"Split into {len(sections)} sections")

        # 各セクションを生成
        results = []
        for i, section_img in enumerate(sections):
            section_number = i + 1
            logger.info(f"Generating section {section_number}/{len(sections)}...")

            # プロンプト選択
            if i == 0:
                prompt = SECTION_PROMPT_FIRST.format(
                    design_colors=design_tokens.get('colors', []) if design_tokens else [],
                    design_fonts=design_tokens.get('fonts', []) if design_tokens else [],
                    viewport_width=section_img.width
                )
            elif i == len(sections) - 1:
                prompt = SECTION_PROMPT_LAST.format(
                    design_colors=design_tokens.get('colors', []) if design_tokens else [],
                    design_fonts=design_tokens.get('fonts', []) if design_tokens else [],
                    image_start_num=(i * 10) + 1
                )
            else:
                prompt = SECTION_PROMPT_MIDDLE.format(
                    section_num=section_number,
                    design_colors=design_tokens.get('colors', []) if design_tokens else [],
                    design_fonts=design_tokens.get('fonts', []) if design_tokens else [],
                    image_start_num=(i * 10) + 1
                )

            # セクション生成（リトライ機能付き）
            result = await self._generate_section(section_img, prompt, section_number)
            results.append(result)

        # 結果を統合
        return self._merge_results(results)

    async def _generate_section(
        self,
        img: Image.Image,
        prompt: str,
        section_number: int = 0,
        max_retries: int = 3,
        retry_delay_base: float = 2.0
    ) -> Dict[str, str]:
        """
        セクションを生成（リトライ機能付き）

        Args:
            img: セクション画像
            prompt: 生成プロンプト
            section_number: セクション番号（ログ用）
            max_retries: 最大リトライ回数
            retry_delay_base: リトライ遅延の基数（秒）

        Returns:
            生成されたコード

        Raises:
            ImageGenerationError: 全リトライ失敗時
        """
        import asyncio
        import anthropic
        from .base_image_generator import ImageGenerationError

        last_exception = None

        for attempt in range(max_retries):
            try:
                logger.info(f"Section {section_number}: Attempt {attempt+1}/{max_retries}")

                # 画像をBase64エンコード（Phase 1で強化された検証機能を使用）
                image_data, media_type = self.generator._encode_image_to_base64(img)

                # Base64サイズをログ出力
                base64_size = len(image_data.encode('utf-8')) / 1024 / 1024
                logger.info(f"Section {section_number}: Base64 size = {base64_size:.2f}MB")

                # API呼び出し（ベースジェネレーターの内部メソッドを使用）
                # マルチセクション時はセクション専用プロンプトを使用するため、
                # システムプロンプトは使用しない（プロンプトの競合を防ぐ）
                result = await self.generator._call_api_with_image(
                    image_data, media_type, prompt, use_system_prompt=False
                )

                logger.info(f"Section {section_number}: Success on attempt {attempt+1}")
                return result

            except anthropic.APIError as e:
                last_exception = e
                error_message = str(e)

                # 画像サイズ超過エラーの特別処理
                if "exceeds 5 MB maximum" in error_message or "image" in error_message.lower():
                    logger.error(
                        f"Section {section_number}: Image size error on attempt {attempt+1}: {error_message}"
                    )
                    # 画像を更に圧縮して再試行
                    if attempt < max_retries - 1:
                        logger.info(f"Section {section_number}: Compressing image further...")
                        # より積極的な圧縮（3.6MB → 3.0MB → 2.5MB）
                        max_size = 3_600_000 - (attempt * 550_000)
                        # 次回の試行で使用するため、画像を縮小
                        scale = 0.9 - (attempt * 0.1)
                        new_width = int(img.width * scale)
                        new_height = int(img.height * scale)
                        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                        logger.info(f"Section {section_number}: Resized to {img.size}")
                        continue

                # レート制限エラー
                elif "rate_limit" in error_message.lower() or "429" in error_message:
                    logger.warning(f"Section {section_number}: Rate limit on attempt {attempt+1}")
                    if attempt < max_retries - 1:
                        # レート制限の場合はより長く待機
                        delay = retry_delay_base ** (attempt + 2)
                        logger.info(f"Section {section_number}: Waiting {delay:.1f}s for rate limit...")
                        await asyncio.sleep(delay)
                        continue

                # その他のAPIエラー
                else:
                    logger.error(f"Section {section_number}: API error on attempt {attempt+1}: {error_message}")
                    if attempt < max_retries - 1:
                        delay = retry_delay_base ** attempt
                        logger.info(f"Section {section_number}: Retrying after {delay:.1f}s...")
                        await asyncio.sleep(delay)
                        continue

            except Exception as e:
                last_exception = e
                logger.error(
                    f"Section {section_number}: Unexpected error on attempt {attempt+1}: {e}",
                    exc_info=True
                )
                if attempt < max_retries - 1:
                    delay = retry_delay_base ** attempt
                    logger.info(f"Section {section_number}: Retrying after {delay:.1f}s...")
                    await asyncio.sleep(delay)
                    continue

        # 全リトライ失敗
        logger.error(f"Section {section_number}: All {max_retries} attempts failed")
        raise ImageGenerationError(
            f"Section {section_number} generation failed after {max_retries} attempts: {last_exception}"
        )

    def _merge_results(self, results: List[Dict[str, str]]) -> Dict[str, str]:
        """
        複数セクションの結果を統合

        Args:
            results: 各セクションの生成結果

        Returns:
            統合されたHTML/CSS/JS
        """
        import re

        # HTMLを結合
        html_parts = []
        for i, result in enumerate(results):
            html = result.get('html', '')

            if i == 0:
                # 最初のセクション: そのまま
                html_parts.append(html)
            elif i == len(results) - 1:
                # 最後のセクション: そのまま
                html_parts.append(html)
            else:
                # 中間セクション: そのまま
                html_parts.append(html)

        merged_html = '\n'.join(html_parts)

        # HTML構造を検証・修正
        if not merged_html.strip().endswith('</html>'):
            logger.warning("HTML does not end with </html>, appending...")
            if not '</body>' in merged_html[-100:]:
                merged_html += '\n</body>'
            merged_html += '\n</html>'

        if not merged_html.strip().startswith('<!DOCTYPE html>'):
            logger.warning("HTML does not start with <!DOCTYPE html>, prepending...")
            merged_html = '<!DOCTYPE html>\n' + merged_html

        # 不正なタグを削除
        merged_html = re.sub(r'</?(html|head|body)>(?=.*</\1>)', '', merged_html, flags=re.DOTALL)

        # CSSを統合
        css_parts = [result.get('css', '') for result in results]
        merged_css = '\n\n'.join(css_parts)

        # JSを統合
        js_parts = [result.get('js', '') for result in results]
        merged_js = '\n\n'.join(js_parts)

        logger.info(f"Merged results: HTML={len(merged_html)} chars, CSS={len(merged_css)} chars, JS={len(merged_js)} chars")

        return {
            'html': merged_html,
            'css': merged_css,
            'js': merged_js
        }
