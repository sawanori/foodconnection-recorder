# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased] - 2026-01-27

### Added

- **画像ベース生成機能**: スクリーンショットから直接Webサイトを生成
  - Claude Vision API (Sonnet 4.5) 統合
  - JPEG圧縮で5MB制限を確実に遵守（実測0.76MB）
  - デザイン要素抽出（色、フォント）
  - ハイブリッドアプローチ（URL + 画像）
  
- **データベーススキーマ更新**:
  - `replication_jobs`テーブルに`screenshot_path`フィールド追加
  - `source_url`フィールド追加（`input_folder`から移行）
  
- **GraphQL API拡張**:
  - `CreateReplicationJobInput`に`screenshot_path`追加
  - `ReplicationJob`型に`screenshot_path`追加
  
- **新規ファイル**:
  - `backend/app/services/replicator/base_image_generator.py` (755行)
  - `backend/app/services/replicator/claude_image_generator.py` (842行)
  - `backend/app/services/replicator/gemini_image_generator.py` (713行)
  - `backend/app/services/replicator/design_extractor.py` (105行)
  - `backend/app/services/replicator/image_generator.py` (545行)
  - `backend/app/services/replicator/multi_section_generator.py` (404行)
  
- **設定追加**:
  - `IMAGE_GENERATOR`: "claude" or "gemini"
  - `ANTHROPIC_API_KEY`: Claude API キー
  - `IMAGE_QUALITY`: JPEG圧縮品質（デフォルト: 85）
  - `MAX_IMAGE_BASE64_SIZE`: Base64最大サイズ（デフォルト: 3.6MB）
  - `GENERATION_TIMEOUT`: タイムアウト（デフォルト: 900秒）

### Changed

- **replicator_runner.py**: 画像ベース生成フローを追加
  - `_get_job()`メソッド追加
  - `_execute()`メソッド修正（モード判定）
  - `_generate_from_image()`メソッド追加
  
- **config.py**: 画像生成設定を追加

- **requirements.txt**: 依存関係追加
  - anthropic>=0.40.0
  - scikit-learn>=1.3.0

### Fixed

- データベーススキーマの整合性問題を解決
  - 古い`input_folder`カラムを削除
  - 新しい`source_url`カラムを追加
  
- 環境変数設定の問題を解決
  - `extra = "ignore"`を追加して未定義の環境変数を許可

### Tests

- 全てのテストが成功（7項目）
  - インポートテスト: ✅
  - データベーススキーマ: ✅
  - GraphQLスキーマ: ✅
  - 画像圧縮テスト: ✅ (0.76MB)
  - GraphQLミューテーション: ✅
  - サーバー起動: ✅
  - 統合テスト: ✅

### Backward Compatibility

- 既存のURLベース生成機能は完全に維持
- `screenshot_path`はオプション（省略可能）
- 既存のAPIは一切変更なし

