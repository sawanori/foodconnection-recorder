"""
ジョブ実行サービス

ジョブの実行を管理します。
Phase 1: URL収集
Phase 2: データ抽出・録画
"""
import asyncio
import uuid
from typing import Dict
from sqlalchemy import select, update
from app.database import get_session
from app.models import JobModel, RecordModel, JobStatus, RecordStatus
from app.services.scraper import ScraperService
from app.services.recorder import RecorderService
from app.services.pubsub import publish_job_progress, publish_record_update
from app.services.errors import (
    NetworkError,
    TimeoutError,
    ElementNotFoundError,
    FileSystemError,
    PlaywrightError
)
from app.config import settings


class JobRunner:
    """ジョブ実行クラス"""

    def __init__(self):
        self.scraper = ScraperService()
        self.recorder = RecorderService()
        self.stop_flags: Dict[str, bool] = {}  # job_id -> bool

    async def run(self, job_id: str):
        """
        ジョブ実行メイン処理

        Args:
            job_id: ジョブID
        """
        try:
            # Phase 1: URL収集
            await self._collect_urls(job_id)

            # Phase 2: データ抽出・録画
            await self._process_records(job_id)

            # 完了処理
            await self._complete_job(job_id)

        except Exception as e:
            print(f"Job {job_id} failed: {e}")
            await self._fail_job(job_id, str(e))

    async def _collect_urls(self, job_id: str):
        """
        Phase 1: 一覧ページから詳細ページURLを収集

        Args:
            job_id: ジョブID
        """
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == job_id)
            )
            job = result.scalar_one()

            all_urls = []
            for page_num in range(job.start_page, job.end_page + 1):
                if self._should_stop(job_id):
                    break

                # 一覧ページURL生成
                if page_num == 1:
                    list_url = "https://f-webdesign.biz/category/all/"
                else:
                    list_url = f"https://f-webdesign.biz/category/all/page/{page_num}/"

                # 詳細ページURL抽出
                try:
                    urls = await self.scraper.extract_detail_urls(list_url)
                    all_urls.extend(urls)
                    print(f"Extracted {len(urls)} URLs from page {page_num}")
                except Exception as e:
                    print(f"Failed to extract URLs from page {page_num}: {e}")
                    # URL収集のエラーはスキップして次のページへ
                    continue

            # 重複除去
            unique_urls = list(set(all_urls))
            print(f"Total unique URLs: {len(unique_urls)}")

            # レコード作成
            for url in unique_urls:
                record = RecordModel(
                    id=str(uuid.uuid4()),
                    job_id=job_id,
                    detail_page_url=url,
                    status=RecordStatus.PENDING,
                )
                session.add(record)

            # ジョブ更新
            job.total_items = len(unique_urls)
            await session.commit()

            # 進捗配信
            await publish_job_progress(job_id, {
                "job_id": job_id,
                "status": JobStatus.RUNNING.value,
                "total_items": len(unique_urls),
                "processed_items": 0,
                "current_record": None
            })

    async def _process_records(self, job_id: str):
        """
        Phase 2: 各レコードを処理（データ抽出・録画）

        Args:
            job_id: ジョブID
        """
        while True:
            if self._should_stop(job_id):
                break

            # 次の未処理レコード取得
            async with get_session() as session:
                result = await session.execute(
                    select(RecordModel)
                    .where(RecordModel.job_id == job_id)
                    .where(RecordModel.status == RecordStatus.PENDING)
                    .limit(1)
                )
                record = result.scalar_one_or_none()

                if not record:
                    break  # 全件処理完了

                record_id = record.id

            # レコード処理
            await self._process_single_record(job_id, record_id)

    async def _process_single_record(self, job_id: str, record_id: str):
        """
        単一レコードの処理

        Args:
            job_id: ジョブID
            record_id: レコードID
        """
        max_retries = settings.MAX_RETRIES
        retry_count = 0

        while retry_count < max_retries:
            try:
                async with get_session() as session:
                    result = await session.execute(
                        select(RecordModel).where(RecordModel.id == record_id)
                    )
                    record = result.scalar_one()

                    # ステータス更新（処理中）
                    record.status = RecordStatus.PROCESSING
                    record.retry_count = retry_count
                    await session.commit()
                    await session.refresh(record)
                    await publish_record_update(job_id, record)

                    detail_url = record.detail_page_url

                # データ抽出
                shop_data = await self.scraper.extract_shop_data(detail_url)

                if not shop_data["shop_name"]:
                    raise ElementNotFoundError("shop_name not found")

                # 動画録画
                async with get_session() as session:
                    result = await session.execute(
                        select(JobModel).where(JobModel.id == job_id)
                    )
                    job = result.scalar_one()
                    output_dir = job.output_dir

                recording_result = await self.recorder.record_page(
                    url=detail_url,
                    shop_name=shop_data["shop_name"],
                    output_dir=output_dir
                )

                # 成功時の更新
                async with get_session() as session:
                    result = await session.execute(
                        select(RecordModel).where(RecordModel.id == record_id)
                    )
                    record = result.scalar_one()
                    record.shop_name = shop_data["shop_name"]
                    record.shop_name_sanitized = shop_data["shop_name_sanitized"]
                    record.shop_url = shop_data["shop_url"]
                    record.video_filename = recording_result["video_filename"]
                    record.screenshot_filename = recording_result["screenshot_filename"]
                    record.status = RecordStatus.SUCCESS
                    record.error_message = None
                    await session.commit()

                    # ジョブ進捗更新
                    await session.execute(
                        update(JobModel)
                        .where(JobModel.id == job_id)
                        .values(processed_items=JobModel.processed_items + 1)
                    )
                    await session.commit()
                    await session.refresh(record)

                    # 配信
                    await publish_record_update(job_id, record)
                    await self._publish_job_progress(job_id)

                print(f"Record {record_id} processed successfully")
                return  # 成功 → 終了

            except ElementNotFoundError as e:
                # 要素未検出 → スキップ（リトライ不要）
                print(f"Record {record_id} skipped: {e}")
                async with get_session() as session:
                    result = await session.execute(
                        select(RecordModel).where(RecordModel.id == record_id)
                    )
                    record = result.scalar_one()
                    record.status = RecordStatus.SKIPPED
                    record.error_message = str(e)
                    record.retry_count = retry_count
                    await session.commit()
                    await session.refresh(record)

                    # ジョブ進捗更新
                    await session.execute(
                        update(JobModel)
                        .where(JobModel.id == job_id)
                        .values(processed_items=JobModel.processed_items + 1)
                    )
                    await session.commit()

                    await publish_record_update(job_id, record)
                    await self._publish_job_progress(job_id)
                return

            except (NetworkError, TimeoutError, FileSystemError, PlaywrightError) as e:
                # リトライ可能エラー
                print(f"Record {record_id} failed (retry {retry_count + 1}/{max_retries}): {e}")
                retry_count += 1

                if retry_count < max_retries:
                    # 指数バックオフ
                    wait_time = settings.RETRY_BACKOFF_BASE ** retry_count  # 2秒, 4秒, 8秒
                    await asyncio.sleep(wait_time)
                else:
                    # 最大リトライ回数到達
                    async with get_session() as session:
                        result = await session.execute(
                            select(RecordModel).where(RecordModel.id == record_id)
                        )
                        record = result.scalar_one()
                        record.status = RecordStatus.FAILED
                        record.error_message = f"Max retries reached: {str(e)}"
                        record.retry_count = retry_count
                        await session.commit()
                        await session.refresh(record)

                        # ジョブ進捗更新
                        await session.execute(
                            update(JobModel)
                            .where(JobModel.id == job_id)
                            .values(processed_items=JobModel.processed_items + 1)
                        )
                        await session.commit()

                        await publish_record_update(job_id, record)
                        await self._publish_job_progress(job_id)

            except Exception as e:
                # 予期しないエラー
                print(f"Record {record_id} unexpected error (retry {retry_count + 1}/{max_retries}): {e}")
                retry_count += 1

                if retry_count >= max_retries:
                    async with get_session() as session:
                        result = await session.execute(
                            select(RecordModel).where(RecordModel.id == record_id)
                        )
                        record = result.scalar_one()
                        record.status = RecordStatus.FAILED
                        record.error_message = f"Unexpected error: {str(e)}"
                        record.retry_count = retry_count
                        await session.commit()
                        await session.refresh(record)

                        # ジョブ進捗更新
                        await session.execute(
                            update(JobModel)
                            .where(JobModel.id == job_id)
                            .values(processed_items=JobModel.processed_items + 1)
                        )
                        await session.commit()

                        await publish_record_update(job_id, record)
                        await self._publish_job_progress(job_id)
                else:
                    await asyncio.sleep(settings.RETRY_BACKOFF_BASE ** retry_count)

    async def _publish_job_progress(self, job_id: str):
        """
        ジョブ進捗を配信

        Args:
            job_id: ジョブID
        """
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == job_id)
            )
            job = result.scalar_one()

            await publish_job_progress(job_id, {
                "job_id": job_id,
                "status": job.status.value,
                "total_items": job.total_items,
                "processed_items": job.processed_items,
            })

    async def _complete_job(self, job_id: str):
        """
        ジョブ完了処理

        Args:
            job_id: ジョブID
        """
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == job_id)
            )
            job = result.scalar_one()
            job.status = JobStatus.COMPLETED
            await session.commit()

            print(f"Job {job_id} completed")

            await publish_job_progress(job_id, {
                "job_id": job_id,
                "status": JobStatus.COMPLETED.value,
                "total_items": job.total_items,
                "processed_items": job.processed_items,
            })

    async def _fail_job(self, job_id: str, error: str):
        """
        ジョブ失敗処理

        Args:
            job_id: ジョブID
            error: エラーメッセージ
        """
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == job_id)
            )
            job = result.scalar_one()
            job.status = JobStatus.FAILED
            await session.commit()

            print(f"Job {job_id} failed: {error}")

            await publish_job_progress(job_id, {
                "job_id": job_id,
                "status": JobStatus.FAILED.value,
                "total_items": job.total_items,
                "processed_items": job.processed_items,
            })

    def _should_stop(self, job_id: str) -> bool:
        """
        停止フラグチェック

        Args:
            job_id: ジョブID

        Returns:
            停止する場合True
        """
        return self.stop_flags.get(job_id, False)

    def set_stop_flag(self, job_id: str):
        """
        停止フラグ設定

        Args:
            job_id: ジョブID
        """
        self.stop_flags[job_id] = True
