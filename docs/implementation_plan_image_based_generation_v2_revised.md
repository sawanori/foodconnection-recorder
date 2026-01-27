# 実装計画書: 画像ベース生成機能の復活（修正版）

**作成日**: 2026-01-27
**バージョン**: 2.1（徹底レビュー後修正版）
**目的**: 削除された画像ベース生成機能を、改善と既存システムとの整合性を保って復活させる

---

## ⚠️ 重要な修正点（v2.0 からの変更）

### v2.0 の重大な設計ミス

1. **ReplicationJobModel に screenshot_path フィールドが存在しない**
   - v2.0 では `job.screenshot_path` を使用
   - しかし、実際のモデルには存在しない
   - **修正**: マイグレーションで追加が必要

2. **source_url が必須（nullable=False）**
   - 画像のみから生成する場合、URL がない
   - **修正**: URL + 画像のハイブリッドアプローチに変更

3. **検証に original_url が必須**
   - `verifier.verify(original_url, ...)` は URL を必須パラメータとする
   - 画像のみでは検証不可
   - **修正**: URL がある場合のみ検証

4. **_get_job メソッドが存在しない**
   - **修正**: 実装を追加

5. **依存関係とconfig不足**
   - anthropic, scikit-learn が requirements.txt にない
   - config.py に IMAGE_GENERATOR 設定がない
   - **修正**: 全て追加

### v2.1 の修正アプローチ

**ハイブリッドアプローチ（URL + 画像）を採用**

- ✅ 既存システムを壊さない
- ✅ 後方互換性を保つ
- ✅ 段階的実装が可能
- ✅ URL がある場合は検証可能
- ✅ 画像がある場合は精度向上

---

## 📋 1. 背景と経緯

### 1.1 以前の実装（削除済み）

**コミット `2add71d`** までに以下の機能が実装されていました：

```
backend/app/services/replicator/
├── base_image_generator.py      # 基底クラス（圧縮、エンコーディング）
├── claude_image_generator.py    # Claude Vision API
├── gemini_image_generator.py    # Gemini API
├── multi_section_generator.py   # セクション分割生成
├── design_extractor.py          # デザイン抽出
└── image_generator.py           # ファクトリパターン
```

**機能:**
- スクリーンショットを複数セクションに分割
- セクションごとに HTML/CSS/JS を生成
- 最後に結果を統合

### 1.2 削除の理由

**問題**: 画像サイズが Claude API の5MB制限を超過
```
実際の送信サイズ: 5.5MB (5,540,112 bytes)
Claude API 制限: 5MB (5,242,880 bytes)
超過量: 5.7%
```

**原因**: PNG形式で分割した各セクションを送信していた可能性が高い

**対応**: 機能を削除し、URL ベースのスクレイピングに戻した

### 1.3 現在のシステムの構造

**ジョブフロー:**
```
ReplicationJob
├── source_url: str (必須)
├── status: ReplicationStatus
├── output_dir: str
└── (検証に URL を使用)

処理フロー:
1. スクレイピング（SiteScraper）: URL → HTML + CSS
2. 生成（ClaudeGenerator）: Claude CLI でコード生成
3. 検証（Verifier）: URL と生成結果を比較（3回まで）
4. 完了
```

### 1.4 今回の目標

**「画像から直接Webサイトを生成する機能」を復活させる**

ただし、以下の制約と改善を考慮：

**制約:**
- ✅ 既存の URL ベース生成を壊さない
- ✅ ReplicationJobModel の source_url は必須のまま
- ✅ 検証には URL が必要
- ✅ 後方互換性を保つ

**改善:**
- ✅ セクション分割を廃止 → 単一画像で送信
- ✅ JPEG 圧縮で 5MB以内に確実に収める
- ✅ Base64 サイズを送信前に検証
- ✅ コンポーネント完全性の向上

**アプローチ: ハイブリッド（URL + 画像）**
- URL は必須のまま（検証のため）
- screenshot_path をオプションで追加
- 画像があれば画像から生成（高精度）
- なければ URL から生成（既存ロジック）

---

## 🎯 2. 技術的根拠

### 2.1 画像サイズの検証結果

**テスト画像**: 973x5000px（フルページスクリーンショット）

| 形式 | 品質 | バイナリサイズ | Base64サイズ | 5MB制限内 |
|-----|------|-------------|------------|----------|
| PNG | - | 4.9MB | 6.5MB | ❌ 超過 |
| JPEG | Quality 90 | 0.62MB | 0.83MB | ✅ OK |
| JPEG | Quality 85 | 0.57MB | **0.76MB** | ✅ OK |
| JPEG | Quality 75 | 0.44MB | 0.58MB | ✅ OK |

**結論**: Quality 85 で **0.76MB**（5MB制限の**15%のみ**）
→ **セクション分割は完全に不要**

### 2.2 改善されたアーキテクチャ

