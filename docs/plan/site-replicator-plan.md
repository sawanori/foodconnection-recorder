# サイト複製機能 実装計画書 v2.0

## 概要

スクレイピングで取得したWebサイトを、Claude Code CLIを使用してHTML/CSS/JavaScriptの3ファイルに複製する機能。従量課金APIを使用せず、Claudeサブスクリプションのみで動作する。

---

## 発見された問題点と対策

### 🔴 重大な問題

| # | 問題 | 対策 |
|---|------|------|
| 1 | Claude CLI出力形式が異なる | `{"type":"result", "result":"..."}` 形式をパース |
| 2 | 出力にMarkdownコードブロックが含まれる | 正規表現で```json```ブロックを抽出 |
| 3 | 長いプロンプトはシェルエスケープ問題 | stdin経由でプロンプトを渡す |
| 4 | 非対話モードでパーミッション要求 | `--permission-mode bypassPermissions` を使用 |
| 5 | デフォルトモデルが高コスト | `--model sonnet` を明示指定 |
| 6 | 画像比較ライブラリ不足 | Pillow, numpy を追加 |

### 🟡 中程度の問題

| # | 問題 | 対策 |
|---|------|------|
| 7 | 同期subprocessがブロッキング | asyncio.subprocess を使用 |
| 8 | 大きなページでコンテキスト超過 | ページサイズ制限 + 分割処理 |
| 9 | スクリーンショットサイズ不一致 | 固定ビューポート(1366x768) |
| 10 | 一時ファイルの残留 | 完了時にクリーンアップ |
| 11 | DBマイグレーション未定義 | 明示的なマイグレーションスクリプト |

### 🟢 軽微な問題

| # | 問題 | 対策 |
|---|------|------|
| 12 | リトライロジック不足 | 3回リトライ + 指数バックオフ |
| 13 | ログ/監視不足 | 構造化ログ追加 |
| 14 | 並行ジョブ制御なし | セマフォで同時実行数制限 |

---

## システム構成（修正版）

```
┌─────────────────────────────────────────────────────────────┐
│                    Food Connection Recorder                  │
├─────────────────────────────────────────────────────────────┤
│  Frontend (Next.js) - http://localhost:3000                 │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  /replicate ページ                                   │   │
│  │  - URL入力フォーム                                   │   │
│  │  - 進捗表示（WebSocket/Subscription）               │   │
│  │  - 比較プレビュー（オリジナル vs 生成）              │   │
│  │  - ダウンロードボタン                               │   │
│  └─────────────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  Backend (FastAPI + GraphQL) - http://localhost:8000        │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  ReplicatorService (asyncio)                        │   │
│  │                                                      │   │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐        │   │
│  │  │ Scraper  │──▶│Generator │──▶│ Verifier │        │   │
│  │  │Playwright│   │Claude CLI│   │Playwright│        │   │
│  │  └──────────┘   └──────────┘   └──────────┘        │   │
│  │       │              │              │               │   │
│  │       ▼              ▼              ▼               │   │
│  │  scraped.json   生成ファイル    比較結果            │   │
│  │                 ├─index.html   ├─similarity%        │   │
│  │                 ├─styles.css   └─diff_report        │   │
│  │                 └─script.js                         │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼ stdin経由
              ┌─────────────────────────────┐
              │      Claude Code CLI        │
              │  claude -p --model sonnet   │
              │  --permission-mode bypass   │
              │  --output-format json       │
              │   (サブスクリプション使用)   │
              └─────────────────────────────┘
```

---

## 処理フロー（修正版）

### Phase 1: スクレイピング（素材収集）

