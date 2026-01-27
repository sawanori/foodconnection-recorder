"""
画像ベースジェネレーターの基底クラス

異なるAIモデル（Claude, Gemini等）で共通のインターフェースを提供します。
"""
import base64
import io
import json
import logging
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Optional

from PIL import Image

logger = logging.getLogger(__name__)

# システムプロンプト（共通）
SYSTEM_PROMPT = """あなたはピクセルパーフェクトなWebデザインの専門家です。
スクリーンショット画像を精密に分析し、見た目が完全に一致するHTML/CSS/JSコードを生成します。

重要な注意点:
- 色は正確なHEX値またはRGB値を使用
- フォントサイズ、行間、余白はピクセル単位で正確に
- レイアウトはFlexboxまたはGridで正確に再現
- 要素の配置、サイズ、間隔を画像と完全一致させる

必ずJSON形式で出力してください。"""

# 生成プロンプトテンプレート（共通）
# 生成プロンプトテンプレート（共通）
GENERATE_PROMPT_TEMPLATE = """
添付の画像はWebページのスクリーンショットです。
この見た目を再現し、レスポンシブ対応のHTML/CSS/JSコードを生成してください。

## 提供されたリソース
1. **スクリーンショット画像**: 最終的な見た目の正解です。
2. **デザイン要素（抽出済み）**:
   - 色: {design_colors}
   - フォント: {design_fonts}
   **重要**: これらの色やフォントを優先的に使用してください。
3. **HTMLソースコード（抜粋）**:
   ```html
   {html_context}
   ```
   **重要**: テキスト、リンクURL、クラス名、ID構造は、このHTMLソースを「正解」として使用してください。
   ただし、スタイル（色、余白、配置）は画像（視覚情報）を優先してください。

## 精密な再現のための要件

### レイアウト（レスポンシブ対応必須）
- デスクトップ基準: {viewport_width}px幅で画像と同じ見た目を再現
- **Box Model**: 全要素に `box-sizing: border-box;` を適用してください。
- **Flexible Layouts**: FlexboxまたはCSS Gridを使用し、`gap` プロパティを活用して要素間の余白を制御してください（margin相殺の問題を避けるため）。
- ヘッダー、ナビゲーション、コンテンツエリア、フッターの構造を維持。

### レスポンシブデザイン（必須）
- meta viewport: <meta name="viewport" content="width=device-width, initial-scale=1">
- max-width と width: 100% を活用してコンテナを可変に。固定幅（width: 1200px等）は避けるか、max-widthと併用してください。
- メディアクエリを使用:
  - @media (max-width: 1024px) - タブレット用調整
  - @media (max-width: 768px) - スマートフォン用調整
- モバイルでは:
  - ナビゲーションはハンバーガーメニューまたは縦並びに
  - 横並びの要素は縦並びに変更
  - フォントサイズを適切に調整
  - 余白・パディングを縮小

### 色とスタイル
- 背景色、テキスト色、ボーダー色は「デザイン要素」または画像から正確に抽出
- グラデーションや影があれば再現
- ボタンやリンクのホバー効果も推測して実装

### タイポグラフィ
- フォントファミリー: 提供された「デザイン要素」のフォントを優先。日本語サイトならNoto Sans JP、游ゴシック等をフォールバックとして設定。
- フォントサイズ、太さ、行間、文字間隔を正確に
- テキストの配置（左揃え、中央揃え等）
- モバイルではclamp()やvwを使用して可変フォントサイズにしない方が無難です（読みやすさ優先でrem/px調整推奨）。

### 画像
- すべての画像は https://picsum.photos/幅/高さ を使用
- 異なる画像には https://picsum.photos/幅/高さ?random=番号 を使用
- 画像にはmax-width: 100%; height: auto; を設定してアスペクト比を維持

## 出力ファイル
1. index.html - 完全なHTML
2. styles.css - すべてのスタイル
3. script.js - インタラクション（必要な場合のみ）

## ファイル参照（厳守）
HTMLでは以下の形式でCSS/JSを参照してください（./ は付けない）:
- CSSリンク: <link rel="stylesheet" href="styles.css">
- JSスクリプト: <script src="script.js"></script>

## 出力形式（厳守）
以下のJSON形式で出力してください。他のテキストは含めないでください。

```json
{{
  "html": "<!DOCTYPE html>...(完全なHTML、CSSは<head>内でstyles.cssを参照、JSは</body>直前でscript.jsを参照)",
  "css": "/* styles.css の内容 */...",
  "js": "// script.js の内容（必要に応じて）..."
}}
```
"""

