"""
デザイン抽出サービス

HTML/CSSまたは画像からデザイン要素（色、フォントなど）を抽出します。
"""
import logging
import re
from typing import Dict, List, Set, Tuple
from collections import Counter
from PIL import Image

logger = logging.getLogger(__name__)

class DesignExtractor:
    """デザイン抽出クラス"""

    def extract_from_html(self, html_content: str) -> Dict[str, List[str]]:
        """
        HTMLコンテンツからデザイン要素を抽出
        
        Args:
            html_content: HTMLソースコード
            
        Returns:
            {
                "colors": ["#ffffff", "#000000", ...],
                "fonts": ["Roboto", "Noto Sans JP", ...]
            }
        """
        colors = self._extract_colors(html_content)
        fonts = self._extract_fonts(html_content)
        
        return {
            "colors": list(colors)[:5],  # 上位5つ
            "fonts": list(fonts)[:3]     # 上位3つ
        }

    def extract_from_image(self, image_path: str) -> Dict[str, List[str]]:
        """
        画像から主要な色を抽出
        
        Args:
            image_path: 画像パス
            
        Returns:
            {
                "colors": ["#ffffff", "#000000", ...],
                "fonts": [] # 画像からのフォント抽出は困難なため空
            }
        """
        try:
            img = Image.open(image_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
                
            # 画像を小さくリサイズして処理を高速化
            img.thumbnail((150, 150))
            
            # 色の頻度を計算
            colors = img.getcolors(img.width * img.height)
            
            # 頻度順にソート (count, (r, g, b))
            sorted_colors = sorted(colors, key=lambda x: x[0], reverse=True)
            
            hex_colors = []
            for _, color in sorted_colors:
                hex_c = '#{:02x}{:02x}{:02x}'.format(*color)
                hex_colors.append(hex_c)
                if len(hex_colors) >= 5:
                    break
                    
            return {
                "colors": hex_colors,
                "fonts": []
            }
        except Exception as e:
            logger.error(f"Failed to extract colors from image: {e}")
            return {"colors": [], "fonts": []}

    def _extract_colors(self, content: str) -> Set[str]:
        """テキストからHEXカラーコードを抽出"""
        # HEXカラー (#fff, #ffffff)
        hex_pattern = r'#(?:[0-9a-fA-F]{3}){1,2}(?![0-9a-fA-F])'
        matches = re.findall(hex_pattern, content)
        
        # 頻度順に並べ替え
        counter = Counter([c.lower() for c in matches])
        return [c for c, _ in counter.most_common()]

    def _extract_fonts(self, content: str) -> Set[str]:
        """テキストからフォントファミリーを抽出"""
        # font-family: "Robotp", sans-serif;
        font_pattern = r'font-family:\s*([^;]+);'
        matches = re.findall(font_pattern, content)
        
        fonts = set()
        for match in matches:
            # カンマで分割してクリーンアップ
            families = [f.strip().strip('"\'') for f in match.split(',')]
            for family in families:
                # 一般的なフォールバックフォントは除外しても良いが、一旦含める
                if family.lower() not in ['sans-serif', 'serif', 'monospace', 'inherit']:
                    fonts.add(family)
                    
        return list(fonts)
