"""
サイト複製サービス

Webサイトをスクレイピングし、Claude CLIを使用してHTML/CSS/JSを生成します。
画像ベースの生成もサポートしています（Claude / Gemini）。
"""
from .site_scraper import SiteScraper
from .claude_generator import ClaudeGenerator
from .verifier import Verifier
from .image_comparator import ImageComparator
from .base_image_generator import (
    BaseImageGenerator,
    ImageGenerationError,
    create_image_generator,
)
from .claude_image_generator import ClaudeImageGenerator
from .gemini_image_generator import GeminiImageGenerator
from .multi_section_generator import MultiSectionGenerator

__all__ = [
    "SiteScraper",
    "ClaudeGenerator",
    "Verifier",
    "ImageComparator",
    # 画像ジェネレーター
    "BaseImageGenerator",
    "ImageGenerationError",
    "create_image_generator",
    "ClaudeImageGenerator",
    "GeminiImageGenerator",
    "MultiSectionGenerator",
]