# 修正指示プロンプト
FIX_CODE_PROMPT_TEMPLATE = """
現在、生成されたWebサイトの検証を行っています。
検証の結果、以下の問題点が見つかりました。

## 検証レポート（差分）
{diff_report}

## 現在のコード status
HTML, CSS, JSは既に生成済みですが、上記の指摘事項を修正する必要があります。

## 修正の指示
1. 検証レポートで指摘された視覚的な差異（色、サイズ、配置、余白など）を修正してください。
2. 指摘されていない部分は変更しないでください。
3. コード全体を再出力してください。

## 出力形式（厳守）
以下のJSON形式で出力してください。

```json
{{
  "html": "...",
  "css": "...",
  "js": "..."
}}
```
"""

# CSS/JS専用生成プロンプト（HTMLソースがある場合用）
# セマンティック再構築プロンプト（HTMLソースを参考にするが、構造は作り直す）
SEMANTIC_RECONSTRUCTION_PROMPT_TEMPLATE = """
添付の画像はWebページのスクリーンショットです。
**提供されたHTMLソースコードからテキストとリンク情報を抽出し、スクリーンショットの見た目をピクセルパーフェクトに再現する新しいHTML/CSS/JSを生成してください。**

## アプローチ: 「コンテンツはコピー、構造は再構築」
1. **テキスト・リンク**: 提供されたHTMLソースコードから正確なテキスト、リンク先URL (`href`)、画像URL (`src`) をコピーして使用してください。
2. **構造 (HTML)**: 提供されたHTMLのDOM構造に縛られないでください。デザインを再現するために最適でクリーンな、セマンティックなHTML構造（`<header>`, `<main>`, `<section>`, `<footer>`等）を**新しく設計**してください。
3. **スタイル (CSS)**: 画像の見た目（レイアウト、色、余白、フォント）を優先し、それを実現するためのCSSをゼロから作成してください。元のクラス名を使おうとせず、分かりやすいクラス名（例: `.hero-section`, `.nav-link`）を新しく付けてください。

## 提供されたリソース
1. **スクリーンショット画像**: 最終的な見た目の正解です。
2. **デザイン要素（抽出済み）**:
   - 色: {design_colors}
   - フォント: {design_fonts}
3. **HTMLソースコード（コンテンツ参照用）**:
```html
{html_content}
```
**重要**: このHTMLから「テキスト」と「リンクURL」を正確に抽出してください。ただし、クラス名やdivのネスト構造は**無視**して、よりきれいな構造に書き換えて構いません。

## 生成要件

### コード品質
- **HTML**: セマンティックで読みやすい構造。不要なdivネストを排除。
- **CSS**: Scopedなクラス命名を推奨。Flexbox/Gridを適切に使用。
- **レスポンシブ**: モバイル（SP）とデスクトップ（PC）の両方で崩れないように。

### 再現の優先順位
1. **見た目の再現性** (画像と一致しているか)
2. **テキストの正確性** (HTMLソースと一致しているか)
3. **リンクの機能性** (hrefが正しいか)

## 出力ファイル
1. index.html - 再構築されたHTML
2. styles.css - 新しいCSS
3. script.js - 新しいJavaScript

## 出力形式（厳守）
以下のJSON形式で出力してください。

```json
{{
  "html": "<!DOCTYPE html>...(完全なHTML)",
  "css": "/* styles.css */...",
  "js": "// script.js..."
}}
```
"""


