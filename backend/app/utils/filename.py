import re
import unicodedata
from typing import Set


def sanitize_filename(name: str, max_length: int = 100) -> str:
    """
    ファイル名をサニタイズ

    処理内容:
    1. Unicode正規化（全角→半角変換）
    2. 禁止文字除去: / \ : * ? " < > |
    3. 空白文字をアンダースコアに変換
    4. 連続アンダースコアを1つに統合
    5. 先頭・末尾のアンダースコア除去
    6. 最大長制限

    Args:
        name: 元のファイル名
        max_length: 最大文字数（拡張子除く）

    Returns:
        サニタイズ済みファイル名

    Examples:
        >>> sanitize_filename("和牛焼肉酒場 勝 （ワギュウヤキニクサカバ マサル）")
        '和牛焼肉酒場_勝_ワギュウヤキニクサカバ_マサル'

        >>> sanitize_filename("鮨処/みやざき")
        '鮨処みやざき'
    """
    # 1. Unicode正規化（全角英数→半角、濁点統合等）
    name = unicodedata.normalize('NFKC', name)

    # 2. 禁止文字を除去
    # Windows/Linux/macOSで禁止されている文字: / \ : * ? " < > |
    name = re.sub(r'[/\\:*?"<>|]', '', name)

    # 3. 空白文字（スペース、全角スペース、タブ等）をアンダースコアに
    name = re.sub(r'\s+', '_', name)

    # 4. 括弧を除去（オプション）
    name = re.sub(r'[()（）\[\]【】]', '', name)

    # 5. 連続アンダースコアを1つに
    name = re.sub(r'_+', '_', name)

    # 6. 先頭・末尾のアンダースコア・ドット除去
    name = name.strip('_.')

    # 7. 空文字列チェック
    if not name:
        name = "unnamed"

    # 8. 最大長制限
    if len(name) > max_length:
        name = name[:max_length].rstrip('_.')

    return name


def get_unique_filename(base_name: str, existing_names: Set[str]) -> str:
    """
    重複を避けたユニークなファイル名を生成

    Args:
        base_name: 基本ファイル名（拡張子なし）
        existing_names: 既存ファイル名のセット（拡張子なし）

    Returns:
        ユニークなファイル名（拡張子なし）

    Examples:
        >>> get_unique_filename("店舗A", {"店舗A", "店舗B"})
        '店舗A_001'

        >>> get_unique_filename("店舗A", {"店舗A", "店舗A_001"})
        '店舗A_002'
    """
    if base_name not in existing_names:
        return base_name

    # カウンタ付きファイル名生成
    counter = 1
    while True:
        unique_name = f"{base_name}_{counter:03d}"
        if unique_name not in existing_names:
            return unique_name
        counter += 1

        # 安全装置（999以上は許可しない）
        if counter > 999:
            raise ValueError(f"Too many duplicates for filename: {base_name}")