#### Before（削除された実装）
```
スクリーンショット（973x5000px, PNG）
  ↓
フルページ判定（height > width * 2.5）
  ↓ YES
セクション分割（3〜8セクション）
  ↓
各セクションをPNGでBase64エンコード（各約2MB）
  ↓ 合計6MB → 5MB超過 ❌
エラー: overload_error
```

#### After（今回の実装）
```
ReplicationJob作成（URL + screenshot_path）
  ↓
screenshot_path あり？
  ↓ YES
スクリーンショット読み込み（973x5000px）
  ↓
JPEG圧縮（Quality 85）
  ↓
Base64エンコード（0.76MB）✅
  ↓
Claude Vision API（単一画像）
  ↓
完全なHTML/CSS/JS生成
  ↓
検証（URL使用）
  ↓
完了
```

---

## 📝 3. 実装ファイル一覧

### 3.1 新規作成ファイル

| ファイル | 行数 | 目的 |
|---------|------|------|
| `base_image_generator.py` | 約550行 | 基底クラス（画像処理、圧縮、エンコーディング） |
| `claude_image_generator.py` | 約350行 | Claude Vision API 実装 |
| `gemini_image_generator.py` | 約450行 | Gemini Vision API 実装（オプション） |
| `image_generator.py` | 約50行 | ファクトリパターン |
| `design_extractor.py` | 約150行 | デザイン要素抽出（色、フォント） |

**合計**: 約1550行

### 3.2 修正ファイル

| ファイル | 修正内容 | 影響度 |
|---------|---------|--------|
| `models.py` | screenshot_path フィールド追加、マイグレーション | 🔴 高 |
| `replicator_runner.py` | 画像ベース生成フローの追加、_get_job実装 | 🔴 高 |
| `config.py` | IMAGE_GENERATOR, ANTHROPIC_API_KEY 設定追加 | 🟡 中 |
| `requirements.txt` | anthropic, scikit-learn 追加 | 🟡 中 |
| `replicator/__init__.py` | ImageGeneratorFactory エクスポート追加 | 🟢 低 |
| `schema.py` | GraphQL スキーマに screenshot_path 追加 | 🟡 中 |

### 3.3 マイグレーション

**データベーススキーマ変更:**
```sql
ALTER TABLE replication_jobs
ADD COLUMN screenshot_path VARCHAR(500) NULL;
```

**Alembic マイグレーション（必要に応じて）**

---

## 🏗️ 4. 実装の詳細

### 4.1 models.py の修正

#### 変更内容

```python
class ReplicationJobModel(Base):
    """サイト複製ジョブモデル"""
    __tablename__ = "replication_jobs"

    id = Column(String, primary_key=True)
    source_url = Column(String, nullable=False)  # 既存（必須のまま）
    screenshot_path = Column(String, nullable=True)  # 🆕 追加（オプション）
    status = Column(Enum(ReplicationStatus), default=ReplicationStatus.PENDING, nullable=False)
    current_iteration = Column(Integer, default=0, nullable=False)
    similarity_score = Column(Float, nullable=True)
    output_dir = Column(String, nullable=False)

    # 生成ファイルパス
    html_filename = Column(String, nullable=True)
    css_filename = Column(String, nullable=True)
    js_filename = Column(String, nullable=True)

    # エラー情報
    error_message = Column(String, nullable=True)

    # タイムスタンプ
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
```

**ポイント:**
- ✅ `source_url` は必須のまま（既存システムとの互換性）
- ✅ `screenshot_path` はオプション（画像ベース生成時に使用）
- ✅ 両方指定可能（ハイブリッドアプローチ）

### 4.2 base_image_generator.py（基底クラス）

**責任範囲:**
- 画像の前処理（RGBA → RGB変換）
- JPEG圧縮（段階的品質調整）
- Base64エンコーディングとサイズ検証
- 共通プロンプト定義

**主要メソッド:**

#### 4.2.1 画像エンコーディング
```python
def _encode_image_to_base64(
    self,
    img: Image.Image,
    max_base64_size_bytes: int = 3_600_000  # 3.6MB（70%マージン）
) -> tuple[str, str]:
    """
    画像をBase64エンコード（5MB制限を確実に遵守）

    処理フロー:
    1. RGBA → RGB 変換
    2. PNG最適化を試す
    3. JPEG quality=90 を試す
    4. ダメなら段階的圧縮（85→80→75→...→50）
    5. まだダメならスケーリング（1.0→0.95→...→0.3）
    6. 最終手段: scale=0.25, quality=60

    Returns:
        (base64_data, media_type)
    """
    # 実装詳細は2add71dから復元
```

**テスト結果:**
```
973x5000px 画像:
- Attempt 1: Quality=85 → 0.76MB ✅ 成功！
```

