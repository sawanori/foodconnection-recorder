"""
画像比較ユーティリティ

2つのスクリーンショットをピクセル単位で比較します。
"""
import io
import logging
from typing import Dict, List, Any
from PIL import Image
import numpy as np

logger = logging.getLogger(__name__)


class ImageComparator:
    """画像比較クラス"""

    def __init__(self, diff_threshold: int = 30):
        """
        Args:
            diff_threshold: 差分閾値（0-255）
        """
        self.diff_threshold = diff_threshold

    def compare(
        self,
        img1_bytes: bytes,
        img2_bytes: bytes
    ) -> Dict[str, Any]:
        """
        2つの画像をピクセル単位で比較

        Args:
            img1_bytes: 画像1のバイトデータ
            img2_bytes: 画像2のバイトデータ

        Returns:
            {
                "similarity": float (0-100),
                "diff_pixels": int,
                "diff_regions": list,
                "dimensions": dict
            }
        """
        # 画像を開く
        img1 = Image.open(io.BytesIO(img1_bytes)).convert('RGB')
        img2 = Image.open(io.BytesIO(img2_bytes)).convert('RGB')

        logger.info(f"Comparing images: {img1.size} vs {img2.size}")

        # サイズを揃える（小さい方に合わせる）
        min_width = min(img1.width, img2.width)
        min_height = min(img1.height, img2.height)

        if img1.size != (min_width, min_height):
            img1 = img1.crop((0, 0, min_width, min_height))
        if img2.size != (min_width, min_height):
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
        diff_mask = diff_gray > self.diff_threshold
        diff_pixels = int(np.sum(diff_mask))

        # 差分領域をバウンディングボックスで表現
        diff_regions = self._find_diff_regions(diff_mask)

        result = {
            "similarity": round(similarity, 2),
            "diff_pixels": diff_pixels,
            "diff_regions": diff_regions,
            "dimensions": {
                "width": min_width,
                "height": min_height
            }
        }

        logger.info(f"Comparison result: similarity={result['similarity']}%, diff_pixels={diff_pixels}")
        return result

    def _find_diff_regions(self, diff_mask: np.ndarray) -> List[Dict[str, int]]:
        """
        差分マスクからバウンディングボックスを検出

        Args:
            diff_mask: 差分マスク（2D bool配列）

        Returns:
            差分領域のリスト
        """
        try:
            from scipy import ndimage
        except ImportError:
            logger.warning("scipy not available, skipping region detection")
            return []

        # ラベリング
        labeled, num_features = ndimage.label(diff_mask)

        boxes = []
        for i in range(1, num_features + 1):
            positions = np.where(labeled == i)
            if len(positions[0]) > 100:  # 小さすぎる領域は無視
                y_min, y_max = int(positions[0].min()), int(positions[0].max())
                x_min, x_max = int(positions[1].min()), int(positions[1].max())
                boxes.append({
                    "x": x_min,
                    "y": y_min,
                    "width": x_max - x_min,
                    "height": y_max - y_min,
                    "pixels": int(np.sum(labeled == i))
                })

        # 大きい順にソート、最大10領域
        boxes.sort(key=lambda b: b["pixels"], reverse=True)
        return boxes[:10]

    def generate_diff_report(
        self,
        comparison: Dict[str, Any],
        iteration: int
    ) -> str:
        """
        差分レポートを生成

        Args:
            comparison: compare() の戻り値
            iteration: 検証イテレーション番号

        Returns:
            差分レポート文字列
        """
        similarity = comparison["similarity"]
        diff_pixels = comparison["diff_pixels"]
        diff_regions = comparison["diff_regions"]
        dimensions = comparison["dimensions"]

        total_pixels = dimensions["width"] * dimensions["height"]
        diff_percentage = (diff_pixels / total_pixels) * 100 if total_pixels > 0 else 0

        report = f"""## 検証結果 (イテレーション {iteration}/3)

### 概要
- 類似度: {similarity}%
- 差分ピクセル数: {diff_pixels:,} ({diff_percentage:.2f}%)
- 画像サイズ: {dimensions['width']}x{dimensions['height']}px

### 差分領域 ({len(diff_regions)}箇所)
"""
        if diff_regions:
            for i, region in enumerate(diff_regions, 1):
                report += f"- 領域{i}: x={region['x']}, y={region['y']}, "
                report += f"サイズ={region['width']}x{region['height']}px "
                report += f"({region['pixels']:,}px)\n"
        else:
            report += "- 大きな差分領域は検出されませんでした\n"

        # 評価コメント
        report += "\n### 評価\n"
        if similarity >= 95:
            report += "✅ **優秀**: 高い類似度です。微調整のみで完成です。\n"
        elif similarity >= 85:
            report += "✅ **良好**: 概ね再現できています。細部の調整が必要です。\n"
        elif similarity >= 70:
            report += "⚠️ **要改善**: レイアウトや色に違いがあります。修正が必要です。\n"
        else:
            report += "❌ **要大幅修正**: 大きな違いがあります。構造から見直しが必要です。\n"

        # 修正提案
        if diff_regions:
            report += "\n### 修正提案\n"
            for i, region in enumerate(diff_regions[:3], 1):
                y = region['y']
                if y < dimensions['height'] * 0.2:
                    report += f"- 領域{i}: ヘッダー部分を確認してください\n"
                elif y > dimensions['height'] * 0.8:
                    report += f"- 領域{i}: フッター部分を確認してください\n"
                else:
                    report += f"- 領域{i}: メインコンテンツ部分（y={y}付近）を確認してください\n"

        return report
