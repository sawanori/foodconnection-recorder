"""
画像ベースジェネレーター

スクリーンショット画像からHTML/CSS/JSを生成します。
Anthropic SDKのVision機能を使用します。
"""
import base64
import io
import json
import logging
import re
import os
from pathlib import Path
from typing import Dict, Optional

import anthropic
from PIL import Image

logger = logging.getLogger(__name__)

# システムプロンプト
SYSTEM_PROMPT = """あなたは世界最高峰のWebエンジニア兼UI/UXデザイナーです。
提供されたUIデザイン（画像）を、ブラウザ上で完全に再現可能なHTML/CSS/JSコードに変換することがあなたの使命です。

## 核心的な行動指針
1. **Pixel-Perfectな再現**: レイアウト、余白、サイズ、配色をピクセル単位で正確に再現してください。
2. **モダンで堅牢なコード**: 最新のHTML5、CSS3、ES6+を使用してください。FlexboxやCSS Gridを適切に使い分けてください。
3. **視覚的ディテールの追求**: 影（box-shadow）、角丸（border-radius）、透明度（opacity）、ぼかし（backdrop-filter）、グラデーションなどを詳細に分析し、実装してください。
4. **レスポンシブへの配慮**: 指定がない場合でも、デバイス幅に応じた適切な挙動（画像の伸縮など）を考慮してください。

必ずJSON形式で出力してください。"""

# 生成プロンプトテンプレート
GENERATE_PROMPT_TEMPLATE = """
添付の画像は、実装すべきWebサイトのデザイン（スクリーンショット）です。
このデザインをブラウザ上で**ピクセル単位で完全に再現**するコードを生成してください。

## 詳細な実装要件

### 1. レイアウトと構造
- ビューポート: {viewport_width}x{viewport_height}px
- **Semantic HTML**: `<header>`, `<main>`, `<section>`, `<article>`, `<footer>` などを適切に使用。
- **Modern CSS Layout**: Flexbox (`display: flex`) と CSS Grid (`display: grid`) を駆使して、複雑なレイアウトも正確に再現してください。
- `gap` プロパティを使用して、均一な余白を管理してください。

### 2. デザインの再現（最重要）
- **配色**: 背景色、文字色、ボーダー色を画像から正確に抽出してください（スポイトで取ったかのように正確に）。
- **タイポグラフィ**: フォントサイズ、ウェイト（太さ）、行間（line-height）、文字間（letter-spacing）を微調整し、画像と同じ「質感」を出してください。
- **装飾**:
  - 繊細なボーダー（border: 1px solid rgba(...)）
  - リアルな影（box-shadow）
  - 角丸（border-radius）
  - ガラスモーフィズム（backdrop-filter: blur(...)）やグラデーションがあれば必ず実装してください。

### 3. 画像とアセット
- `<img src="https://picsum.photos/幅/高さ?random=1" ...>` の形式でプレースホルダー画像を使用。
- アスペクト比（object-fit: cover/contain）を正しく設定。
- アイコンが見える場合は、FontAwesome等は使わず、CSSで描画するかSVGプレースホルダーを想定した `<span>` 等で代用し、クラス名で意図を示してください。

### 4. コンテンツ
- 画像内のテキストが読み取れる場合は、**可能な限りそのテキストをそのまま使用**してください。
-読み取れない場合は、文脈に合った自然なダミーテキスト（Lorem Ipsum等）を使用してください。

## 出力ファイル構成
以下の3ファイルを生成します：
1. `index.html`: 完全なHTML構造。`<link rel="stylesheet" href="styles.css">` と `<script src="script.js">` を含める。
2. `styles.css`: 全てのスタイル定義。リセットCSS（`* { box-sizing: border-box; margin: 0; padding: 0; }`）を含めること。
3. `script.js`: ハンバーガーメニュー、スライダー、モーダルなどのインタラクションが必要な場合のみ記述。

## 出力形式（厳守）
JSONフォーマットのみを出力してください。思考過程やMarkdownのコードブロック（```json）は不要です。

{{
  "html": "<!DOCTYPE html>...",
  "css": "/* styles.css */...",
  "js": "// script.js..."
}}
"""

