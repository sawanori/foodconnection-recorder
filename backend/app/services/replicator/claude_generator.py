"""
Claude CLIジェネレーター

Claude Code CLIを使用してHTML/CSS/JSを生成します。
"""
import asyncio
import json
import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# 専用システムプロンプト（短く焦点を絞る）
SYSTEM_PROMPT = """あなたはWebサイト複製の専門家です。
与えられたスクレイピングデータから、完全な見た目の複製を作成します。
必ずJSON形式で出力してください。余計な説明は不要です。"""

# 生成プロンプトテンプレート
GENERATE_PROMPT_TEMPLATE = """
以下のスクレイピングデータから、Webページを複製してください。

## 要件
1. 3つのファイルを生成: index.html, styles.css, script.js
2. オリジナルと完全に同じ見た目を再現
3. ビューポートサイズ: {viewport_width}x{viewport_height}px
4. 外部画像はオリジナルURLをそのまま使用
5. CSSはクラスベースで整理
6. HTMLは適切なセマンティック要素を使用
7. CSSファイルは styles.css として外部参照
8. JSファイルは script.js として外部参照

## スクレイピングデータ
URL: {url}
タイトル: {title}

### HTML構造
{html_snippet}

### 計算済みスタイル（主要要素）
{styles_snippet}

### 既存スタイルシート
{stylesheets_snippet}

## 出力形式（厳守）
以下のJSON形式で出力してください。他のテキストは含めないでください。

```json
{{
  "html": "<!DOCTYPE html>...(完全なHTML)",
  "css": "/* styles.css の内容 */...",
  "js": "// script.js の内容（必要に応じて）..."
}}
```
"""

# 修正プロンプトテンプレート
REFINE_PROMPT_TEMPLATE = """
前回生成したコードを修正してください。

## 検証結果
- 類似度: {similarity_score}%
- 差分箇所:
{diff_report}

## 前回のコード

### HTML
```html
{previous_html}
```

### CSS
```css
{previous_css}
```

### JS
```javascript
{previous_js}
```

## 修正要件
上記の差分を解消し、オリジナルにより近づけてください。
特に以下の点に注意:
- レイアウトのずれを修正
- 色やフォントの違いを修正
- 欠落している要素を追加

## 出力形式（厳守）
以下のJSON形式で出力してください。

```json
{{
  "html": "<!DOCTYPE html>...(修正後の完全なHTML)",
  "css": "/* 修正後のCSS */...",
  "js": "// 修正後のJS..."
}}
```
"""


class GenerationError(Exception):
    """生成エラー"""
    pass