```python
async def scrape_site(url: str) -> dict:
    """サイトの素材を収集"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 1366, "height": 768}  # 固定サイズ
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle")

        # 収集データ
        data = {
            "url": url,
            "title": await page.title(),
            "html": await page.content(),
            "viewport": {"width": 1366, "height": 768},

            # 全要素のスタイル情報
            "computed_styles": await page.evaluate("""
                () => {
                    const elements = document.querySelectorAll('*');
                    const styles = [];
                    elements.forEach((el, i) => {
                        if (i < 500) {  // 要素数制限
                            const cs = getComputedStyle(el);
                            styles.push({
                                tag: el.tagName,
                                classes: el.className,
                                styles: {
                                    color: cs.color,
                                    backgroundColor: cs.backgroundColor,
                                    fontSize: cs.fontSize,
                                    fontFamily: cs.fontFamily,
                                    margin: cs.margin,
                                    padding: cs.padding,
                                    display: cs.display,
                                    position: cs.position,
                                    width: cs.width,
                                    height: cs.height,
                                }
                            });
                        }
                    });
                    return styles;
                }
            """),

            # 外部スタイルシート
            "stylesheets": await page.evaluate("""
                () => {
                    const sheets = [];
                    for (const sheet of document.styleSheets) {
                        try {
                            const rules = [];
                            for (const rule of sheet.cssRules) {
                                rules.push(rule.cssText);
                            }
                            sheets.push(rules.join('\\n'));
                        } catch (e) {
                            // CORSエラーは無視
                        }
                    }
                    return sheets;
                }
            """),

            # スクリーンショット（Base64）
            "screenshot_base64": base64.b64encode(
                await page.screenshot(full_page=True)
            ).decode()
        }

        # データサイズチェック（Claude コンテキスト制限）
        data_str = json.dumps(data)
        if len(data_str) > 100000:  # 100KB制限
            # 大きすぎる場合は簡略化
            data["computed_styles"] = data["computed_styles"][:100]
            data["stylesheets"] = data["stylesheets"][:5]

        await browser.close()
        return data
```

### Phase 2: Claude CLI でファイル生成（修正版）

```python
import asyncio
import json
import re

# 専用システムプロンプト（短く焦点を絞る）
SYSTEM_PROMPT = """あなたはWebサイト複製の専門家です。
与えられたスクレイピングデータから、完全な見た目の複製を作成します。
必ずJSON形式で出力してください。余計な説明は不要です。"""

GENERATE_PROMPT_TEMPLATE = """
以下のスクレイピングデータから、Webページを複製してください。

## 要件
1. 3つのファイルを生成: index.html, styles.css, script.js
2. オリジナルと完全に同じ見た目を再現
3. ビューポートサイズ: {viewport_width}x{viewport_height}px
4. 外部画像はオリジナルURLをそのまま使用
5. CSSはクラスベースで整理

## スクレイピングデータ
{scraped_data}

## 出力形式（厳守）
```json
{{
  "html": "<!DOCTYPE html>...",
  "css": "/* styles */...",
  "js": "// scripts..."
}}
```
"""

async def call_claude_cli(prompt: str, timeout: int = 300) -> dict:
    """
    Claude Code CLIを非同期で呼び出し

    Returns:
        {"html": "...", "css": "...", "js": "..."}
    """
    cmd = [
        "claude",
        "-p",  # 非対話モード
        "--model", "sonnet",  # コスト効率のためsonnet使用
        "--output-format", "json",
        "--permission-mode", "bypassPermissions",  # パーミッション回避
        "--system-prompt", SYSTEM_PROMPT,
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(input=prompt.encode('utf-8')),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        process.kill()
        raise TimeoutError(f"Claude CLI timed out after {timeout}s")

    if process.returncode != 0:
        raise RuntimeError(f"Claude CLI error: {stderr.decode()}")

    # JSON出力をパース
    output = stdout.decode('utf-8')
    try:
        response = json.loads(output)
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON from Claude CLI: {output[:500]}")

    # エラーチェック
    if response.get("is_error"):
        raise RuntimeError(f"Claude returned error: {response.get('result')}")

    # resultフィールドから実際のコンテンツを取得
    result_text = response.get("result", "")

    # Markdownコードブロックからjson JSONを抽出
    code_block_match = re.search(r'```json\s*([\s\S]*?)\s*```', result_text)
    if code_block_match:
        json_str = code_block_match.group(1)
    else:
        # コードブロックがない場合、全体をJSONとして試行
        json_str = result_text

    try:
        generated = json.loads(json_str)
    except json.JSONDecodeError:
        # JSON抽出失敗時のフォールバック
        raise ValueError(f"Could not extract JSON from Claude response: {result_text[:500]}")

    # 必須フィールド検証
    required_fields = ["html", "css", "js"]
    for field in required_fields:
        if field not in generated:
            raise ValueError(f"Missing required field '{field}' in Claude response")

    return generated
```