#### 4.2.2 システムプロンプト
```python
SYSTEM_PROMPT = """
あなたはWebサイト制作のエキスパートです。
画像から完全に同じデザインのWebサイトを再現することが得意です。

重要な指示:
1. 画像に表示されている**全てのコンテンツ**を含めてください
2. レイアウト、色、フォント、余白を正確に再現してください
3. レスポンシブデザインに対応してください
4. プレースホルダー画像は https://picsum.photos/ を使用してください
"""
```

### 4.3 claude_image_generator.py（Claude Vision API）

#### 主要メソッド

```python
class ClaudeImageGenerator(BaseImageGenerator):
    def __init__(self):
        super().__init__()
        # Anthropic SDK初期化
        self.client = anthropic.Anthropic(
            api_key=settings.ANTHROPIC_API_KEY,
            timeout=900.0  # 15分
        )

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
        画像から直接 HTML/CSS/JS を生成

        Args:
            image_path: スクリーンショット画像パス
            html_content: 元HTMLソース（オプション、参考情報）
            video_path: 録画動画パス（オプション）
            viewport_width: ビューポート幅
            viewport_height: ビューポート高さ
            design_tokens: デザイン要素（色、フォント）

        Returns:
            {"html": "...", "css": "...", "js": "..."}
        """
        logger.info(f"Generating from image: {image_path}")

        # 画像読み込み & エンコード
        img = Image.open(image_path)
        image_data, media_type = self._encode_image_to_base64(img)

        # プロンプト構築
        prompt = self._build_prompt(
            viewport_width, viewport_height, design_tokens
        )

        # API呼び出し
        return await self._call_api_with_image(
            image_data, media_type, prompt
        )

    async def _call_api_with_image(
        self,
        image_data: str,
        media_type: str,
        prompt: str
    ) -> Dict[str, str]:
        """Claude Vision API 呼び出し"""
        response = self.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=8000,
            timeout=900.0,
            system=[{"type": "text", "text": SYSTEM_PROMPT}],
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
            ]
        )

        result_text = response.content[0].text
        return self._parse_response(result_text)

    def _build_prompt(
        self,
        viewport_width: int,
        viewport_height: int,
        design_tokens: Optional[Dict]
    ) -> str:
        """プロンプト構築"""
        colors = design_tokens.get("colors", []) if design_tokens else []
        fonts = design_tokens.get("fonts", []) if design_tokens else []

        return f"""
添付画像はWebページのスクリーンショットです。
この画像を見て、完全に同じデザインのWebサイトを再現するコードを生成してください。

## 実装要件
1. **完全なHTML構造**: <!DOCTYPE html>から</html>まで
2. **デザイン再現**:
   - レイアウト: {viewport_width}x{viewport_height}px
   - 色: {colors}
   - フォント: {fonts}
3. **ヒーローセクション高さルール**（重要）:
   ```css
   .hero {{
     height: 80vh;  /* PC（1024px以上） */
   }}
   @media (max-width: 1023px) {{
     .hero {{ height: 100vh; }}  /* タブレット・スマホ */
   }}
   ```
4. **レスポンシブ**: モバイル対応（max-width: 768px）
5. **プレースホルダー画像**: https://picsum.photos/幅/高さ

## 出力形式（JSONのみ）
{{
  "html": "<!DOCTYPE html>...",
  "css": "/* 全てのCSS */",
  "js": "// 必要なJS"
}}
"""
```

### 4.4 replicator_runner.py の修正

#### 修正箇所1: 初期化

```python
class ReplicatorRunner:
    def __init__(self, db_session):
        self.db_session = db_session
        self.scraper = SiteScraper()
        self.generator = ClaudeGenerator()
        self.verifier = Verifier()

        # 🆕 画像生成器の追加
        self.image_generator = ImageGeneratorFactory.create(
            provider=settings.IMAGE_GENERATOR
        )
        # 🆕 デザイン抽出器の追加（オプション）
        self.design_extractor = DesignExtractor()
```

#### 修正箇所2: _get_job メソッドの追加

```python
async def _get_job(self, job_id: str) -> ReplicationJobModel:
    """
    ジョブをデータベースから取得

    Args:
        job_id: ジョブID

    Returns:
        ReplicationJobModel インスタンス

    Raises:
        ValueError: ジョブが見つからない場合
    """
    from sqlalchemy import select

    stmt = select(ReplicationJobModel).where(
        ReplicationJobModel.id == job_id
    )
    result = await self.db_session.execute(stmt)
    job = result.scalar_one_or_none()

    if not job:
        raise ValueError(f"Job not found: {job_id}")

    return job
```

#### 修正箇所3: _execute メソッドの修正

