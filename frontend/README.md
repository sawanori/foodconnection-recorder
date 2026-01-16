# Food Connection Recorder - Frontend

Web実績ページ自動巡回・録画システムのフロントエンド

## 技術スタック

- **Framework**: Next.js 14 (App Router)
- **Language**: TypeScript
- **GraphQL Client**: Apollo Client
- **UI Framework**: Tailwind CSS
- **Real-time**: GraphQL Subscriptions (WebSocket)

## セットアップ

### 依存関係のインストール

```bash
npm install
```

### 環境変数設定

`.env.local` ファイルを作成:

```env
NEXT_PUBLIC_GRAPHQL_HTTP_URL=http://localhost:8000/graphql
NEXT_PUBLIC_GRAPHQL_WS_URL=ws://localhost:8000/graphql
```

### 開発サーバー起動

```bash
npm run dev
```

ブラウザで http://localhost:3000 にアクセス

### ビルド

```bash
npm run build
npm start
```

## コンポーネント構成

### JobForm
ジョブの設定と実行を行うフォームコンポーネント

- 開始/終了ページ番号の入力
- 出力ディレクトリ名の入力（英数字・ハイフン・アンダースコアのみ）
- バリデーション機能
- 実行中の無効化

### ProgressBar
ジョブの進捗状況をリアルタイム表示

- プログレスバー（パーセンテージ表示）
- 処理済み/総数の表示
- 現在処理中の店舗名表示
- ステータス表示（待機中/実行中/完了/失敗）

### RecordTable
処理結果の一覧表示

- レコードの一覧表示（#, 店舗名, URL, ステータス, 動画, エラー）
- ステータスフィルタ機能
- ステータスに応じた色分け
- 動画ダウンロードリンク
- リアルタイム更新

### ErrorLog
エラー・失敗レコードの管理

- 失敗/スキップレコードの一覧
- エラーメッセージ詳細表示
- 個別再実行機能
- リトライ回数表示

## GraphQL操作

### Queries
- `GET_JOBS`: 全ジョブ取得
- `GET_JOB`: 特定ジョブ取得
- `GET_RECORDS`: レコード一覧取得

### Mutations
- `CREATE_JOB`: ジョブ作成
- `START_JOB`: ジョブ開始
- `STOP_JOB`: ジョブ停止
- `RETRY_RECORD`: レコード再実行

### Subscriptions
- `JOB_PROGRESS_SUBSCRIPTION`: ジョブ進捗のリアルタイム配信
- `RECORD_UPDATE_SUBSCRIPTION`: レコード更新のリアルタイム配信

## ディレクトリ構造

```
frontend/
├── app/
│   ├── globals.css      # グローバルCSS
│   ├── layout.tsx       # ルートレイアウト
│   ├── page.tsx         # メインページ
│   └── providers.tsx    # Apollo Provider
├── components/
│   ├── ErrorLog.tsx     # エラーログ
│   ├── JobForm.tsx      # ジョブフォーム
│   ├── ProgressBar.tsx  # 進捗バー
│   └── RecordTable.tsx  # 結果テーブル
├── lib/
│   ├── apollo.ts        # Apollo Client設定
│   └── graphql/
│       ├── mutations.ts
│       ├── queries.ts
│       └── subscriptions.ts
└── types/
    └── index.ts         # TypeScript型定義
```

## 使用方法

1. バックエンドサーバーを起動
2. フロントエンドサーバーを起動（`npm run dev`）
3. ブラウザでアクセス
4. ジョブフォームで設定を入力
5. 「実行」ボタンをクリック
6. 進捗状況をリアルタイムで確認
7. 完了後、結果一覧とエラーログを確認

## 注意事項

- バックエンドが起動していないと動作しません
- WebSocket接続が必要です（GraphQL Subscriptions用）
- 出力ディレクトリ名は英数字・ハイフン・アンダースコアのみ使用可能

## トラブルシューティング

### WebSocket接続エラー
- バックエンドサーバーが起動しているか確認
- `.env.local` のWebSocket URLが正しいか確認
- CORSエラーの場合、バックエンドのCORS設定を確認

### データが表示されない
- GraphQLエンドポイントが正しいか確認
- ブラウザのコンソールでエラーを確認
- Networkタブでリクエストを確認

## 開発

### Lintチェック
```bash
npm run lint
```

### 型チェック
```bash
npx tsc --noEmit
```

## ライセンス

プロジェクト内部使用