# ========================================
# 3段階生成プロンプト（HTML → CSS → JS）
# ========================================

# Step 1: HTMLクリーンアップ（元のHTMLを整形）
HTML_CLEANUP_PROMPT = """
以下のHTMLソースコードをクリーンアップしてください。

## 要件
1. **構造の整理**: 不要なdivのネスト、空要素、コメントを削除
2. **セマンティック化**: 適切なHTML5タグ（header, main, section, footer, nav, article等）に置き換え
3. **コンテンツ保持**: テキスト、リンクURL（href）、画像URL（src）は**絶対に変更しない**
4. **クラス名整理**: 分かりやすいクラス名に置き換え（例: `.hero-section`, `.nav-menu`）
5. **CSS/JSリンク**: 外部ファイル参照に変更
   - <link rel="stylesheet" href="styles.css">
   - <script src="script.js"></script>

## 元のHTMLソース
```html
{html_content}
```

## 出力形式
クリーンアップされたHTMLのみをJSON形式で出力してください。

```json
{{
  "html": "<!DOCTYPE html>..."
}}
```
"""

# Step 2: スクリーンショットからCSS生成
CSS_FROM_SCREENSHOT_PROMPT = """
添付のスクリーンショット画像を参照して、以下のHTMLに対応するCSSを生成してください。

## 参照HTML
```html
{html_content}
```

## デザイン要素
- 抽出された色: {design_colors}
- 抽出されたフォント: {design_fonts}

## CSS生成要件
1. **視覚的再現**: スクリーンショットの見た目を忠実に再現
2. **色**: 正確なHEX値またはRGB値を使用（デザイン要素を参考に）
3. **フォント**: フォントファミリー、サイズ、太さ、行間を正確に
4. **レイアウト**: Flexbox/CSS Gridを使用して正確な配置
5. **余白**: margin/paddingを正確に（box-sizing: border-box推奨）
6. **背景**: 背景色、グラデーション、パターンを再現
7. **ボーダー**: 枠線、角丸を正確に
8. **レスポンシブ**: メディアクエリで768px以下のスマホ対応

## 画像のプレースホルダ
- 画像URLは元のHTMLから抽出したものを使用
- 見つからない場合は https://picsum.photos/幅/高さ を使用

## 出力形式
CSSのみをJSON形式で出力してください。

```json
{{
  "css": "/* styles.css */..."
}}
```
"""

# Step 3: 動画からJS生成（アニメーション・インタラクション）
JS_FROM_VIDEO_PROMPT = """
添付の動画は、Webページをスクロールしながら録画したものです。
動画を分析して、以下のHTMLに対応するJavaScriptを生成してください。

## 参照HTML
```html
{html_content}
```

## 参照CSS
```css
{css_content}
```

## 動画から抽出すべき情報
1. **スクロールアニメーション**: 要素が表示されるときのフェードイン、スライドイン等
2. **ホバーエフェクト**: ボタンや画像のホバー時の変化
3. **ナビゲーション**: ハンバーガーメニューの開閉、スムーススクロール
4. **スライダー/カルーセル**: 画像の自動切り替えやスワイプ
5. **モーダル/ポップアップ**: 表示・非表示のトリガー
6. **その他インタラクション**: クリック、フォーム送信等

## JS生成要件
1. **バニラJS**: 外部ライブラリを使用しない（必要最小限のコード）
2. **イベントリスナー**: DOMContentLoadedで初期化
3. **パフォーマンス**: requestAnimationFrame、IntersectionObserverを適切に使用
4. **アクセシビリティ**: キーボード操作も考慮

## 出力形式
JavaScriptのみをJSON形式で出力してください。
アニメーションが見つからない場合は最小限の初期化コードを返してください。

```json
{{
  "js": "// script.js..."
}}
```
"""