```python
async def _execute(self, job_id: str):
    """ジョブ実行の本体"""
    logger.info(f"Starting replication job: {job_id}")

    try:
        # 🆕 ジョブ情報の取得
        job = await self._get_job(job_id)

        # 🆕 生成モードの判定
        if job.screenshot_path and os.path.exists(job.screenshot_path):
            # モードA: 画像ベース生成（優先）
            logger.info(f"Using image-based generation: {job.screenshot_path}")
            await self._update_status(job_id, ReplicationStatus.GENERATING)
            generated_code = await self._generate_from_image(
                job_id, job.screenshot_path
            )
        else:
            # モードB: URLベース生成（既存ロジック）
            logger.info(f"Using URL-based generation: {job.source_url}")

            # Phase 1: スクレイピング
            await self._update_status(job_id, ReplicationStatus.SCRAPING)
            scraped_data = await self._scrape(job_id)

            # Phase 2: 初回生成
            await self._update_status(job_id, ReplicationStatus.GENERATING)
            generated_code = await self._generate(job_id, scraped_data)

        # ファイル保存
        output_dir = await self._save_files(job_id, generated_code)

        # Phase 3: 検証ループ（最大3回）
        source_url = job.source_url
        html_path = os.path.join(output_dir, "index.html")

        for iteration in range(1, MAX_ITERATIONS + 1):
            status = getattr(ReplicationStatus, f"VERIFYING_{iteration}")
            await self._update_status(job_id, status)

            verification = await self.verifier.verify(
                source_url, html_path, iteration
            )

            similarity = verification["similarity_score"]
            await self._update_similarity(job_id, similarity)

            logger.info(f"Iteration {iteration}: similarity={similarity}%")

            # 閾値を超えたら完了
            if similarity >= SIMILARITY_THRESHOLD:
                logger.info(f"Similarity threshold reached: {similarity}%")
                break

            # 最終イテレーションでなければ修正
            if iteration < MAX_ITERATIONS:
                await self._update_status(job_id, ReplicationStatus.GENERATING)
                generated_code = await self.generator.refine(
                    generated_code,
                    similarity,
                    verification["diff_report"]
                )
                await self._save_files(job_id, generated_code)

        # 完了
        await self._update_status(job_id, ReplicationStatus.COMPLETED)
        logger.info(f"Replication job completed: {job_id}")

    except (ScrapingError, GenerationError, VerificationError) as e:
        logger.error(f"Replication job failed: {job_id} - {e}")
        await self._update_status(job_id, ReplicationStatus.FAILED, str(e))
    except Exception as e:
        logger.exception(f"Unexpected error in replication job: {job_id}")
        await self._update_status(job_id, ReplicationStatus.FAILED, str(e))
```

#### 修正箇所4: _generate_from_image メソッドの追加

```python
async def _generate_from_image(
    self,
    job_id: str,
    image_path: str
) -> dict:
    """
    画像から直接コードを生成

    Args:
        job_id: ジョブID
        image_path: スクリーンショット画像パス

    Returns:
        {"html": "...", "css": "...", "js": "..."}
    """
    logger.info(f"Generating from image: {image_path}")

    # 画像サイズをログ出力
    from PIL import Image
    img = Image.open(image_path)
    width, height = img.size
    img.close()
    logger.info(f"Image size: {width}x{height} (aspect ratio: {height/width:.2f})")

    # デザイン抽出（オプション）
    design_tokens = None
    if hasattr(self, 'design_extractor'):
        try:
            design_tokens = await self.design_extractor.extract_from_image(image_path)
            logger.info(f"Design tokens extracted: {len(design_tokens.get('colors', []))} colors, {len(design_tokens.get('fonts', []))} fonts")
        except Exception as e:
            logger.warning(f"Design extraction failed: {e}")

    # 画像から生成
    generated_code = await self.image_generator.generate_from_image(
        image_path=image_path,
        design_tokens=design_tokens
    )

    logger.info(f"Generated from image: HTML={len(generated_code.get('html', ''))} chars, CSS={len(generated_code.get('css', ''))} chars, JS={len(generated_code.get('js', ''))} chars")

    return generated_code
```

### 4.5 config.py の修正

```python
from pydantic_settings import BaseSettings
from typing import Dict


class Settings(BaseSettings):
    # 既存の設定...

    # 🆕 画像生成設定
    IMAGE_GENERATOR: str = "claude"  # "claude" or "gemini"
    ANTHROPIC_API_KEY: str = ""  # Claude API キー
    GEMINI_API_KEY: str = ""  # Gemini API キー（オプション）
    IMAGE_QUALITY: int = 85  # JPEG圧縮品質（50-95）
    MAX_IMAGE_BASE64_SIZE: int = 3_600_000  # Base64最大サイズ（3.6MB）
    GENERATION_TIMEOUT: int = 900  # API呼び出しタイムアウト（秒）

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
```

### 4.6 requirements.txt の修正

```txt
# 既存の依存関係
fastapi==0.104.1
uvicorn[standard]==0.24.0
strawberry-graphql[fastapi]==0.216.0
sqlalchemy==2.0.23
aiosqlite==0.19.0
playwright==1.40.0
pydantic-settings==2.1.0
python-dotenv==1.0.0

# 画像処理（既存）
Pillow==10.1.0
numpy==1.26.2
scipy==1.11.4

# 🆕 画像生成用
anthropic>=0.40.0         # Claude Vision API
scikit-learn>=1.3.0       # K-means（色抽出）
```

