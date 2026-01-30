"""
Claude画像ベースジェネレーター

Anthropic SDKのVision機能を使用してスクリーンショット画像からHTML/CSS/JSを生成します。
動画入力にも対応しています。
"""
import base64
import logging
from pathlib import Path
from typing import Dict, Optional

import anthropic

from .base_image_generator import (
    BaseImageGenerator,
    ImageGenerationError,
    SYSTEM_PROMPT,
    GENERATE_PROMPT_TEMPLATE,
    SEMANTIC_RECONSTRUCTION_PROMPT_TEMPLATE,
    HTML_CLEANUP_PROMPT,
    CSS_FROM_SCREENSHOT_PROMPT,
    JS_FROM_VIDEO_PROMPT,
)
from app.config import settings

logger = logging.getLogger(__name__)


class ClaudeImageGenerator(BaseImageGenerator):
    """Claude（Anthropic）を使用した画像ベースジェネレーター"""

    def __init__(self, model: str = "claude-opus-4-5-20251101", timeout: int = 900):
        """
        Args:
            model: 使用するClaudeモデル
            timeout: APIタイムアウト（秒、デフォルト900=15分）
        """
        import httpx
        self.model = model
        self.timeout = timeout

        # APIキーを明示的に設定
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set in environment or config")

        self.client = anthropic.Anthropic(
            api_key=api_key,
            timeout=httpx.Timeout(timeout, read=timeout, write=10.0, connect=5.0)
        )

    def get_model_name(self) -> str:
        """使用しているモデル名を返す"""
        return f"Claude ({self.model})"

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
            design_tokens: デザイン要素タプル (colors, fonts)

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
            logger.info(f"Using design tokens - Colors: {len(design_tokens.get('colors', []))}, Fonts: {len(design_tokens.get('fonts', []))}")
        else:
            design_colors = "（画像から推測してください）"
            design_fonts = "（画像から推測してください）"

        # プロンプト生成（HTMLコンテキストを埋め込み）
        try:
            prompt = GENERATE_PROMPT_TEMPLATE.format(
                viewport_width=viewport_width,
                viewport_height=viewport_height,
                html_context=html_context,
                design_colors=design_colors,
                design_fonts=design_fonts
            )
        except KeyError as e:
            # テンプレート側のプレースホルダと合わない場合のフォールバック
            logger.warning(f"Failed to format prompt with context: {e}. Falling back to legacy prompt.")
            prompt = f"""
            Generate HTML/CSS/JS from this image.
            Viewport: {viewport_width}x{viewport_height}
            HTML Reference: {html_context[:1000]}...
            """

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

        # 画像がある場合は画像付きで呼び出し
        if image_path:
            img, _ = self._prepare_image(image_path)
            image_data, media_type = self._encode_image_to_base64(img)
            return await self._call_api_with_image(image_data, media_type, prompt)
        else:
            # 画像なしでテキストのみで呼び出し
            return await self._call_api_text_only(prompt)

    async def _call_api_text_only(self, prompt: str) -> Dict[str, str]:
        """テキストのみでAPIを呼び出し"""
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=20000,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                system=SYSTEM_PROMPT
            )

            response_text = response.content[0].text
            return self._parse_response(response_text)

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise ImageGenerationError(f"Claude API error: {e}")

    async def _call_api_with_image(
        self,
        image_data: str,
        media_type: str,
        prompt: str,
        use_system_prompt: bool = True
    ) -> Dict[str, str]:
        """画像付きでAPIを呼び出し"""
        try:
            kwargs = {
                "model": self.model,
                "max_tokens": 20000,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data
                                }
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ]
                    }
                ]
            }
            if use_system_prompt:
                kwargs["system"] = SYSTEM_PROMPT

            response = self.client.messages.create(**kwargs)

            response_text = response.content[0].text
            return self._parse_response(response_text)

        except anthropic.APIError as e:
            logger.error(f"Claude API error: {e}")
            raise ImageGenerationError(f"Claude API error: {e}")

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

            # ファイルサイズチェック（Claudeの制限は約25MB）
            file_size = video_file.stat().st_size
            max_size = 25 * 1024 * 1024  # 25MB
            if file_size > max_size:
                logger.warning(f"Video file too large ({file_size / 1024 / 1024:.1f}MB > 25MB), skipping video input")
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
        prompt: str,
        use_system_prompt: bool = True
    ) -> Dict[str, str]:
        """画像と動画付きでAPIを呼び出し"""
        logger.info("Calling Claude API with image and video...")

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
            kwargs = {
                "model": self.model,
                "max_tokens": 20000,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video",
                                "source": {
                                    "type": "base64",
                                    "media_type": video_media_type,
                                    "data": video_data
                                }
                            },
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": image_media_type,
                                    "data": image_data
                                }
                            },
                            {
                                "type": "text",
                                "text": full_prompt
                            }
                        ]
                    }
                ]
            }
            if use_system_prompt:
                kwargs["system"] = SYSTEM_PROMPT

            response = self.client.messages.create(**kwargs)

            response_text = response.content[0].text
            return self._parse_response(response_text)

        except anthropic.APIError as e:
            logger.error(f"Claude API error with video: {e}")
            # 動画付きで失敗した場合、画像のみで再試行
            logger.info("Retrying with image only...")
            return await self._call_api_with_image(image_data, image_media_type, prompt, use_system_prompt)

    # ========================================
    # 3段階生成メソッド（HTML → CSS → JS）
    # ========================================

    async def generate_three_step(
        self,
        image_path: str,
        html_content: str,
        video_path: Optional[str] = None,
        design_tokens: Optional[Dict] = None
    ) -> Dict[str, str]:
        """
        3段階生成: HTML → CSS → JS (旧バージョン)
        """
        return await self.generate_three_step_v2(image_path, html_content, video_path, design_tokens)

    async def generate_three_step_v2(
        self,
        image_path: str,
        html_content: str,
        video_path: Optional[str] = None,
        design_tokens: Optional[Dict] = None
    ) -> Dict[str, str]:
        """
        3段階生成 v2: HTML → CSS → JS（分割なし、シンプル版）

        HTMLを分割せず、各ステップで1種類のみ生成してトークン制限を回避。

        Args:
            image_path: スクリーンショット画像パス
            html_content: 元のHTMLソース
            video_path: 録画動画パス（オプション）
            design_tokens: デザイン要素

        Returns:
            {"html": "...", "css": "...", "js": "..."}
        """
        logger.info("Starting 3-step v2 generation (simple, no splitting)")

        # Step 1: HTMLクリーンアップ（ローカル処理）
        logger.info("Step 1: Cleaning up HTML (local processing)...")
        clean_html = self._step1_cleanup_html(html_content)
        logger.info(f"Step 1 complete: HTML length = {len(clean_html)}")

        # Step 2: スクリーンショットからCSS生成（HTML全体を参照）
        logger.info("Step 2: Generating CSS from screenshot...")
        css = await self._step2_generate_css_v2(image_path, clean_html, design_tokens)
        logger.info(f"Step 2 complete: CSS length = {len(css)}")

        # Step 3: 動画からJS生成
        logger.info("Step 3: Generating JS from video...")
        js = await self._step3_generate_js_v2(video_path, clean_html, css)
        logger.info(f"Step 3 complete: JS length = {len(js)}")

        return {
            "html": clean_html,
            "css": css,
            "js": js
        }

    def _split_html_into_parts(self, html_content: str, num_parts: int = 3) -> list:
        """HTMLを指定数のパートに分割"""
        import re

        # bodyタグの中身を抽出
        body_match = re.search(r'<body[^>]*>(.*?)</body>', html_content, re.DOTALL | re.IGNORECASE)
        if not body_match:
            # bodyがない場合はそのまま分割
            total_len = len(html_content)
            part_size = total_len // num_parts
            parts = []
            for i in range(num_parts):
                start = i * part_size
                end = (i + 1) * part_size if i < num_parts - 1 else total_len
                parts.append(html_content[start:end])
            return parts

        body_content = body_match.group(1)
        head_match = re.search(r'<head[^>]*>.*?</head>', html_content, re.DOTALL | re.IGNORECASE)
        head_content = head_match.group(0) if head_match else ""

        # 主要なセクションタグで分割を試みる
        section_tags = ['section', 'article', 'main', 'header', 'footer', 'nav', 'div']
        sections = []

        for tag in section_tags:
            pattern = rf'<{tag}[^>]*>.*?</{tag}>'
            found_sections = re.findall(pattern, body_content, re.DOTALL | re.IGNORECASE)
            if len(found_sections) >= num_parts:
                sections = found_sections
                break

        if len(sections) >= num_parts:
            # セクションをグループ化
            sections_per_part = len(sections) // num_parts
            parts = []
            for i in range(num_parts):
                start_idx = i * sections_per_part
                end_idx = (i + 1) * sections_per_part if i < num_parts - 1 else len(sections)
                part_sections = sections[start_idx:end_idx]
                part_html = f"<!DOCTYPE html><html><head>{head_content}</head><body>{''.join(part_sections)}</body></html>"
                parts.append(part_html)
            return parts
        else:
            # セクションが見つからない場合は文字数で分割
            total_len = len(body_content)
            part_size = total_len // num_parts
            parts = []
            for i in range(num_parts):
                start = i * part_size
                end = (i + 1) * part_size if i < num_parts - 1 else total_len
                part_body = body_content[start:end]
                part_html = f"<!DOCTYPE html><html>{head_content}<body>{part_body}</body></html>"
                parts.append(part_html)
            return parts

    def _combine_css_parts(self, css_parts: list) -> str:
        """複数のCSSパートを結合（重複除去）"""
        import re

        combined = "/* Combined CSS from multiple parts */\n\n"
        seen_selectors = set()

        for i, css in enumerate(css_parts):
            combined += f"/* === Part {i+1} === */\n"

            # CSSルールを抽出
            rules = re.findall(r'([^{]+)\{([^}]+)\}', css)
            for selector, properties in rules:
                selector = selector.strip()
                if selector and selector not in seen_selectors:
                    seen_selectors.add(selector)
                    combined += f"{selector} {{\n{properties}\n}}\n\n"

        return combined

    def _step1_cleanup_html(self, html_content: str) -> str:
        """Step 1: HTMLクリーンアップ（ローカル処理、AIは使わない）

        インラインスタイル、スクリプト、不要な属性を削除して
        外部CSS/JSで制御できる状態にする。
        """
        import re

        html = html_content

        # <style>タグを削除（外部CSSで置き換えるため）
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # <script>タグを削除（外部JSで置き換えるため）
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)

        # style属性を削除
        html = re.sub(r'\s+style\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)

        # onclick等のイベントハンドラを削除
        html = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', html, flags=re.IGNORECASE)

        # 外部CSS/JSリンクを追加（headの終わりに）
        if '</head>' in html.lower():
            css_link = '<link rel="stylesheet" href="styles.css">'
            js_link = '<script src="script.js" defer></script>'
            html = re.sub(
                r'(</head>)',
                f'{css_link}\n{js_link}\n\\1',
                html,
                flags=re.IGNORECASE
            )

        logger.info(f"HTML cleaned: {len(html_content)} -> {len(html)} chars")
        return html

    def _extract_html_summary(self, html_content: str, max_chars: int = 8000) -> str:
        """HTMLを要約して重要な部分だけ抽出

        注意: 出力は.format()で使用されるため、中括弧をエスケープする
        """
        import re

        # クラス名とID名を抽出
        classes = set(re.findall(r'class=["\']([^"\']+)["\']', html_content))
        ids = set(re.findall(r'id=["\']([^"\']+)["\']', html_content))

        # HTMLが短ければそのまま返す
        if len(html_content) <= max_chars:
            # 中括弧をエスケープ（.format()対策）
            return html_content.replace('{', '{{').replace('}', '}}')

        # 長い場合は先頭と末尾を結合
        head_part = html_content[:max_chars // 2]
        tail_part = html_content[-(max_chars // 2):]

        summary = f"{head_part}\n\n<!-- ... 省略 ({len(html_content)} chars total) ... -->\n\n{tail_part}"
        summary += f"\n\n<!-- 使用クラス: {', '.join(list(classes)[:50])} -->"
        summary += f"\n<!-- 使用ID: {', '.join(list(ids)[:30])} -->"

        # 中括弧をエスケープ（.format()対策）
        return summary.replace('{', '{{').replace('}', '}}')

    async def _step2_generate_css(
        self,
        image_path: str,
        html_content: str,
        design_tokens: Optional[Dict] = None
    ) -> str:
        """Step 2: スクリーンショットからCSS生成"""
        # 画像を準備
        img, _ = self._prepare_image(image_path)
        image_data, media_type = self._encode_image_to_base64(img)

        # デザイン要素
        if design_tokens:
            design_colors = ", ".join(design_tokens.get("colors", []))
            design_fonts = ", ".join(design_tokens.get("fonts", []))
        else:
            design_colors = "（画像から推測してください）"
            design_fonts = "（画像から推測してください）"

        # HTMLを要約（トークン制限対策）
        html_summary = self._extract_html_summary(html_content)
        logger.info(f"HTML summary for CSS: {len(html_content)} -> {len(html_summary)} chars")

        prompt = CSS_FROM_SCREENSHOT_PROMPT.format(
            html_content=html_summary,
            design_colors=design_colors,
            design_fonts=design_fonts
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=20000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data
                                }
                            },
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                system="あなたはCSSの専門家です。スクリーンショットを見て正確なCSSを生成します。"
            )
            result = self._parse_response(response.content[0].text)
            return result.get("css", "/* No CSS generated */")
        except Exception as e:
            logger.error(f"Step 2 failed: {e}")
            return "/* CSS generation failed */"

    async def _step3_generate_js(
        self,
        video_path: Optional[str],
        html_content: str,
        css_content: str
    ) -> str:
        """Step 3: 動画からJS生成"""
        # HTMLとCSSを要約（トークン制限対策）
        html_summary = self._extract_html_summary(html_content, max_chars=4000)
        css_summary = css_content[:4000] if len(css_content) > 4000 else css_content
        # CSSも中括弧をエスケープ（.format()対策）
        css_summary = css_summary.replace('{', '{{').replace('}', '}}')

        logger.info(f"HTML summary for JS: {len(html_content)} -> {len(html_summary)} chars")
        logger.info(f"CSS summary for JS: {len(css_content)} -> {len(css_summary)} chars")

        prompt = JS_FROM_VIDEO_PROMPT.format(
            html_content=html_summary,
            css_content=css_summary
        )

        # 動画がある場合
        if video_path and Path(video_path).exists():
            video_data, video_media_type = self._encode_video_to_base64(video_path)
            if video_data:
                try:
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=16000,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "video",
                                        "source": {
                                            "type": "base64",
                                            "media_type": video_media_type,
                                            "data": video_data
                                        }
                                    },
                                    {"type": "text", "text": prompt}
                                ]
                            }
                        ],
                        system="あなたはJavaScriptの専門家です。動画を分析してアニメーションやインタラクションを実装します。"
                    )
                    result = self._parse_response(response.content[0].text)
                    return result.get("js", "// No JS generated")
                except Exception as e:
                    logger.error(f"Step 3 with video failed: {e}")

        # 動画がない場合は最小限のJSを返す
        logger.info("No video available, returning minimal JS")
        return self._generate_minimal_js()

    def _generate_minimal_js(self) -> str:
        """最小限のJSを返す"""
        return """// Minimal initialization
document.addEventListener('DOMContentLoaded', function() {
    console.log('Page loaded');
});
"""

    # ========================================
    # v2メソッド（.format()を使わない）
    # ========================================

    async def _step2_generate_css_v2(
        self,
        image_path: str,
        html_content: str,
        design_tokens: Optional[Dict] = None
    ) -> str:
        """Step 2 v2: スクリーンショットからCSS生成（.format()不使用）"""
        # 画像を準備
        img, _ = self._prepare_image(image_path)
        image_data, media_type = self._encode_image_to_base64(img)

        # デザイン要素
        if design_tokens:
            design_colors = ", ".join(design_tokens.get("colors", []))
            design_fonts = ", ".join(design_tokens.get("fonts", []))
        else:
            design_colors = "（画像から推測してください）"
            design_fonts = "（画像から推測してください）"

        # HTMLを要約（長すぎる場合）
        if len(html_content) > 8000:
            html_summary = html_content[:4000] + "\n\n<!-- ... 省略 ... -->\n\n" + html_content[-4000:]
        else:
            html_summary = html_content

        # プロンプトを直接構築（.format()不使用）
        prompt = f"""添付のスクリーンショット画像を参照して、以下のHTMLに対応するCSSを生成してください。

## 参照HTML
```html
{html_summary}
```

## デザイン要素
- 抽出された色: {design_colors}
- 抽出されたフォント: {design_fonts}

## CSS生成要件
1. スクリーンショットの見た目を忠実に再現
2. 色は正確なHEX値またはRGB値を使用
3. フォントファミリー、サイズ、太さ、行間を正確に
4. Flexbox/CSS Gridで正確な配置
5. margin/paddingを正確に
6. 背景色、グラデーション、パターンを再現
7. ボーダー、角丸を正確に
8. メディアクエリで768px以下のスマホ対応

## 出力形式
CSSのみをJSON形式で出力してください。

```json
{{"css": "/* styles.css */..."}}
```"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=20000,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data
                                }
                            },
                            {"type": "text", "text": prompt}
                        ]
                    }
                ],
                system="あなたはCSSの専門家です。スクリーンショットを見て正確なCSSを生成します。CSSのみを出力してください。"
            )
            result = self._parse_response(response.content[0].text)
            return result.get("css", "/* No CSS generated */")
        except Exception as e:
            logger.error(f"Step 2 v2 failed: {e}")
            return "/* CSS generation failed */"

    async def _step3_generate_js_v2(
        self,
        video_path: Optional[str],
        html_content: str,
        css_content: str
    ) -> str:
        """Step 3 v2: 動画からJS生成（.format()不使用）"""
        # HTMLとCSSを要約
        if len(html_content) > 4000:
            html_summary = html_content[:2000] + "\n<!-- ... 省略 ... -->\n" + html_content[-2000:]
        else:
            html_summary = html_content

        if len(css_content) > 4000:
            css_summary = css_content[:2000] + "\n/* ... 省略 ... */\n" + css_content[-2000:]
        else:
            css_summary = css_content

        # プロンプトを直接構築
        prompt = f"""添付の動画は、Webページをスクロールしながら録画したものです。