### Phase 3: Playwright検証（修正版）

```python
from PIL import Image
import numpy as np
import io
import base64

async def verify_replication(
    original_url: str,
    generated_html_path: str,
    iteration: int
) -> dict:
    """
    オリジナルと生成サイトを比較

    Returns:
        {
            "similarity_score": float,  # 0-100
            "diff_regions": list,
            "original_screenshot": str,  # base64
            "generated_screenshot": str,  # base64
            "diff_report": str
        }
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)

        # 同じビューポートサイズで比較
        viewport = {"width": 1366, "height": 768}

        # オリジナルのスクリーンショット
        context1 = await browser.new_context(viewport=viewport)
        page1 = await context1.new_page()
        await page1.goto(original_url, wait_until="networkidle")
        original_screenshot = await page1.screenshot(full_page=True)
        await context1.close()

        # 生成サイトのスクリーンショット
        context2 = await browser.new_context(viewport=viewport)
        page2 = await context2.new_page()
        await page2.goto(f"file://{generated_html_path}", wait_until="networkidle")
        generated_screenshot = await page2.screenshot(full_page=True)
        await context2.close()

        await browser.close()

    # 画像比較
    comparison = compare_images(original_screenshot, generated_screenshot)

    # 差分レポート生成
    diff_report = generate_diff_report(comparison, iteration)

    return {
        "similarity_score": comparison["similarity"],
        "diff_regions": comparison["diff_regions"],
        "original_screenshot": base64.b64encode(original_screenshot).decode(),
        "generated_screenshot": base64.b64encode(generated_screenshot).decode(),
        "diff_report": diff_report
    }


def compare_images(img1_bytes: bytes, img2_bytes: bytes) -> dict:
    """2つの画像をピクセル単位で比較"""
    img1 = Image.open(io.BytesIO(img1_bytes)).convert('RGB')
    img2 = Image.open(io.BytesIO(img2_bytes)).convert('RGB')

    # サイズを揃える（小さい方に合わせる）
    min_width = min(img1.width, img2.width)
    min_height = min(img1.height, img2.height)
    img1 = img1.crop((0, 0, min_width, min_height))
    img2 = img2.crop((0, 0, min_width, min_height))

    # numpy配列に変換
    arr1 = np.array(img1, dtype=np.float32)
    arr2 = np.array(img2, dtype=np.float32)

    # ピクセル差分
    diff = np.abs(arr1 - arr2)

    # 類似度計算 (0-100%)
    max_possible_diff = 255.0 * 3 * min_width * min_height
    actual_diff = np.sum(diff)
    similarity = (1 - actual_diff / max_possible_diff) * 100

    # 差分が大きい領域を特定
    diff_gray = np.mean(diff, axis=2)
    threshold = 30  # 差分閾値
    diff_mask = diff_gray > threshold

    # 差分領域をバウンディングボックスで表現
    diff_regions = find_bounding_boxes(diff_mask)

    return {
        "similarity": round(similarity, 2),
        "diff_regions": diff_regions,
        "diff_pixels": int(np.sum(diff_mask))
    }


def find_bounding_boxes(mask: np.ndarray) -> list:
    """差分マスクからバウンディングボックスを検出"""
    from scipy import ndimage

    labeled, num_features = ndimage.label(mask)
    boxes = []
    for i in range(1, num_features + 1):
        positions = np.where(labeled == i)
        if len(positions[0]) > 100:  # 小さすぎる領域は無視
            y_min, y_max = positions[0].min(), positions[0].max()
            x_min, x_max = positions[1].min(), positions[1].max()
            boxes.append({
                "x": int(x_min),
                "y": int(y_min),
                "width": int(x_max - x_min),
                "height": int(y_max - y_min)
            })
    return boxes[:10]  # 最大10領域


def generate_diff_report(comparison: dict, iteration: int) -> str:
    """差分レポートを生成"""
    report = f"""
## 検証結果 (イテレーション {iteration}/3)

- 類似度: {comparison['similarity']}%
- 差分ピクセル数: {comparison['diff_pixels']}

### 差分領域
"""
    for i, region in enumerate(comparison["diff_regions"], 1):
        report += f"- 領域{i}: x={region['x']}, y={region['y']}, "
        report += f"サイズ={region['width']}x{region['height']}px\n"

    if comparison["similarity"] >= 95:
        report += "\n✅ 高い類似度です。微調整のみ必要です。"
    elif comparison["similarity"] >= 80:
        report += "\n⚠️ 中程度の類似度です。レイアウトの修正が必要です。"
    else:
        report += "\n❌ 類似度が低いです。大幅な修正が必要です。"

    return report
```