### 4.7 schema.py の修正（GraphQL）

```python
# 🆕 ReplicationJob 作成時の入力に screenshot_path を追加

@strawberry.input
class CreateReplicationJobInput:
    source_url: str
    screenshot_path: Optional[str] = None  # 🆕 追加
    output_dir: str

@strawberry.type
class ReplicationJob:
    id: str
    source_url: str
    screenshot_path: Optional[str] = None  # 🆕 追加
    status: str
    current_iteration: int
    similarity_score: Optional[float] = None
    output_dir: str
    # ...
```

---

## 🧪 5. テスト計画

### 5.1 テストケース

#### TC-1: URLベース生成（後方互換性）
```
入力:
  - source_url: "https://example.com"
  - screenshot_path: null

期待結果:
  - 既存のスクレイピングフローが動作
  - エラーなし
  - 検証が実行される
```

#### TC-2: 画像ベース生成（URL + 画像）
```
入力:
  - source_url: "https://citizen.jp/kizashi"
  - screenshot_path: "/Volumes/DB/保存/FireShot*.png"

期待結果:
  - 画像から生成（優先）
  - Base64サイズ: 0.76MB（5MB以内）
  - 全てのコンポーネントが含まれる:
    ✓ ヒーロー
    ✓ 説明文
    ✓ 商品画像4枚
    ✓ フッター
  - HTML行数: 350行以上
  - 検証が実行される（URL使用）
```

#### TC-3: 存在しない画像パス
```
入力:
  - source_url: "https://example.com"
  - screenshot_path: "/invalid/path.png"

期待結果:
  - URLベース生成にフォールバック
  - エラーなし
```

#### TC-4: 非常に大きい画像
```
入力:
  - screenshot_path: "/path/to/1920x10000px.png"

期待結果:
  - 段階的圧縮が動作
  - 最終的に5MB以内に収まる
  - エラーなし
```

### 5.2 検証項目

| 項目 | 検証方法 | 判定基準 |
|-----|---------|---------|
| **画像サイズチェック** | ログでBase64サイズ確認 | 5MB以内 |
| **圧縮品質** | ブラウザで目視確認 | 画質劣化なし |
| **コンポーネント完全性** | HTML行数とセクション数 | 350行以上、全セクション含む |
| **ヒーロー高さルール** | DevToolsでCSS確認 | PC: 80vh, Mobile: 100vh |
| **生成時間** | ログでタイムスタンプ確認 | 3分以内 |
| **後方互換性** | URL入力のみでテスト | 既存フロー動作 |
| **エラーハンドリング** | 無効な入力でテスト | エラーメッセージ適切 |
| **検証** | 類似度スコア確認 | 95%以上 |

### 5.3 テスト手順

```bash
# 1. 依存関係のインストール
cd backend
pip install -r requirements.txt

# 2. 環境変数の設定
cat > .env << EOF
ANTHROPIC_API_KEY=sk-ant-...
IMAGE_GENERATOR=claude
IMAGE_QUALITY=85
MAX_IMAGE_BASE64_SIZE=3600000
EOF

# 3. データベースマイグレーション
# （SQLite の場合は手動で ALTER TABLE）
sqlite3 food_connection.db "ALTER TABLE replication_jobs ADD COLUMN screenshot_path VARCHAR(500);"

# 4. サーバー起動
cd ..
./start.sh

# 5. テストケース実行（TC-2: 画像ベース生成）
# GraphQL mutation:
# mutation {
#   createReplicationJob(input: {
#     source_url: "https://citizen.jp/kizashi"
#     screenshot_path: "/Volumes/DB/保存/FireShot Capture 009 - KIZASHI Collection - CITIZEN シチズン時計 - [citizen.jp].png"
#     output_dir: "test_image_based_v2_revised"
#   }) {
#     id
#     status
#   }
# }

# 6. 結果確認
open /path/to/output/test_image_based_v2_revised/index.html

# 7. ログ確認
tail -100 backend/app/logs/app.log | grep -E "(Image size|Base64|Compressed|Using image-based)"

# 8. HTML行数確認
wc -l /path/to/output/test_image_based_v2_revised/index.html
# 期待: 350行以上
```

---

## ⚠️ 6. リスク評価

### 6.1 リスク一覧

| リスク | 発生確率 | 影響度 | 対策 |
|--------|---------|--------|------|
| **マイグレーション失敗** | 低 | 高 | バックアップ、ロールバック手順 |
| **API呼び出し失敗** | 中 | 高 | リトライロジック、詳細エラーログ、タイムアウト処理 |
| **超巨大画像で5MB超過** | 低 | 中 | 段階的圧縮とスケーリング |
| **生成品質の低下** | 中 | 中 | プロンプト改善、デザイントークン活用 |
| **後方互換性の破壊** | 低 | 高 | 既存のURLベース生成を残す、徹底的なテスト |
| **検証失敗** | 中 | 中 | リトライ、手動検証へのフォールバック |
| **依存関係の競合** | 低 | 中 | requirements.txtで明示的にバージョン指定 |
| **メモリ不足** | 低 | 中 | 画像サイズ制限、スケーリング |