# 修正プロンプトテンプレート
REFINE_PROMPT_TEMPLATE = """
添付のオリジナル画像と、前回生成したコードのレンダリング結果（もしあれば）を比較し、コードを修正してください。

## 検証ステータス
- 現在の類似度: {similarity_score}%
- 目標類似度: 95%以上

## 修正への指針
以下の「差分レポート」と「あなたのプロとしての目」で、違和感のある箇所を徹底的に修正してください。

### 差分レポート
{diff_report}

### 重点チェックポイント
1. **配置のズレ**: 数ピクセルのズレも許容せず、margin/padding/gapを微調整してください。
2. **色の正確性**: 微妙なグレーや透明度、グラデーションの角度なども合わせ込んでください。
3. **フォントの質感**: font-weightやline-heightを見直し、テキストの塊としての見え方を一致させてください。

## 前回生成したコード
### HTML
```html
{previous_html}
```
### CSS
```css
{previous_css}
```

## 出力形式（厳守）
修正後の**完全な**HTML/CSS/JSコードをJSONで出力してください（差分のみは不可）。

{{
  "html": "...",
  "css": "...",
  "js": "..."
}}
"""


class ImageGenerationError(Exception):
    """画像生成エラー"""
    pass


class ImageGenerator:
    """画像ベースジェネレータークラス"""

    def __init__(self, model: str = "claude-opus-4-5-20251101"):
        """
        Args:
            model: 使用するClaudeモデル
        """
        self.model = model
        self.client = anthropic.Anthropic()  # ANTHROPIC_API_KEY環境変数から自動取得

    async def generate_from_image(
        self,
        image_path: str,
        viewport_width: int = 1366,
        viewport_height: int = 768
    ) -> Dict[str, str]:
        """
        スクリーンショット画像からHTML/CSS/JSを生成

        Args:
            image_path: スクリーンショット画像のパス
            viewport_width: ビューポート幅
            viewport_height: ビューポート高さ

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            ImageGenerationError: 生成失敗時
        """
        # 画像ファイルの存在確認
        image_file = Path(image_path)
        if not image_file.exists():
            raise ImageGenerationError(f"Image file not found: {image_path}")

        # 画像をbase64エンコード（5MB制限対応で自動圧縮）
        image_data, media_type = self._encode_image(image_path)

        # プロンプト生成
        prompt = GENERATE_PROMPT_TEMPLATE.format(
            viewport_width=viewport_width,
            viewport_height=viewport_height
        )

        return await self._call_api_with_image(image_data, media_type, prompt)

    async def refine(
        self,
        image_path: str,
        previous_code: Dict[str, str],
        similarity_score: float,
        diff_report: str
    ) -> Dict[str, str]:
        """
        前回のコードを画像と比較して修正

        Args:
            image_path: オリジナル画像パス
            previous_code: 前回生成したコード
            similarity_score: 類似度スコア
            diff_report: 差分レポート

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            ImageGenerationError: 生成失敗時
        """
        # 画像をbase64エンコード（5MB制限対応で自動圧縮）
        image_data, media_type = self._encode_image(image_path)

        prompt = REFINE_PROMPT_TEMPLATE.format(
            similarity_score=similarity_score,
            diff_report=diff_report,
            previous_html=previous_code.get("html", "")[:5000],
            previous_css=previous_code.get("css", "")[:3000],
            previous_js=previous_code.get("js", "")[:2000],
        )

        return await self._call_api_with_image(image_data, media_type, prompt)

    def _encode_image(self, image_path: str, max_size_bytes: int = 4 * 1024 * 1024) -> tuple[str, str]:
        """
        画像をbase64エンコード（5MB制限対応、フルページはビューポートにクロップ）

        Args:
            image_path: 画像ファイルパス
            max_size_bytes: 最大サイズ（デフォルト4MB、余裕を持たせる）

        Returns:
            (base64エンコードされた画像データ, メディアタイプ)
        """
        # 画像を開いてサイズを確認
        img = Image.open(image_path)
        logger.info(f"Original image size: {img.size}")

        # フルページスクリーンショット（高さが幅の3倍以上）の場合、上部のみをクロップ
        # これにより、詳細を保持しつつAPIサイズ制限に収まる
        if img.height > img.width * 3:
            # ビューポート高さ（約2スクリーン分）をクロップ
            crop_height = min(img.height, img.width * 2)  # 幅の2倍まで
            img = img.crop((0, 0, img.width, crop_height))
            logger.info(f"Cropped to viewport: {img.size}")

        # RGBに変換
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # 高品質PNGとしてエンコードを試みる
        buffer = io.BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        data = buffer.getvalue()

        if len(data) <= max_size_bytes:
            logger.info(f"PNG size: {len(data) / 1024 / 1024:.2f}MB (within limit)")
            return base64.standard_b64encode(data).decode("utf-8"), "image/png"

        # PNGが大きすぎる場合、高品質JPEGで試す
        logger.info(f"PNG too large ({len(data) / 1024 / 1024:.2f}MB), trying JPEG...")
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=95, optimize=True)
        data = buffer.getvalue()

        if len(data) <= max_size_bytes:
            logger.info(f"JPEG size: {len(data) / 1024 / 1024:.2f}MB (within limit)")
            return base64.standard_b64encode(data).decode("utf-8"), "image/jpeg"

        # まだ大きい場合は段階的に品質を下げる
        logger.info(f"JPEG still too large ({len(data) / 1024 / 1024:.2f}MB), compressing...")
        return self._compress_and_encode_pil(img, max_size_bytes), "image/jpeg"

    def _compress_and_encode_pil(self, img: Image.Image, max_size_bytes: int) -> str:
        """PIL Imageオブジェクトを圧縮してbase64エンコード"""
        quality = 90
        scale = 1.0

        while True:
            if scale < 1.0:
                new_width = int(img.width * scale)
                new_height = int(img.height * scale)
                resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            else:
                resized = img

            buffer = io.BytesIO()
            resized.save(buffer, format='JPEG', quality=quality, optimize=True)
            data = buffer.getvalue()

            if len(data) <= max_size_bytes:
                logger.info(f"Compressed to {len(data) / 1024 / 1024:.2f}MB (scale={scale:.2f}, quality={quality})")
                return base64.standard_b64encode(data).decode("utf-8")

            if quality > 60:
                quality -= 5
            elif scale > 0.5:
                scale -= 0.1
                quality = 90
            else:
                scale -= 0.1
                if scale < 0.3:
                    logger.warning(f"Could not compress below {len(data) / 1024 / 1024:.2f}MB")
                    return base64.standard_b64encode(data).decode("utf-8")

    def _get_media_type(self, image_path: str) -> str:
        """画像のメディアタイプを取得"""
        ext = Path(image_path).suffix.lower()
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return media_types.get(ext, "image/png")

    async def _call_api_with_image(
        self,
        image_data: str,
        media_type: str,
        prompt: str
    ) -> Dict[str, str]:
        """
        画像付きでAnthropic APIを呼び出し

        Args:
            image_data: base64エンコードされた画像
            media_type: 画像のメディアタイプ
            prompt: プロンプト

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            ImageGenerationError: 呼び出し失敗時
        """
        logger.info(f"Calling Anthropic API with image...")

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=16384,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            }
                        ],
                    }
                ],
            )

        except anthropic.APIConnectionError as e:
            raise ImageGenerationError(f"API connection error: {e}")
        except anthropic.RateLimitError as e:
            raise ImageGenerationError(f"Rate limit exceeded: {e}")
        except anthropic.APIStatusError as e:
            raise ImageGenerationError(f"API error: {e}")
        except Exception as e:
            raise ImageGenerationError(f"Unexpected error: {e}")

        # レスポンスからテキストを取得
        if not message.content or len(message.content) == 0:
            raise ImageGenerationError("Empty response from API")

        # トークン制限で途切れた場合の警告
        if message.stop_reason == "max_tokens":
            logger.warning("Response was truncated due to max_tokens limit")

        result_text = message.content[0].text
        logger.info(f"API response received (stop_reason={message.stop_reason}, length={len(result_text)})")

        return self._parse_response(result_text)

    def _parse_response(self, result_text: str) -> Dict[str, str]:
        """
        APIレスポンスをパース

        Args:
            result_text: APIからのテキストレスポンス

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            ImageGenerationError: パース失敗時
        """
        generated = self._extract_json_from_result(result_text)

        # 必須フィールド検証
        required_fields = ["html", "css", "js"]
        for field in required_fields:
            if field not in generated:
                generated[field] = "" if field == "js" else f"/* {field} not generated */"
                logger.warning(f"Missing required field '{field}' in response, using default")

        logger.info("Response parsed successfully")
        return generated

    def _extract_json_from_result(self, result_text: str) -> Dict[str, str]:
        """
        result テキストからJSONを抽出

        Args:
            result_text: APIからのテキスト

        Returns:
            抽出されたJSON辞書

        Raises:
            ImageGenerationError: 抽出失敗時
        """
        # 方法1: ```json ... ``` ブロックから抽出
        code_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', result_text)
        if code_block_match:
            json_str = code_block_match.group(1)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 方法2: ``` ... ``` ブロックから抽出
        code_block_match = re.search(r'```\s*([\s\S]*?)\s*```', result_text)
        if code_block_match:
            json_str = code_block_match.group(1)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 方法3: ```json で始まるが閉じられていない場合（トークン制限で途切れた場合）
        if '```json' in result_text:
            json_start = result_text.find('```json') + 7
            json_str = result_text[json_start:].strip()
            # 途切れたJSONを修復して試行
            repaired = self._repair_truncated_json(json_str)
            if repaired:
                return repaired

        # 方法4: { で始まり } で終わる部分を抽出
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            json_str = json_match.group(0)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 方法5: { で始まる部分から修復を試みる
        if '{' in result_text:
            json_start = result_text.find('{')
            json_str = result_text[json_start:]
            repaired = self._repair_truncated_json(json_str)
            if repaired:
                return repaired

        # 方法6: 全体をJSONとして試行
        try:
            return json.loads(result_text)
        except json.JSONDecodeError:
            pass

        raise ImageGenerationError(
            f"Could not extract JSON from response.\n"
            f"Response preview: {result_text[:500]}..."
        )

    def _repair_truncated_json(self, json_str: str) -> Optional[Dict[str, str]]:
        """
        途切れたJSONの修復を試みる

        Args:
            json_str: 途切れた可能性のあるJSON文字列

        Returns:
            修復されたJSON辞書、または修復失敗時None
        """
        # まずそのまま試行
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # html, css, js のキーを探して個別に抽出
        result = {}

        for key in ["html", "css", "js"]:
            # "key": "..." パターンを検索
            pattern = rf'"{key}"\s*:\s*"'
            match = re.search(pattern, json_str)
            if match:
                start = match.end()
                # 次のキーまたは文字列終端を探す
                value = self._extract_json_string_value(json_str, start)
                if value is not None:
                    result[key] = value

        if result:
            logger.info(f"Repaired truncated JSON, extracted keys: {list(result.keys())}")
            return result

        return None

    def _extract_json_string_value(self, text: str, start: int) -> Optional[str]:
        """
        JSON文字列値を抽出（エスケープ処理対応）

        Args:
            text: テキスト
            start: 開始位置（開始クォートの次）

        Returns:
            抽出された文字列値
        """
        result = []
        i = start
        while i < len(text):
            char = text[i]
            if char == '\\' and i + 1 < len(text):
                # エスケープシーケンス
                next_char = text[i + 1]
                if next_char == 'n':
                    result.append('\n')
                elif next_char == 't':
                    result.append('\t')
                elif next_char == 'r':
                    result.append('\r')
                elif next_char == '"':
                    result.append('"')
                elif next_char == '\\':
                    result.append('\\')
                else:
                    result.append(next_char)
                i += 2
            elif char == '"':
                # 文字列終端
                return ''.join(result)
            else:
                result.append(char)
                i += 1

        # 終端がない場合（途切れた場合）は現在までの値を返す
        if result:
            return ''.join(result)
        return None