動画を分析して、以下のHTMLに対応するJavaScriptを生成してください。

## 参照HTML
```html
{html_summary}
```

## 参照CSS
```css
{css_summary}
```

## 動画から抽出すべき情報
1. スクロールアニメーション（フェードイン、スライドイン等）
2. ホバーエフェクト
3. ナビゲーション（ハンバーガーメニュー、スムーススクロール）
4. スライダー/カルーセル
5. モーダル/ポップアップ
6. その他インタラクション

## JS生成要件
1. バニラJS（外部ライブラリ不使用）
2. DOMContentLoadedで初期化
3. IntersectionObserverを適切に使用
4. キーボード操作も考慮

## 出力形式
JavaScriptのみをJSON形式で出力してください。

```json
{{"js": "// script.js..."}}
```"""

        # 動画がある場合
        if video_path and Path(video_path).exists():
            video_data, video_media_type = self._encode_video_to_base64(video_path)
            if video_data:
                try:
                    response = self.client.messages.create(
                        model=self.model,
                        max_tokens=16000,
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "video",
                                        "source": {
                                            "type": "base64",
                                            "media_type": video_media_type,
                                            "data": video_data
                                        }
                                    },
                                    {"type": "text", "text": prompt}
                                ]
                            }
                        ],
                        system="あなたはJavaScriptの専門家です。動画を分析してアニメーションやインタラクションを実装します。JSのみを出力してください。"
                    )
                    result = self._parse_response(response.content[0].text)
                    return result.get("js", "// No JS generated")
                except Exception as e:
                    logger.error(f"Step 3 v2 with video failed: {e}")

        # 動画がない場合は最小限のJSを返す
        logger.info("No video available, returning minimal JS")
        return self._generate_minimal_js()