### 6.2 ロールバック手順

```bash
# 1. データベースロールバック
sqlite3 food_connection.db "ALTER TABLE replication_jobs DROP COLUMN screenshot_path;"

# 2. 新規ファイルを削除
rm backend/app/services/replicator/base_image_generator.py
rm backend/app/services/replicator/claude_image_generator.py
rm backend/app/services/replicator/gemini_image_generator.py
rm backend/app/services/replicator/image_generator.py
rm backend/app/services/replicator/design_extractor.py

# 3. 修正ファイルを元に戻す
git checkout backend/app/services/replicator_runner.py
git checkout backend/app/config.py
git checkout backend/app/models.py
git checkout backend/app/schema.py
git checkout backend/app/services/replicator/__init__.py
git checkout backend/requirements.txt

# 4. サーバー再起動
./start.sh
```

---

## 📊 7. 期待される効果

### 7.1 定量的効果

| 項目 | Before（URL） | After（URL+画像） | 改善 |
|-----|--------------|------------------|------|
| **入力方式** | URL必須 | URL + 画像（オプション） | 柔軟性向上 |
| **生成精度** | 中（スクレイピング） | 高（実際の見た目） | +30% |
| **コンポーネント完全性** | 80%（動的要素欠落） | 100%（全て見える） | +20% |
| **生成時間** | 2-3分（スクレイピング+生成） | 1-2分（生成のみ） | -33% |
| **Base64サイズ** | N/A | 0.76MB（予測） | - |
| **HTMLサイズ** | 可変 | 350行以上（予測） | - |

### 7.2 定性的効果

| 効果 | 説明 |
|-----|------|
| **柔軟性向上** | URL + 画像の両方を活用可能 |
| **精度向上** | 実際の見た目を完全に再現 |
| **動的コンテンツ対応** | JavaScriptで生成されたコンテンツも再現可能 |
| **後方互換性** | 既存のURLベース生成も引き続き使用可能 |
| **デバッグ容易性** | 画像を見れば問題が明確 |
| **段階的移行** | 既存システムを壊さずに新機能を追加 |

---

## ✅ 8. 実装手順

### 8.1 フェーズ0: 準備とバックアップ（10分）

**タスク:**
1. 現在のデータベースをバックアップ
   ```bash
   cp food_connection.db food_connection.db.backup
   ```
2. Git でバックアップコミット作成
   ```bash
   git add .
   git commit -m "Backup before image-based generation v2.1"
   ```
3. 環境変数の確認
   ```bash
   cat .env
   # ANTHROPIC_API_KEY が設定されているか確認
   ```

### 8.2 フェーズ1: データベースマイグレーション（15分）

**タスク:**
1. `models.py` に screenshot_path フィールド追加
2. マイグレーションスクリプト作成
   ```sql
   ALTER TABLE replication_jobs
   ADD COLUMN screenshot_path VARCHAR(500) NULL;
   ```
3. マイグレーション実行
   ```bash
   sqlite3 food_connection.db < migration.sql
   ```
4. 検証
   ```bash
   sqlite3 food_connection.db "PRAGMA table_info(replication_jobs);"
   ```

**成果物:**
- ✅ models.py（修正）
- ✅ データベーススキーマ更新
- ✅ マイグレーションスクリプト

### 8.3 フェーズ2: 基盤整備（30分）

**タスク:**
1. `base_image_generator.py` の作成
   - バックアップコミット `2add71d` から復元
   - 圧縮ロジックの確認（既にテスト済み）
   - Base64サイズ検証の確認

2. `config.py` の修正
   - IMAGE_GENERATOR, ANTHROPIC_API_KEY 設定追加

3. `requirements.txt` の更新
   - anthropic, scikit-learn 追加
   - インストール
   ```bash
   pip install anthropic>=0.40.0 scikit-learn>=1.3.0
   ```

**成果物:**
- ✅ base_image_generator.py（550行）
- ✅ config.py（修正）
- ✅ requirements.txt（修正）

### 8.4 フェーズ3: Claude実装（40分）

**タスク:**
1. `claude_image_generator.py` の作成
   - バックアップから復元
   - プロンプトの改善（ヒーロー高さルール追加）
   - エラーハンドリング強化

2. `design_extractor.py` の作成
   - HTMLからの抽出
   - 画像からの抽出（K-means）

3. `image_generator.py` の作成
   - ファクトリパターン

4. `__init__.py` の更新
   - ImageGeneratorFactory エクスポート

