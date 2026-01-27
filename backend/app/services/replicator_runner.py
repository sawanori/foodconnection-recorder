"""
サイト複製ランナー

複製ジョブの全体フローを制御します。
"""
import asyncio
import logging
import os
import uuid
from typing import Optional
from datetime import datetime
from sqlalchemy import select
from PIL import Image

from app.database import get_session
from app.models import ReplicationJobModel, ReplicationStatus
from app.config import settings
from app.services.replicator import SiteScraper, ClaudeGenerator, Verifier, create_image_generator
from app.services.replicator.site_scraper import ScrapingError
from app.services.replicator.claude_generator import GenerationError
from app.services.replicator.verifier import VerificationError
from app.services.replicator.design_extractor import DesignExtractor

logger = logging.getLogger(__name__)

# 同時実行数制限
MAX_CONCURRENT_JOBS = 2
_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

# 最大検証回数
MAX_ITERATIONS = 3

# 類似度閾値（これ以上なら検証終了）
SIMILARITY_THRESHOLD = 95.0


class ReplicatorRunner:
    """サイト複製ランナークラス"""

    def __init__(self):
        self.scraper = SiteScraper()
        self.generator = ClaudeGenerator()
        self.verifier = Verifier()
        
        # 画像生成器の追加
        self.image_generator = create_image_generator(provider="claude")
        # デザイン抽出器の追加
        self.design_extractor = DesignExtractor()

    async def run(self, job_id: str):
        """
        複製ジョブを実行

        Args:
            job_id: ジョブID
        """
        async with _semaphore:
            await self._execute(job_id)

    async def _get_job(self, job_id: str):
        """
        ジョブをデータベースから取得

        Args:
            job_id: ジョブID

        Returns:
            ReplicationJobModel インスタンス

        Raises:
            ValueError: ジョブが見つからない場合
        """
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one_or_none()

            if not job:
                raise ValueError(f"Job not found: {job_id}")

            return job

    async def _execute(self, job_id: str):
        """ジョブ実行の本体"""
        logger.info(f"Starting replication job: {job_id}")

        try:
            # ジョブ情報の取得
            job = await self._get_job(job_id)

            # 生成モードの判定
            if job.screenshot_path and os.path.exists(job.screenshot_path):
                # モードA: 画像ベース生成（優先）
                logger.info(f"Using image-based generation: {job.screenshot_path}")
                await self._update_status(job_id, ReplicationStatus.GENERATING)
                generated_code = await self._generate_from_image(
                    job_id, job.screenshot_path
                )
                # ファイル保存
                output_dir = await self._save_files(job_id, generated_code)
                # 画像ベースの場合は検証をスキップして完了
                source_url = None
                html_path = os.path.join(output_dir, "index.html")
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
                source_url = scraped_data["url"]
                html_path = os.path.join(output_dir, "index.html")

            # Phase 3: 検証ループ（URLベースの場合のみ）
            if source_url:
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

    async def _scrape(self, job_id: str) -> dict:
        """スクレイピング実行"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            source_url = job.source_url

        return await self.scraper.scrape(source_url)

    async def _generate(self, job_id: str, scraped_data: dict) -> dict:
        """コード生成実行"""
        return await self.generator.generate(scraped_data)

    async def _save_files(self, job_id: str, code: dict) -> str:
        """
        生成ファイルを保存

        Returns:
            出力ディレクトリパス
        """
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            output_dir_name = job.output_dir

        # 出力ディレクトリ作成
        base_dir = os.path.abspath(settings.OUTPUT_BASE_DIR)
        output_dir = os.path.join(base_dir, output_dir_name, "replicated")
        os.makedirs(output_dir, exist_ok=True)

        # ファイル保存
        html_path = os.path.join(output_dir, "index.html")
        css_path = os.path.join(output_dir, "styles.css")
        js_path = os.path.join(output_dir, "script.js")

        # HTMLにCSS/JSリンクを追加（必要に応じて）
        html_content = code.get("html", "")
        if "<link" not in html_content and code.get("css"):
            # headタグ内にCSSリンクを追加
            html_content = html_content.replace(
                "</head>",
                '  <link rel="stylesheet" href="styles.css">\n</head>'
            )
        if "<script" not in html_content and code.get("js"):
            # bodyタグ終了前にJSを追加
            html_content = html_content.replace(
                "</body>",
                '  <script src="script.js"></script>\n</body>'
            )

        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        with open(css_path, 'w', encoding='utf-8') as f:
            f.write(code.get("css", ""))

        with open(js_path, 'w', encoding='utf-8') as f:
            f.write(code.get("js", ""))

        # DB更新
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            job.html_filename = "index.html"
            job.css_filename = "styles.css"
            job.js_filename = "script.js"
            await session.commit()

        logger.info(f"Files saved to: {output_dir}")
        return output_dir

    async def _update_status(
        self,
        job_id: str,
        status: ReplicationStatus,
        error_message: Optional[str] = None
    ):
        """ステータス更新"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            job.status = status
            job.updated_at = datetime.utcnow()
            if error_message:
                job.error_message = error_message
            if status.value.startswith("verifying_"):
                job.current_iteration = int(status.value.split("_")[1])
            await session.commit()

        logger.info(f"Job {job_id} status: {status.value}")

    async def _update_similarity(self, job_id: str, similarity: float):
        """類似度更新"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == job_id)
            )
            job = result.scalar_one()
            job.similarity_score = similarity
            job.updated_at = datetime.utcnow()
            await session.commit()

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
        img = Image.open(image_path)
        width, height = img.size
        img.close()
        logger.info(f"Image size: {width}x{height} (aspect ratio: {height/width:.2f})")

        # デザイン抽出（オプション）
        design_tokens = None
        if hasattr(self, 'design_extractor'):
            try:
                design_tokens = self.design_extractor.extract_from_image(image_path)
                logger.info(f"Design tokens extracted: {len(design_tokens.get('colors', []))} colors")
            except Exception as e:
                logger.warning(f"Design extraction failed: {e}")

        # 画像から生成
        generated_code = await self.image_generator.generate_from_image(
            image_path=image_path,
            design_tokens=design_tokens
        )

        logger.info(f"Generated from image: HTML={len(generated_code.get('html', ''))} chars")

        return generated_code