class ClaudeGenerator:
    """Claude CLIジェネレータークラス"""

    def __init__(self, timeout: int = 300):
        """
        Args:
            timeout: CLIタイムアウト（秒）
        """
        self.timeout = timeout

    async def generate(self, scraped_data: Dict[str, Any]) -> Dict[str, str]:
        """
        スクレイピングデータからHTML/CSS/JSを生成

        Args:
            scraped_data: スクレイピングデータ

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            GenerationError: 生成失敗時
        """
        prompt = self._build_generate_prompt(scraped_data)
        return await self._call_claude_cli(prompt)

    async def refine(
        self,
        previous_code: Dict[str, str],
        similarity_score: float,
        diff_report: str
    ) -> Dict[str, str]:
        """
        前回のコードを修正

        Args:
            previous_code: 前回生成したコード
            similarity_score: 類似度スコア
            diff_report: 差分レポート

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            GenerationError: 生成失敗時
        """
        prompt = REFINE_PROMPT_TEMPLATE.format(
            similarity_score=similarity_score,
            diff_report=diff_report,
            previous_html=previous_code.get("html", "")[:5000],  # 長さ制限
            previous_css=previous_code.get("css", "")[:3000],
            previous_js=previous_code.get("js", "")[:2000],
        )
        return await self._call_claude_cli(prompt)

    def _build_generate_prompt(self, data: Dict[str, Any]) -> str:
        """生成プロンプトを構築"""
        # HTML スニペット（長すぎる場合は切り詰め）
        html = data.get("html", "")
        html_snippet = html[:10000] if len(html) > 10000 else html

        # スタイル スニペット
        styles = data.get("computed_styles", [])
        styles_snippet = json.dumps(styles[:50], ensure_ascii=False, indent=2)

        # スタイルシート スニペット
        stylesheets = data.get("stylesheets", [])
        stylesheets_snippet = "\n---\n".join(s[:2000] for s in stylesheets[:3])

        viewport = data.get("viewport", {"width": 1366, "height": 768})

        return GENERATE_PROMPT_TEMPLATE.format(
            viewport_width=viewport["width"],
            viewport_height=viewport["height"],
            url=data.get("url", ""),
            title=data.get("title", ""),
            html_snippet=html_snippet,
            styles_snippet=styles_snippet,
            stylesheets_snippet=stylesheets_snippet,
        )

    async def _call_claude_cli(self, prompt: str) -> Dict[str, str]:
        """
        Claude Code CLIを非同期で呼び出し

        Args:
            prompt: プロンプト

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            GenerationError: 呼び出し失敗時
        """
        cmd = [
            "claude",
            "-p",  # 非対話モード
            "--model", "sonnet",  # コスト効率のためsonnet使用
            "--output-format", "json",
            "--permission-mode", "bypassPermissions",  # パーミッション回避
            "--system-prompt", SYSTEM_PROMPT,
        ]

        logger.info("Calling Claude CLI...")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=prompt.encode('utf-8')),
                timeout=self.timeout
            )

        except asyncio.TimeoutError:
            raise GenerationError(f"Claude CLI timed out after {self.timeout}s")
        except FileNotFoundError:
            raise GenerationError("Claude CLI not found. Please ensure 'claude' is installed and in PATH.")
        except Exception as e:
            raise GenerationError(f"Failed to execute Claude CLI: {e}")

        if process.returncode != 0:
            stderr_text = stderr.decode('utf-8', errors='replace')
            raise GenerationError(f"Claude CLI error (code {process.returncode}): {stderr_text}")

        # 出力をパース
        output = stdout.decode('utf-8')
        return self._parse_cli_output(output)

    def _parse_cli_output(self, output: str) -> Dict[str, str]:
        """
        Claude CLI出力をパース

        Args:
            output: CLI出力

        Returns:
            {"html": "...", "css": "...", "js": "..."}

        Raises:
            GenerationError: パース失敗時
        """
        # JSON出力をパース
        try:
            response = json.loads(output)
        except json.JSONDecodeError as e:
            raise GenerationError(f"Invalid JSON from Claude CLI: {e}\nOutput: {output[:500]}")

        # エラーチェック
        if response.get("is_error"):
            raise GenerationError(f"Claude returned error: {response.get('result')}")

        # resultフィールドから実際のコンテンツを取得
        result_text = response.get("result", "")

        if not result_text:
            raise GenerationError("Empty result from Claude CLI")

        # JSONを抽出
        generated = self._extract_json_from_result(result_text)

        # 必須フィールド検証
        required_fields = ["html", "css", "js"]
        for field in required_fields:
            if field not in generated:
                # 空のデフォルト値を設定
                generated[field] = "" if field == "js" else f"/* {field} not generated */"
                logger.warning(f"Missing required field '{field}' in Claude response, using default")

        logger.info("Claude CLI response parsed successfully")
        return generated

    def _extract_json_from_result(self, result_text: str) -> Dict[str, str]:
        """
        result テキストからJSONを抽出

        Args:
            result_text: Claude の result フィールド

        Returns:
            抽出されたJSON辞書

        Raises:
            GenerationError: 抽出失敗時
        """
        # 方法1: ```json ... ``` ブロックから抽出
        code_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', result_text)
        if code_block_match:
            json_str = code_block_match.group(1)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass  # 次の方法を試行

        # 方法2: ``` ... ``` ブロックから抽出（言語指定なし）
        code_block_match = re.search(r'```\s*([\s\S]*?)\s*```', result_text)
        if code_block_match:
            json_str = code_block_match.group(1)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 方法3: { で始まり } で終わる部分を抽出
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            json_str = json_match.group(0)
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 方法4: 全体をJSONとして試行
        try:
            return json.loads(result_text)
        except json.JSONDecodeError:
            pass

        raise GenerationError(
            f"Could not extract JSON from Claude response.\n"
            f"Response preview: {result_text[:500]}..."
        )