class ImageGenerationError(Exception):
    """画像生成エラー"""
    pass


class BaseImageGenerator(ABC):
    """画像ベースジェネレーターの抽象基底クラス"""

    @abstractmethod
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
        pass

    @abstractmethod
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
            image_path: オリジナル画像のパス（参照用）

        Returns:
            修正後のコード {"html": "...", "css": "...", "js": "..."}
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """使用しているモデル名を返す"""
        pass

    def _prepare_image(self, image_path: str, max_size_bytes: int = 3 * 1024 * 1024, skip_crop: bool = False) -> tuple[Image.Image, str]:
        """
        画像を前処理（クロップ・圧縮の準備）

        Args:
            image_path: 画像ファイルパス
            max_size_bytes: 最大サイズ（3MBに設定し、base64エンコード後に4MB以下に収める）
            skip_crop: Trueの場合、フルページ画像をクロップしない（マルチセクション生成用）

        Returns:
            (処理済みPILイメージ, 画像パス)
        """
        # 画像ファイルの存在確認
        image_file = Path(image_path)
        if not image_file.exists():
            raise ImageGenerationError(f"Image file not found: {image_path}")

        img = Image.open(image_path)
        logger.info(f"Original image size: {img.size}")

        # フルページスクリーンショット（高さが幅の3倍以上）の場合、クロップ
        # ただし、skip_cropがTrueの場合はクロップしない（マルチセクション生成で全体を使う）
        if not skip_crop and img.height > img.width * 3:
            crop_height = min(img.height, img.width * 2)
            img = img.crop((0, 0, img.width, crop_height))
            logger.info(f"Cropped to viewport: {img.size}")

        # RGBに変換
        if img.mode == 'RGBA':
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        return img, image_path

    def _encode_image_to_base64(
        self,
        img: Image.Image,
        max_base64_size_bytes: int = 3_600_000  # 3.6MB（Claude 5MBの70%、安全マージン30%）
    ) -> tuple[str, str]:
        """
        PIL ImageをBase64エンコード（Claude API 5MB制限を確実に遵守）

        Args:
            img: PILイメージ
            max_base64_size_bytes: Base64エンコード後の最大サイズ（デフォルト3.6MB）

        Returns:
            (base64エンコードされた画像データ, メディアタイプ)
        """
        # RGBAモードの場合はRGBに変換（JPEGはアルファチャンネル非対応）
        if img.mode == 'RGBA':
            bg = Image.new('RGB', img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        # バイナリデータの目標サイズ（Base64は約33%増加するため）
        max_binary_size = int(max_base64_size_bytes / 1.33)

        # 高品質PNGとしてエンコードを試みる
        buffer = io.BytesIO()
        img.save(buffer, format='PNG', optimize=True)
        data = buffer.getvalue()

        # Base64エンコード後のサイズを検証
        base64_data = base64.standard_b64encode(data).decode("utf-8")
        base64_size = len(base64_data.encode('utf-8'))

        if base64_size <= max_base64_size_bytes:
            logger.info(f"PNG size: binary={len(data)/1024/1024:.2f}MB, base64={base64_size/1024/1024:.2f}MB (OK)")
            return base64_data, "image/png"

        # PNGが大きすぎる場合、高品質JPEGで試す
        logger.info(f"PNG too large (base64={base64_size/1024/1024:.2f}MB), trying JPEG...")
        buffer = io.BytesIO()
        img.save(buffer, format='JPEG', quality=90, optimize=True)
        data = buffer.getvalue()

        base64_data = base64.standard_b64encode(data).decode("utf-8")
        base64_size = len(base64_data.encode('utf-8'))

        if base64_size <= max_base64_size_bytes:
            logger.info(f"JPEG size: binary={len(data)/1024/1024:.2f}MB, base64={base64_size/1024/1024:.2f}MB (OK)")
            return base64_data, "image/jpeg"

        # まだ大きい場合は段階的に圧縮
        logger.warning(f"JPEG still too large (base64={base64_size/1024/1024:.2f}MB), compressing...")
        return self._compress_and_encode_with_validation(img, max_base64_size_bytes), "image/jpeg"

    def _compress_and_encode_with_validation(
        self,
        img: Image.Image,
        max_base64_size_bytes: int
    ) -> str:
        """
        PIL Imageを圧縮してBase64エンコード（サイズ検証付き）
        
        Base64エンコード後のサイズを実際に計算しながら、
        確実に制限内に収まるまで圧縮を繰り返す。
        
        Args:
            img: PILイメージ
            max_base64_size_bytes: Base64エンコード後の最大サイズ
            
        Returns:
            Base64エンコードされた画像データ
        """
        quality = 85  # 初期品質を90から85に下げる
        scale = 1.0
        attempts = 0
        max_attempts = 20

        while attempts < max_attempts:
            attempts += 1

            # スケーリング
            if scale < 1.0:
                new_width = int(img.width * scale)
                new_height = int(img.height * scale)
                resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
            else:
                resized = img

            # JPEG圧縮
            buffer = io.BytesIO()
            resized.save(buffer, format='JPEG', quality=quality, optimize=True)
            data = buffer.getvalue()

            # Base64エンコードして実際のサイズをチェック
            base64_data = base64.standard_b64encode(data).decode("utf-8")
            base64_size = len(base64_data.encode('utf-8'))

            if base64_size <= max_base64_size_bytes:
                logger.info(
                    f"Compressed successfully: binary={len(data)/1024/1024:.2f}MB, "
                    f"base64={base64_size/1024/1024:.2f}MB "
                    f"(scale={scale:.2f}, quality={quality}, attempts={attempts})"
                )
                return base64_data

            # 圧縮パラメータの調整（より積極的に）
            if quality > 70:
                quality -= 5
            elif quality > 50:
                quality -= 3
            elif scale > 0.7:
                scale -= 0.05
                quality = 85
            elif scale > 0.5:
                scale -= 0.05
                quality = 80
            else:
                scale -= 0.05
                quality = 75
                if scale < 0.3:
                    logger.error(
                        f"Could not compress below limit: base64={base64_size/1024/1024:.2f}MB "
                        f"(limit={max_base64_size_bytes/1024/1024:.2f}MB) after {attempts} attempts"
                    )
                    # 最後の手段：さらに小さくリサイズ
                    final_scale = 0.25
                    final_width = int(img.width * final_scale)
                    final_height = int(img.height * final_scale)
                    resized = img.resize((final_width, final_height), Image.Resampling.LANCZOS)
                    buffer = io.BytesIO()
                    resized.save(buffer, format='JPEG', quality=60, optimize=True)
                    data = buffer.getvalue()
                    return base64.standard_b64encode(data).decode("utf-8")

        # ここには到達しないはずだが、念のため
        return base64_data

    def _compress_and_encode(self, img: Image.Image, max_size_bytes: int) -> str:
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
            pattern = rf'"{key}"\s*:\s*"'
            match = re.search(pattern, json_str)
            if match:
                start = match.end()
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
                return ''.join(result)
            else:
                result.append(char)
                i += 1

        if result:
            return ''.join(result)
        return None


def create_image_generator(model_type: str = "claude") -> BaseImageGenerator:
    """
    画像ジェネレーターのファクトリ関数

    Args:
        model_type: "claude" または "gemini"

    Returns:
        BaseImageGenerator のインスタンス

    Raises:
        ValueError: 不明なmodel_typeの場合
    """
    if model_type == "claude":
        from .claude_image_generator import ClaudeImageGenerator
        return ClaudeImageGenerator()
    elif model_type == "gemini":
        from .gemini_image_generator import GeminiImageGenerator
        return GeminiImageGenerator()
    else:
        raise ValueError(f"Unknown model type: {model_type}. Supported: 'claude', 'gemini'")
