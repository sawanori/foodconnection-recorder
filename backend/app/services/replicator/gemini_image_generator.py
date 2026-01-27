"""
Gemini画像ベースジェネレーター

Google GenAI SDKを使用してスクリーンショット画像からHTML/CSS/JSを生成します。
動画入力にも対応しています。
"""
import base64
import io
import logging
import os
from pathlib import Path
from typing import Dict, Optional

from google import genai
from google.genai import types
from PIL import Image

from .base_image_generator import (
    BaseImageGenerator,
    ImageGenerationError,
    SYSTEM_PROMPT,
    GENERATE_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)


class GeminiImageGenerator(BaseImageGenerator):
    """Gemini（Google）を使用した画像ベースジェネレーター"""

    def __init__(self, model: str = "gemini-3-flash-preview"):
        """
        Args:
            model: 使用するGeminiモデル
                   - gemini-3-flash-preview: Gemini 3 Flash（推奨・最新）
                   - gemini-3-pro-preview: Gemini 3 Pro
                   - gemini-2.5-flash: 安定版
        """
        self.model = model

        # API keyの設定
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ImageGenerationError(
                "GOOGLE_API_KEY or GEMINI_API_KEY environment variable is required for Gemini"
            )

        self.client = genai.Client(api_key=api_key)

    def get_model_name(self) -> str:
        """使用しているモデル名を返す"""
        return f"Gemini ({self.model})"

    async def generate_from_image(
        self,
        image_path: str,
        html_content: Optional[str] = None,
        video_path: Optional[str] = None,
        viewport_width: int = 1366,
        viewport_height: int = 768,
        design_tokens: Optional[Dict] = None
    ) -> Dict[str, str]:
        """
        スクリーンショット画像からHTML/CSS/JSを生成

        Args:
            image_path: スクリーンショット画像のパス
            html_content: オリジナルHTMLソース（オプション）
            video_path: 録画ビデオパス（オプション）
            viewport_width: ビューポート幅
            viewport_height: ビューポート高さ
            design_tokens: デザイントークン（オプション）

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            ImageGenerationError: 生成失敗時
        """
        # 画像を前処理
        img, _ = self._prepare_image(image_path)

        # Base64エンコード
        image_data, media_type = self._encode_image_to_base64(img)

        # HTMLコンテキストの準備
        if html_content:
            # 中括弧をエスケープ（.format()対策）
            html_context = html_content.replace('{', '{{').replace('}', '}}')
            logger.info(f"Using HTML context: {len(html_content)} chars")
        else:
            html_context = "（提供なし）"

        # デザイン要素の準備
        if design_tokens:
            design_colors = ", ".join(design_tokens.get("colors", []))
            design_fonts = ", ".join(design_tokens.get("fonts", []))
        else:
            design_colors = "（画像から推測してください）"
            design_fonts = "（画像から推測してください）"

        # プロンプト生成
        prompt = self._build_full_prompt(viewport_width, viewport_height, html_context, design_colors, design_fonts)

        # 動画がある場合は動画付きで呼び出し
        if video_path and Path(video_path).exists():
            logger.info(f"Using video input: {video_path}")
            video_data, video_media_type = self._encode_video_to_base64(video_path)
            if video_data:
                return await self._call_api_with_image_and_video(
                    image_data, media_type, video_data, video_media_type, prompt
                )
            else:
                logger.warning("Failed to encode video, falling back to image-only")

        return await self._call_api_with_image(image_data, media_type, prompt)

    def _build_full_prompt(
        self,
        viewport_width: int,
        viewport_height: int,
        html_context: str = "（提供なし）",
        design_colors: str = "（画像から推測してください）",
        design_fonts: str = "（画像から推測してください）"
    ) -> str:
        """システムプロンプトと生成プロンプトを結合"""
        try:
            generation_prompt = GENERATE_PROMPT_TEMPLATE.format(
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                html_context=html_context,
                design_colors=design_colors,
                design_fonts=design_fonts
            )
        except KeyError as e:
            # テンプレート側のプレースホルダと合わない場合のフォールバック
            logger.warning(f"Failed to format prompt with html_context: {e}. Falling back.")
            generation_prompt = f"""
            Generate HTML/CSS/JS from this image.
            Viewport: {viewport_width}x{viewport_height}
            """
        return f"{SYSTEM_PROMPT}\n\n{generation_prompt}"

    async def _call_api_with_image(
        self,
        image_data: str,
        media_type: str,
        prompt: str,
        use_system_prompt: bool = True
    ) -> Dict[str, str]:
        """
        画像付きでGemini APIを呼び出し

        Args:
            image_data: base64エンコードされた画像
            media_type: 画像のメディアタイプ
            prompt: プロンプト
            use_system_prompt: 互換性のためのパラメータ（Geminiでは使用しない）

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            ImageGenerationError: 呼び出し失敗時
        """
        logger.info(f"Calling Gemini API ({self.model}) with image...")

        try:
            # base64からバイトに変換
            import base64
            image_bytes = base64.b64decode(image_data)

            # Gemini APIを呼び出し
            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(
                                data=image_bytes,
                                mime_type=media_type
                            ),
                            types.Part.from_text(text=prompt)
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=16384,
                    temperature=0.2,
                )
            )

            # レスポンスの確認
            if not response.text:
                raise ImageGenerationError("Empty response from Gemini API")

            result_text = response.text
            logger.info(f"Gemini API response received (length={len(result_text)})")

            return self._parse_response(result_text)

        except Exception as e:
            error_msg = str(e)
            if "SAFETY" in error_msg.upper():
                raise ImageGenerationError(f"Content was blocked by safety filters: {e}")
            elif "QUOTA" in error_msg.upper() or "RATE" in error_msg.upper():
                raise ImageGenerationError(f"Rate limit or quota exceeded: {e}")
            elif "API_KEY" in error_msg.upper() or "401" in error_msg:
                raise ImageGenerationError(f"Invalid API key: {e}")
            else:
                raise ImageGenerationError(f"Gemini API error: {e}")

    async def fix_code(
        self,
        current_code: Dict[str, str],
        diff_report: str,
        image_path: Optional[str] = None
    ) -> Dict[str, str]:
        """
        コードを修正

        Args:
            current_code: 現在のコード
            diff_report: 差分レポート
            image_path: オリジナル画像パス（参照用）

        Returns:
            修正後のコード
        """
        from .base_image_generator import FIX_CODE_PROMPT_TEMPLATE

        logger.info("Fixing code based on verification report...")

        # プロンプト作成
        prompt = FIX_CODE_PROMPT_TEMPLATE.format(diff_report=diff_report)

        # 現在のコードを追加
        prompt += "\n\n## 現在のコード\n"
        prompt += f"### HTML\n```html\n{current_code.get('html', '')}\n```\n\n"
        prompt += f"### CSS\n```css\n{current_code.get('css', '')}\n```\n\n"
        if current_code.get('js'):
            prompt += f"### JavaScript\n```javascript\n{current_code.get('js', '')}\n```\n\n"

        # フルプロンプトを作成
        full_prompt = f"{SYSTEM_PROMPT}\n\n{prompt}"

        # 画像がある場合は画像付きで呼び出し
        if image_path:
            img, _ = self._prepare_image(image_path)
            image_data, media_type = self._encode_image_to_base64(img)
            return await self._call_api_with_image(image_data, media_type, full_prompt)
        else:
            # 画像なしでテキストのみで呼び出し
            return await self._call_api_text_only(full_prompt)

    async def _call_api_text_only(self, prompt: str) -> Dict[str, str]:
        """テキストのみでAPIを呼び出し"""
        logger.info(f"Calling Gemini API ({self.model}) without image...")

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_text(text=prompt)
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=16384,
                    temperature=0.2,
                )
            )

            if not response.text:
                raise ImageGenerationError("Empty response from Gemini API")

            result_text = response.text
            logger.info(f"Gemini API response received (length={len(result_text)})")

            return self._parse_response(result_text)

        except Exception as e:
            error_msg = str(e)
            if "SAFETY" in error_msg.upper():
                raise ImageGenerationError(f"Content was blocked by safety filters: {e}")
            elif "QUOTA" in error_msg.upper() or "RATE" in error_msg.upper():
                raise ImageGenerationError(f"Rate limit or quota exceeded: {e}")
            elif "API_KEY" in error_msg.upper() or "401" in error_msg:
                raise ImageGenerationError(f"Invalid API key: {e}")
            else:
                raise ImageGenerationError(f"Gemini API error: {e}")

    def _encode_video_to_base64(self, video_path: str) -> tuple[Optional[str], str]:
        """
        動画をBase64エンコード

        Args:
            video_path: 動画ファイルパス

        Returns:
            (base64データ, メディアタイプ) または (None, "") エラー時
        """
        try:
            video_file = Path(video_path)
            if not video_file.exists():
                logger.error(f"Video file not found: {video_path}")
                return None, ""

            # ファイルサイズチェック（Geminiの制限）
            file_size = video_file.stat().st_size
            max_size = 20 * 1024 * 1024  # 20MB
            if file_size > max_size:
                logger.warning(f"Video file too large ({file_size / 1024 / 1024:.1f}MB > 20MB), skipping video input")
                return None, ""

            # 拡張子からメディアタイプを判定
            extension = video_file.suffix.lower()
            media_type_map = {
                ".webm": "video/webm",
                ".mp4": "video/mp4",
                ".mov": "video/quicktime",
                ".avi": "video/x-msvideo",
            }
            media_type = media_type_map.get(extension, "video/webm")

            # Base64エンコード
            with open(video_path, "rb") as f:
                video_data = base64.b64encode(f.read()).decode("utf-8")

            logger.info(f"Video encoded: {file_size / 1024 / 1024:.1f}MB, type={media_type}")
            return video_data, media_type

        except Exception as e:
            logger.error(f"Failed to encode video: {e}")
            return None, ""

    async def _call_api_with_image_and_video(
        self,
        image_data: str,
        image_media_type: str,
        video_data: str,
        video_media_type: str,
        prompt: str
    ) -> Dict[str, str]:
        """画像と動画付きでGemini APIを呼び出し"""
        logger.info("Calling Gemini API with image and video...")

        # 動画用の追加プロンプト
        video_prompt = """
## 追加リソース: 録画動画
添付の動画はWebページをスクロールしながら録画したものです。
動画から以下の情報を抽出して活用してください：
- スクロール中に表示される全セクションの詳細
- アニメーションやホバー効果
- 実際の画像の見た目
- コンテンツの配置と流れ

動画とスクリーンショットの両方を参考にして、より正確なHTML/CSS/JSを生成してください。
"""
        full_prompt = video_prompt + "\n\n" + prompt

        try:
            # base64からバイトに変換
            image_bytes = base64.b64decode(image_data)
            video_bytes = base64.b64decode(video_data)

            # Gemini APIを呼び出し（動画と画像の両方を含む）
            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(
                                data=video_bytes,
                                mime_type=video_media_type
                            ),
                            types.Part.from_bytes(
                                data=image_bytes,
                                mime_type=image_media_type
                            ),
                            types.Part.from_text(text=full_prompt)
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=16384,
                    temperature=0.2,
                )
            )

            if not response.text:
                raise ImageGenerationError("Empty response from Gemini API")

            result_text = response.text
            logger.info(f"Gemini API response with video received (length={len(result_text)})")

            return self._parse_response(result_text)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Gemini API error with video: {error_msg}")
            # 動画付きで失敗した場合、画像のみで再試行
            logger.info("Retrying with image only...")
            return await self._call_api_with_image(image_data, image_media_type, prompt)

    # ========================================
    # 3段階分割生成（Gemini用）
    # ========================================

    async def generate_three_step_v2(
        self,
        image_path: str,
        html_content: str,
        video_path: Optional[str] = None,
        design_tokens: Optional[Dict] = None
    ) -> Dict[str, str]:
        """
        3段階分割生成: HTMLを3分割 → 各パートCSS生成 → 結合 → JS生成

        Geminiは出力制限があるため、分割して生成する。

        Args:
            image_path: スクリーンショット画像パス
            html_content: 元のHTMLソース
            video_path: 録画動画パス（オプション）
            design_tokens: デザイン要素

        Returns:
            {"html": "...", "css": "...", "js": "..."}
        """
        import re

        logger.info("Starting Gemini 3-step generation with HTML splitting")

        # Step 1: HTMLクリーンアップ（ローカル処理）
        logger.info("Step 1: Cleaning up HTML...")
        clean_html = self._cleanup_html(html_content)
        logger.info(f"Step 1 complete: HTML length = {len(clean_html)}")

        # Step 2: HTMLを3分割してそれぞれCSS生成
        logger.info("Step 2: Splitting HTML and generating CSS for each part...")
        html_parts = self._split_html(clean_html, num_parts=3)
        logger.info(f"HTML split into {len(html_parts)} parts: {[len(p) for p in html_parts]} chars each")

        css_parts = []
        for i, html_part in enumerate(html_parts):
            # 空パートはスキップ
            if not html_part or len(html_part.strip()) < 50:
                logger.warning(f"Step 2.{i+1}: Skipping empty/short part {i+1}")
                css_parts.append("/* Empty part */")
                continue

            logger.info(f"Step 2.{i+1}: Generating CSS for part {i+1}/{len(html_parts)} ({len(html_part)} chars)...")
            try:
                css_part = await self._generate_css_for_part(image_path, html_part, design_tokens, i+1, len(html_parts))
                if css_part and len(css_part) > 20:
                    css_parts.append(css_part)
                    logger.info(f"Step 2.{i+1} complete: CSS part length = {len(css_part)}")
                else:
                    logger.warning(f"Step 2.{i+1}: CSS generation returned empty/short result")
                    css_parts.append(f"/* Part {i+1} - generation failed */")
            except Exception as e:
                logger.error(f"Step 2.{i+1} failed with error: {e}")
                css_parts.append(f"/* Part {i+1} - error: {str(e)[:100]} */")

        # CSS結合
        combined_css = "\n\n".join([f"/* Part {i+1} */\n{css}" for i, css in enumerate(css_parts)])
        logger.info(f"Step 2 complete: Combined CSS length = {len(combined_css)}")

        # Step 3: 動画からJS生成
        logger.info("Step 3: Generating JS from video...")
        js = await self._generate_js_from_video(video_path, clean_html, combined_css)
        logger.info(f"Step 3 complete: JS length = {len(js)}")

        return {
            "html": clean_html,
            "css": combined_css,
            "js": js
        }

    def _cleanup_html(self, html_content: str) -> str:
        """HTMLクリーンアップ（インラインスタイル・スクリプト削除）"""
        import re

        html = html_content
        # <style>タグを削除
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # <script>タグを削除
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
        # style属性を削除
        html = re.sub(r'\s+style\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)

        # 外部CSS/JSリンクを追加
        if '</head>' in html.lower():
            html = re.sub(
                r'(</head>)',
                '<link rel="stylesheet" href="styles.css">\n<script src="script.js" defer></script>\n\\1',
                html,
                flags=re.IGNORECASE
            )

        return html

    def _split_html(self, html_content: str, num_parts: int = 3) -> list:
        """HTMLをセクション単位で分割（タグを壊さない）"""
        import re

        # 主要なセクション終了タグで分割ポイントを探す
        section_pattern = r'(</(?:section|div|article|header|footer|main|nav|aside)>)'

        # 全てのセクション終了位置を取得
        split_points = [0]
        for match in re.finditer(section_pattern, html_content, re.IGNORECASE):
            split_points.append(match.end())
        split_points.append(len(html_content))

        # 分割ポイントが少ない場合は文字数ベースで安全に分割
        if len(split_points) < num_parts + 1:
            # 閉じタグの後で分割
            total_len = len(html_content)
            part_size = total_len // num_parts
            parts = []

            for i in range(num_parts):
                start = 0 if i == 0 else parts_ends[i-1] if i > 0 else 0
                target_end = (i + 1) * part_size if i < num_parts - 1 else total_len

                # target_end以降で最初の > を探す
                actual_end = html_content.find('>', target_end)
                if actual_end == -1 or actual_end > total_len:
                    actual_end = total_len
                else:
                    actual_end += 1  # > を含める

                if i == 0:
                    parts_ends = [actual_end]
                else:
                    parts_ends.append(actual_end)

            # パーツを作成
            parts = []
            prev_end = 0
            for end in parts_ends:
                parts.append(html_content[prev_end:end])
                prev_end = end

            return parts

        # セクション終了位置をnum_parts個に均等分配
        total_len = len(html_content)
        target_size = total_len // num_parts

        parts = []
        current_start = 0

        for i in range(num_parts - 1):
            target_end = (i + 1) * target_size

            # target_endに最も近い分割ポイントを探す
            best_point = split_points[1]  # デフォルトは最初の分割ポイント
            for point in split_points:
                if point > current_start and abs(point - target_end) < abs(best_point - target_end):
                    best_point = point

            # 分割ポイントが現在位置より後ろで、かつ全体の終わりでない場合のみ使用
            if best_point > current_start and best_point < total_len:
                parts.append(html_content[current_start:best_point])
                current_start = best_point

        # 最後のパート
        parts.append(html_content[current_start:])

        # パーツ数が足りない場合は補完
        while len(parts) < num_parts:
            parts.append("")

        return parts[:num_parts]

    async def _generate_css_for_part(
        self,
        image_path: str,
        html_part: str,
        design_tokens: Optional[Dict],
        part_num: int,
        total_parts: int
    ) -> str:
        """HTMLパートに対するCSSを生成"""
        # 画像を準備
        img, _ = self._prepare_image(image_path)
        image_data, media_type = self._encode_image_to_base64(img)

        # デザイン要素
        if design_tokens:
            design_colors = ", ".join(design_tokens.get("colors", []))
            design_fonts = ", ".join(design_tokens.get("fonts", []))
        else:
            design_colors = "（画像から推測）"
            design_fonts = "（画像から推測）"

        prompt = f"""スクリーンショット画像を参照して、以下のHTMLパート（{part_num}/{total_parts}）に対応するCSSを生成してください。

## HTMLパート {part_num}/{total_parts}
```html
{html_part[:15000]}
```

## デザイン要素
- 色: {design_colors}
- フォント: {design_fonts}

## 要件
- スクリーンショットの見た目を忠実に再現
- CSSのみを出力（HTMLやJSは不要）
- JSON形式で出力: {{"css": "..."}}
"""

        try:
            image_bytes = base64.b64decode(image_data)

            response = self.client.models.generate_content(
                model=self.model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_bytes(data=image_bytes, mime_type=media_type),
                            types.Part.from_text(text=prompt)
                        ]
                    )
                ],
                config=types.GenerateContentConfig(
                    max_output_tokens=16384,
                    temperature=0.2,
                )
            )

            if response.text:
                result = self._parse_response(response.text)
                return result.get("css", "/* No CSS */")
            return "/* Empty response */"

        except Exception as e:
            logger.error(f"CSS generation for part {part_num} failed: {e}")
            return f"/* Error in part {part_num} */"

    async def _generate_js_from_video(
        self,
        video_path: Optional[str],
        html_content: str,
        css_content: str
    ) -> str:
        """動画からJSを生成"""
        # HTML/CSSを要約（JSはHTML構造とCSS参照のためもう少し長く）
        html_summary = html_content[:8000] if len(html_content) > 8000 else html_content
        css_summary = css_content[:5000] if len(css_content) > 5000 else css_content

        prompt = f"""動画を分析して、以下のHTML/CSSに対応するJavaScriptを生成してください。

## HTML（抜粋）
```html
{html_summary}
```

## CSS（抜粋）
```css
{css_summary}
```

## 要件
- スクロールアニメーション、ホバー効果、ナビゲーション等を実装
- バニラJS（外部ライブラリ不使用）
- JSON形式で出力: {{"js": "..."}}
"""

        if video_path and Path(video_path).exists():
            video_data, video_media_type = self._encode_video_to_base64(video_path)
            if video_data:
                try:
                    video_bytes = base64.b64decode(video_data)

                    response = self.client.models.generate_content(
                        model=self.model,
                        contents=[
                            types.Content(
                                role="user",
                                parts=[
                                    types.Part.from_bytes(data=video_bytes, mime_type=video_media_type),
                                    types.Part.from_text(text=prompt)
                                ]
                            )
                        ],
                        config=types.GenerateContentConfig(
                            max_output_tokens=16384,
                            temperature=0.2,
                        )
                    )

                    if response.text:
                        result = self._parse_response(response.text)
                        return result.get("js", "// No JS")
                except Exception as e:
                    logger.error(f"JS generation from video failed: {e}")

        # 動画がない場合は最小限のJS
        return """// Minimal initialization
document.addEventListener('DOMContentLoaded', function() {
    console.log('Page loaded');
});
"""