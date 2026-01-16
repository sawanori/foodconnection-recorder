# Food Connection Recorder

Web実績ページ自動巡回・録画システム

Food Connectionの実績ページを自動的に巡回し、詳細ページの動画を録画するシステムです。バックエンドはFastAPI + GraphQL、フロントエンドはNext.js + TypeScriptで構築されています。

## 必要要件

- Python 3.11以上
- Node.js 18以上
- npm または yarn

## プロジェクト構成

```
food-connection-recorder/
├── backend/           # FastAPI + GraphQL バックエンド
│   ├── app/
│   │   ├── main.py           # FastAPIアプリケーション
│   │   ├── schema.py         # GraphQLスキーマ定義
│   │   ├── models.py         # データベースモデル
│   │   ├── database.py       # データベース接続設定
│   │   ├── config.py         # 設定管理
│   │   └── services/         # ビジネスロジック
│   │       ├── job_runner.py # ジョブ実行管理
│   │       ├── scraper.py    # Webスクレイピング
│   │       ├── recorder.py   # 動画録画
│   │       ├── pubsub.py     # リアルタイム通信
│   │       └── errors.py     # エラー定義
│   ├── run.py                # サーバー起動スクリプト
│   └── requirements.txt      # Python依存パッケージ
├── frontend/          # Next.js フロントエンド
│   ├── src/
│   │   ├── app/              # Next.js App Router
│   │   ├── components/       # Reactコンポーネント
│   │   └── lib/              # GraphQLクライアント設定
│   └── package.json          # Node.js依存パッケージ
└── README.md
```

## セットアップ手順

### 1. バックエンドのセットアップ

#### 1-1. 依存パッケージのインストール

```bash
cd backend
pip install -r requirements.txt
```

#### 1-2. Playwrightブラウザのインストール

```bash
playwright install chromium
```

#### 1-3. 環境変数の設定（オプション）

必要に応じて `.env` ファイルを作成し、設定をカスタマイズできます。

```bash
# .env の例
DATABASE_URL=sqlite+aiosqlite:///./food_recorder.db
FRONTEND_URL=http://localhost:3000
MAX_RETRIES=3
RETRY_BACKOFF_BASE=2
```

デフォルト設定で動作するため、`.env` ファイルは必須ではありません。

#### 1-4. バックエンドの起動

```bash
python run.py
```

サーバーが起動すると、以下のエンドポイントが利用可能になります。

- GraphQL API: http://localhost:8000/graphql
- GraphiQL（開発用UI）: http://localhost:8000/graphql
- ヘルスチェック: http://localhost:8000/health

### 2. フロントエンドのセットアップ

#### 2-1. 依存パッケージのインストール

```bash
cd frontend
npm install
```

または yarn を使用:

```bash
yarn install
```

#### 2-2. フロントエンドの起動

```bash
npm run dev
```

または yarn を使用:

```bash
yarn dev
```

ブラウザで http://localhost:3000 にアクセスします。

## 使用方法

### 基本的な使い方

1. ブラウザで http://localhost:3000 を開く
2. 「新規ジョブ作成」フォームで以下を入力:
   - 開始ページ番号（例: 1）
   - 終了ページ番号（例: 3）
   - 保存先ディレクトリ名（例: output_20260116）
     - 英数字、ハイフン、アンダースコアのみ使用可能
3. 「ジョブを作成」ボタンをクリック
4. ジョブ一覧に作成されたジョブが表示される
5. 「開始」ボタンをクリックしてジョブを実行
6. リアルタイムで進捗が更新される
7. 録画された動画は `backend/outputs/{保存先ディレクトリ名}/` に保存される

### ジョブのステータス

- **PENDING**: 作成済み、未実行
- **RUNNING**: 実行中
- **COMPLETED**: 正常完了
- **FAILED**: エラーにより失敗

### レコードのステータス

- **PENDING**: 処理待ち
- **PROCESSING**: 処理中
- **SUCCESS**: 正常完了
- **FAILED**: 失敗（最大リトライ回数到達）
- **SKIPPED**: スキップ（必須要素未検出）

## 機能

### 実装済み機能

1. **ジョブ管理**
   - ジョブの作成、開始、停止
   - 複数ジョブの並列管理
   - ジョブステータスの追跡

2. **URL収集**
   - 一覧ページから詳細ページURLを自動抽出
   - 指定ページ範囲の巡回
   - 重複URL除去

3. **データ抽出**
   - 店舗名の抽出とサニタイズ
   - 店舗URLの抽出
   - エラーハンドリングとリトライ

4. **動画録画**
   - 詳細ページの自動スクロール録画
   - 店舗名ベースのファイル命名
   - ディレクトリ自動作成

5. **リアルタイム更新**
   - GraphQL Subscriptionによる進捗配信
   - レコード単位の状態更新
   - WebSocketベースの双方向通信

6. **エラー管理**
   - 指数バックオフによるリトライ
   - エラー種別による処理分岐
   - エラーメッセージの記録

### GraphQL API

#### クエリ

```graphql
# 全ジョブ取得
query {
  jobs {
    id
    startPage
    endPage
    outputDir
    status
    totalItems
    processedItems
    createdAt
  }
}

# 特定ジョブ取得
query {
  job(id: "job-id") {
    id
    status
  }
}

# レコード一覧取得
query {
  records(jobId: "job-id") {
    id
    shopName
    status
    errorMessage
  }
}
```

#### ミューテーション

```graphql
# ジョブ作成
mutation {
  createJob(input: {
    startPage: 1
    endPage: 3
    outputDir: "output_test"
  }) {
    id
    status
  }
}

# ジョブ開始
mutation {
  startJob(id: "job-id") {
    id
    status
  }
}

# レコード再試行
mutation {
  retryRecord(id: "record-id") {
    id
    status
    retryCount
  }
}
```

#### サブスクリプション

```graphql
# ジョブ進捗購読
subscription {
  jobProgress(jobId: "job-id") {
    jobId
    status
    totalItems
    processedItems
  }
}

# レコード更新購読
subscription {
  recordUpdate(jobId: "job-id") {
    id
    shopName
    status
  }
}
```

## トラブルシューティング

### バックエンドが起動しない

- Python 3.11以上がインストールされているか確認
- `pip install -r requirements.txt` が正常に完了したか確認
- `playwright install chromium` が正常に完了したか確認

### フロントエンドが起動しない

- Node.js 18以上がインストールされているか確認
- `npm install` が正常に完了したか確認
- ポート3000が他のプロセスで使用されていないか確認

### 録画が失敗する

- ネットワーク接続を確認
- 対象サイトがアクセス可能か確認
- `outputs/` ディレクトリの書き込み権限を確認

### GraphQLサブスクリプションが動作しない

- バックエンドとフロントエンドの両方が起動しているか確認
- ブラウザのコンソールでエラーを確認
- WebSocket接続が確立されているか確認

## 開発

### テストの実行

データベース接続とGraphQLエンドポイントの動作確認:

```bash
cd backend
python test_connection.py
```

### コード構成

- **Phase 1**: プロジェクト基盤（データベース、GraphQL API）
- **Phase 2**: URL収集機能
- **Phase 3**: データ抽出・録画機能
- **Phase 4**: エラーハンドリング・リトライ
- **Phase 5**: フロントエンド実装
- **Phase 6**: 統合・テスト・ドキュメント

## ライセンス

このプロジェクトは内部使用目的で作成されています。