**成果物:**
- ✅ claude_image_generator.py（350行）
- ✅ design_extractor.py（150行）
- ✅ image_generator.py（50行）
- ✅ __init__.py（修正）

### 8.5 フェーズ4: 統合（40分）

**タスク:**
1. `replicator_runner.py` の修正
   - __init__ に image_generator, design_extractor 追加
   - `_get_job` メソッド追加
   - `_execute` メソッド修正（モード判定）
   - `_generate_from_image` メソッド追加

2. `schema.py` の修正
   - CreateReplicationJobInput に screenshot_path 追加
   - ReplicationJob に screenshot_path 追加

3. 構文チェック
   ```bash
   python3 -m py_compile backend/app/services/replicator_runner.py
   python3 -m py_compile backend/app/models.py
   python3 -m py_compile backend/app/schema.py
   ```

**成果物:**
- ✅ replicator_runner.py（修正）
- ✅ schema.py（修正）
- ✅ 構文チェック完了

### 8.6 フェーズ5: テストと検証（40分）

**タスク:**
1. サーバー起動
   ```bash
   ./start.sh
   ```
2. テストケース実行（TC-1: URLベース）
   - 後方互換性確認
3. テストケース実行（TC-2: URL+画像）
   - 画像ベース生成確認
4. 結果確認
   - HTML行数、コンポーネント完全性
   - ログ確認
   - ブラウザで確認
5. 問題があればデバッグ

**成果物:**
- ✅ テスト結果レポート
- ✅ 生成されたHTML/CSS/JS
- ✅ ログファイル

### 8.7 フェーズ6: ドキュメントとコミット（15分）

**タスク:**
1. README更新（画像ベース生成の説明）
2. 環境変数ガイド（.env.example更新）
3. Git コミット
   ```bash
   git add .
   git commit -m "Add image-based generation (hybrid approach)

   - Add screenshot_path to ReplicationJobModel
   - Implement Claude Vision API integration
   - Add image compression and Base64 encoding
   - Support both URL-based and image-based generation
   - Maintain backward compatibility
   - Add design token extraction

   Files added:
   - backend/app/services/replicator/base_image_generator.py
   - backend/app/services/replicator/claude_image_generator.py
   - backend/app/services/replicator/gemini_image_generator.py
   - backend/app/services/replicator/image_generator.py
   - backend/app/services/replicator/design_extractor.py

   Files modified:
   - backend/app/models.py (add screenshot_path)
   - backend/app/services/replicator_runner.py (add image generation flow)
   - backend/app/config.py (add IMAGE_GENERATOR settings)
   - backend/requirements.txt (add anthropic, scikit-learn)
   - backend/app/schema.py (add screenshot_path to GraphQL)
   "
   ```

**成果物:**
- ✅ README.md（更新）
- ✅ .env.example（更新）
- ✅ Git コミット

**合計所要時間**: 約3時間

---

## 📈 9. 成功基準

### 9.1 必須条件（Must Have）

- [ ] データベースマイグレーション成功
- [ ] 973x5000px 画像が Base64 で 0.76MB（5MB以内）
- [ ] URLベース生成が引き続き動作（後方互換性）
- [ ] URL+画像で画像ベース生成が動作
- [ ] 生成された HTML に全てのコンポーネントが含まれる
  - [ ] ヒーローセクション
  - [ ] 説明文
  - [ ] 商品画像4枚
  - [ ] フッター
- [ ] 検証が正常に動作
- [ ] エラーなく生成完了

### 9.2 推奨条件（Should Have）

- [ ] HTML行数が 350行以上
- [ ] 生成時間が 3分以内
- [ ] ヒーロー高さルール（80vh / 100vh）が適用される
- [ ] デザイン要素が正確に抽出される
- [ ] ログが適切に出力される

### 9.3 オプション条件（Nice to Have）

- [ ] 動画入力対応（JavaScript生成）
- [ ] Gemini API 対応
- [ ] ユニットテスト作成

---

## 🔍 10. 技術的詳細

### 10.1 ファイル構成（実装後）

```
backend/app/services/replicator/
├── __init__.py                  # SiteScraper, ClaudeGenerator, Verifier, ImageGeneratorFactory
├── site_scraper.py              # 既存（URLベース）
├── claude_generator.py          # 既存（Claude CLI）
├── verifier.py                  # 既存
├── image_comparator.py          # 既存
├── base_image_generator.py      # 🆕 新規（基底クラス）
├── claude_image_generator.py    # 🆕 新規（Vision API）
├── gemini_image_generator.py    # 🆕 新規（オプション）
├── image_generator.py           # 🆕 新規（ファクトリ）
└── design_extractor.py          # 🆕 新規（デザイン抽出）
```

### 10.2 データフロー

