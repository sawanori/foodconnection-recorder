"""
カスタムエラークラス定義
"""


class RecorderError(Exception):
    """録画処理エラーの基底クラス"""
    pass


class NetworkError(RecorderError):
    """ネットワーク関連エラー（DNS解決失敗、接続タイムアウト等）"""
    retryable = True


class TimeoutError(RecorderError):
    """タイムアウトエラー"""
    retryable = True


class ElementNotFoundError(RecorderError):
    """要素未検出エラー（セレクタマッチなし）"""
    retryable = False  # リトライしても解決しない


class FileSystemError(RecorderError):
    """ファイルシステムエラー（保存失敗、権限エラー等）"""
    retryable = True


class PlaywrightError(RecorderError):
    """Playwright実行時エラー"""
    retryable = True