---

## 依存関係（修正版）

### backend/requirements.txt に追加

```
# 画像処理（追加）
Pillow==10.1.0
numpy==1.26.2
scipy==1.11.4
```

---

## データモデル（修正版）

### models.py に追加

```python
from enum import Enum as PyEnum

class ReplicationStatus(PyEnum):
    PENDING = "pending"
    SCRAPING = "scraping"
    GENERATING = "generating"
    VERIFYING_1 = "verifying_1"
    VERIFYING_2 = "verifying_2"
    VERIFYING_3 = "verifying_3"
    COMPLETED = "completed"
    FAILED = "failed"


class ReplicationJobModel(Base):
    __tablename__ = "replication_jobs"

    id = Column(String, primary_key=True)
    source_url = Column(String, nullable=False)
    status = Column(SQLEnum(ReplicationStatus), default=ReplicationStatus.PENDING)
    current_iteration = Column(Integer, default=0)
    similarity_score = Column(Float, nullable=True)
    output_dir = Column(String, nullable=False)

    # 生成ファイルパス
    html_filename = Column(String, nullable=True)
    css_filename = Column(String, nullable=True)
    js_filename = Column(String, nullable=True)

    # エラー情報
    error_message = Column(String, nullable=True)

    # タイムスタンプ
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

---

## ファイル構成（修正版）

```
backend/
├── app/
│   ├── services/
│   │   ├── replicator/
│   │   │   ├── __init__.py
│   │   │   ├── site_scraper.py     # サイト素材収集
│   │   │   ├── claude_generator.py # Claude CLI呼び出し
│   │   │   ├── verifier.py         # Playwright検証
│   │   │   └── image_comparator.py # 画像比較ユーティリティ
│   │   └── replicator_runner.py    # ジョブ制御
│   ├── models.py                   # ReplicationJobModel追加
│   └── schema.py                   # GraphQL追加
│
frontend/
├── app/                            # App Router使用
│   └── replicate/
│       └── page.tsx                # 複製ページ
├── components/
│   ├── ReplicatorForm.tsx
│   ├── ReplicatorProgress.tsx
│   └── ComparisonPreview.tsx
```

---

## エラーハンドリング

```python
class ReplicatorError(Exception):
    """複製エラーの基底クラス"""
    pass

class ScrapingError(ReplicatorError):
    """スクレイピングエラー"""
    pass

class GenerationError(ReplicatorError):
    """Claude CLI生成エラー"""
    pass

class VerificationError(ReplicatorError):
    """検証エラー"""
    pass

# リトライデコレータ
async def with_retry(func, max_retries=3, backoff_base=2):
    """指数バックオフ付きリトライ"""
    for attempt in range(max_retries):
        try:
            return await func()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            wait_time = backoff_base ** attempt
            logger.warning(f"Retry {attempt + 1}/{max_retries} after {wait_time}s: {e}")
            await asyncio.sleep(wait_time)