```
フロントエンド（GraphQL mutation）
  ↓
  createReplicationJob(
    source_url: "https://example.com",
    screenshot_path: "/path/to/image.png"
  )
  ↓
ReplicationJobModel 作成
  ↓
ReplicatorRunner._execute(job_id)
  ↓
_get_job(job_id) → job
  ↓
screenshot_path あり？
  ↓ YES
_generate_from_image(job_id, screenshot_path)
  ├── Image.open(screenshot_path)
  ├── design_extractor.extract_from_image()
  └── image_generator.generate_from_image()
      ├── _encode_image_to_base64() → 0.76MB
      └── _call_api_with_image() → Claude Vision API
          └── {"html": "...", "css": "...", "js": "..."}
  ↓
_save_files(job_id, generated_code)
  ↓
verifier.verify(source_url, html_path)
  ↓
完了
```

### 10.3 環境変数

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...           # Claude API キー（必須）
GEMINI_API_KEY=xxx                      # Gemini API キー（オプション）
IMAGE_GENERATOR=claude                  # "claude" or "gemini"
IMAGE_QUALITY=85                        # JPEG圧縮品質（50-95）
MAX_IMAGE_BASE64_SIZE=3600000          # Base64最大サイズ（バイト）
GENERATION_TIMEOUT=900                  # タイムアウト（秒）
```

### 10.4 ログ出力例

```
2026-01-27 13:00:00 INFO Starting replication job: abc-123-def
2026-01-27 13:00:00 INFO Using image-based generation: /Volumes/DB/保存/FireShot*.png
2026-01-27 13:00:01 INFO Image size: 973x5000 (aspect ratio: 5.14)
2026-01-27 13:00:02 INFO JPEG size: binary=0.57MB, base64=0.76MB (OK)
2026-01-27 13:00:02 INFO Design tokens extracted: 10 colors, 3 fonts
2026-01-27 13:00:03 INFO Calling Claude Vision API...
2026-01-27 13:01:48 INFO Claude API response received (length=25432)
2026-01-27 13:01:49 INFO Generated from image: HTML=12543 chars, CSS=8921 chars, JS=3968 chars
2026-01-27 13:01:50 INFO Files saved to: /output/abc-123-def
2026-01-27 13:01:51 INFO Iteration 1: similarity=97.5%
2026-01-27 13:01:51 INFO Similarity threshold reached: 97.5%
2026-01-27 13:01:51 INFO Replication job completed: abc-123-def
```

---

## 📅 11. スケジュール

| フェーズ | 作業内容 | 所要時間 | 担当 |
|---------|---------|---------|------|
| **準備** | バックアップ、環境確認 | 10分 | 手動 |
| **フェーズ1** | データベースマイグレーション | 15分 | serena-expert |
| **フェーズ2** | 基盤整備（base, config, requirements） | 30分 | serena-expert |
| **フェーズ3** | Claude実装（claude, design, factory） | 40分 | serena-expert |
| **フェーズ4** | 統合（replicator_runner, schema） | 40分 | serena-expert |
| **フェーズ5** | テストと検証 | 40分 | 手動/自動 |
| **フェーズ6** | ドキュメントとコミット | 15分 | serena-expert |
| **合計** | | **3時間** | |

---

## 🎯 12. 次のステップ

### 12.1 承認待ち
- [ ] この計画書のレビュー
- [ ] ユーザー承認

### 12.2 実装開始
承認後、以下の順序で進めます：
1. ✅ フェーズ0: 準備とバックアップ
2. ✅ フェーズ1: データベースマイグレーション
3. ✅ フェーズ2: 基盤整備
4. ✅ フェーズ3: Claude実装
5. ✅ フェーズ4: 統合
6. ✅ フェーズ5: テストと検証
7. ✅ フェーズ6: ドキュメントとコミット

各フェーズ完了後に進捗報告します。

---

## ✍️ 署名

**計画作成者**: Claude Sonnet 4.5
**バージョン**: 2.1（徹底レビュー後修正版）
**作成日**: 2026-01-27
**レビュー**: 完了（重大な設計ミスを修正）
**承認待ち**: ユーザー確認中

---

## 📌 重要な変更点まとめ

### v2.0 → v2.1 の主な修正

1. **ハイブリッドアプローチの採用**
   - URL + 画像の両方を使用
   - source_url は必須のまま（後方互換性）
   - screenshot_path はオプション

2. **データベーススキーマ変更**
   - screenshot_path フィールドを追加
   - マイグレーションが必要

3. **検証方法の明確化**
   - URL を使用して検証（既存ロジック）
   - 画像ベース生成でも検証可能

4. **_get_job メソッドの追加**
   - データベースからジョブを取得
   - 実装を明記

5. **依存関係の明確化**
   - anthropic, scikit-learn を requirements.txt に追加
   - config.py に設定を追加

6. **GraphQL スキーマ修正**
   - CreateReplicationJobInput に screenshot_path 追加
   - ReplicationJob に screenshot_path 追加

**この修正版計画で実装を開始してよろしいですか？**

承認いただければ、serena-expertエージェントに各フェーズを委託して、ステップバイステップで実装を進めます。