```

---

## 並行実行制御

```python
import asyncio

# 同時実行数制限（Claude CLIの負荷軽減）
MAX_CONCURRENT_JOBS = 2
replication_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

async def run_replication_job(job_id: str):
    """セマフォで同時実行数を制限"""
    async with replication_semaphore:
        await _execute_replication(job_id)
```

---

## 実装フェーズ（修正版）

### Phase 1: 基盤構築（0.5日）
- [x] 計画書レビュー・修正
- [ ] requirements.txt 更新
- [ ] ReplicationJobModel 追加
- [ ] データベーステーブル作成

### Phase 2: スクレイピング（0.5日）
- [ ] site_scraper.py 実装
- [ ] スクレイピングテスト

### Phase 3: Claude CLI連携（1日）
- [ ] claude_generator.py 実装
- [ ] プロンプトテンプレート作成
- [ ] 出力パーステスト
- [ ] エラーハンドリング

### Phase 4: 検証機能（1日）
- [ ] verifier.py 実装
- [ ] image_comparator.py 実装
- [ ] 検証ループテスト

### Phase 5: 統合（0.5日）
- [ ] replicator_runner.py 実装
- [ ] GraphQL API追加
- [ ] E2Eテスト

### Phase 6: フロントエンド（1日）
- [ ] 複製ページUI
- [ ] 進捗表示
- [ ] プレビュー機能

**合計: 約4.5日**

---

## テスト計画

### 単体テスト
```python
# tests/test_replicator.py

async def test_scrape_simple_site():
    """シンプルなサイトのスクレイピング"""
    data = await scrape_site("https://example.com")
    assert "html" in data
    assert "computed_styles" in data

async def test_claude_cli_generation():
    """Claude CLI呼び出しテスト"""
    result = await call_claude_cli("簡単なHTMLを生成: Hello World")
    assert "html" in result

async def test_image_comparison():
    """画像比較テスト"""
    # 同じ画像 = 100%類似
    result = compare_images(img_bytes, img_bytes)
    assert result["similarity"] == 100.0
```

### E2Eテスト
```python
async def test_full_replication_flow():
    """完全な複製フロー"""
    job = await create_replication_job("https://example.com", "test-output")
    await start_replication(job.id)

    # 完了まで待機
    while True:
        job = await get_replication_job(job.id)
        if job.status == ReplicationStatus.COMPLETED:
            break
        if job.status == ReplicationStatus.FAILED:
            pytest.fail(f"Replication failed: {job.error_message}")
        await asyncio.sleep(5)

    # 結果検証
    assert job.similarity_score >= 70  # 最低70%類似
    assert os.path.exists(f"output/{job.output_dir}/index.html")
```

---

## 成功基準（修正版）

| 項目 | 基準 |
|------|------|
| 機能完成 | URL入力→3ファイル生成→3回検証が動作 |
| 類似度 | 平均80%以上（シンプルなサイト） |
| 処理時間 | 1サイト5分以内 |
| コスト | API従量課金なし（サブスクのみ） |
| エラー率 | 正常系90%以上成功 |

---

## リスクと対策（修正版）

| リスク | 影響 | 対策 |
|--------|------|------|
| Claude CLIレート制限 | 処理停止 | リトライ + バックオフ |
| 大規模サイト | コンテキスト超過 | 100KB制限 + 簡略化 |
| 動的コンテンツ | 再現不可 | 静的スナップショットとして明記 |
| 外部リソースCORS | CSS取得失敗 | エラー無視 + フォールバック |
| Claude CLI未インストール | 起動失敗 | 起動時チェック + エラーメッセージ |

---

## 次のステップ

1. ✅ 計画書レビュー完了
2. → Phase 1から実装開始

---

作成日: 2026-01-16
更新日: 2026-01-16 (v2.0 - 問題点修正)
