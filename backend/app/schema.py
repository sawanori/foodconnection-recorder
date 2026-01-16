import strawberry
from typing import List, Optional, AsyncGenerator
from datetime import datetime
from enum import Enum
import uuid
import re
import asyncio
from sqlalchemy import select

from app.models import JobModel, RecordModel, JobStatus, RecordStatus, ReplicationJobModel, ReplicationStatus
from app.database import get_session
from app.services.pubsub import (
    subscribe_to_job_progress,
    unsubscribe_from_job_progress,
    subscribe_to_record_update,
    unsubscribe_from_record_update,
    publish_job_progress
)
from app.services.job_runner import JobRunner
from app.services.replicator_runner import ReplicatorRunner
from app.config import settings


@strawberry.enum
class JobStatusEnum(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@strawberry.enum
class RecordStatusEnum(Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@strawberry.enum
class ReplicationStatusEnum(Enum):
    PENDING = "pending"
    SCRAPING = "scraping"
    GENERATING = "generating"
    VERIFYING_1 = "verifying_1"
    VERIFYING_2 = "verifying_2"
    VERIFYING_3 = "verifying_3"
    COMPLETED = "completed"
    FAILED = "failed"


@strawberry.type
class Job:
    id: str
    start_page: int
    end_page: int
    output_dir: str
    status: JobStatusEnum
    total_items: int
    processed_items: int
    created_at: datetime
    updated_at: datetime


@strawberry.type
class Record:
    id: str
    job_id: str
    shop_name: str
    shop_name_sanitized: str
    shop_url: Optional[str]
    detail_page_url: str
    video_filename: Optional[str]
    screenshot_filename: Optional[str]
    status: RecordStatusEnum
    error_message: Optional[str]
    retry_count: int
    created_at: datetime
    updated_at: datetime


@strawberry.type
class ReplicationJob:
    id: str
    source_url: str
    status: ReplicationStatusEnum
    current_iteration: int
    similarity_score: Optional[float]
    output_dir: str
    html_filename: Optional[str]
    css_filename: Optional[str]
    js_filename: Optional[str]
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


@strawberry.type
class JobProgress:
    job_id: str
    status: JobStatusEnum
    total_items: int
    processed_items: int
    current_record: Optional[Record]


@strawberry.input
class CreateJobInput:
    start_page: int
    end_page: int
    output_dir: str


@strawberry.input
class CreateReplicationJobInput:
    source_url: str
    output_dir: str


def job_model_to_type(job: JobModel) -> Job:
    """JobModelをGraphQL型に変換"""
    return Job(
        id=job.id,
        start_page=job.start_page,
        end_page=job.end_page,
        output_dir=job.output_dir,
        status=JobStatusEnum[job.status.name],
        total_items=job.total_items,
        processed_items=job.processed_items,
        created_at=job.created_at,
        updated_at=job.updated_at
    )


def record_model_to_type(record: RecordModel) -> Record:
    """RecordModelをGraphQL型に変換"""
    return Record(
        id=record.id,
        job_id=record.job_id,
        shop_name=record.shop_name or "",
        shop_name_sanitized=record.shop_name_sanitized or "",
        shop_url=record.shop_url,
        detail_page_url=record.detail_page_url,
        video_filename=record.video_filename,
        screenshot_filename=record.screenshot_filename,
        status=RecordStatusEnum[record.status.name],
        error_message=record.error_message,
        retry_count=record.retry_count,
        created_at=record.created_at,
        updated_at=record.updated_at
    )


def replication_job_model_to_type(job: ReplicationJobModel) -> ReplicationJob:
    """ReplicationJobModelをGraphQL型に変換"""
    return ReplicationJob(
        id=job.id,
        source_url=job.source_url,
        status=ReplicationStatusEnum[job.status.name],
        current_iteration=job.current_iteration,
        similarity_score=job.similarity_score,
        output_dir=job.output_dir,
        html_filename=job.html_filename,
        css_filename=job.css_filename,
        js_filename=job.js_filename,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at
    )


def validate_dir_name(dir_name: str) -> bool:
    """ディレクトリ名のバリデーション"""
    pattern = settings.ALLOWED_OUTPUT_DIR_PATTERN
    return bool(re.match(pattern, dir_name))


@strawberry.type
class Query:
    @strawberry.field
    async def jobs(self) -> List[Job]:
        """全ジョブ取得"""
        async with get_session() as session:
            result = await session.execute(select(JobModel).order_by(JobModel.created_at.desc()))
            jobs = result.scalars().all()
            return [job_model_to_type(j) for j in jobs]

    @strawberry.field
    async def job(self, id: str) -> Optional[Job]:
        """特定ジョブ取得"""
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == id)
            )
            job = result.scalar_one_or_none()
            return job_model_to_type(job) if job else None

    @strawberry.field
    async def records(self, job_id: str) -> List[Record]:
        """特定ジョブのレコード一覧取得"""
        async with get_session() as session:
            result = await session.execute(
                select(RecordModel)
                .where(RecordModel.job_id == job_id)
                .order_by(RecordModel.created_at)
            )
            records = result.scalars().all()
            return [record_model_to_type(r) for r in records]

    @strawberry.field
    async def replication_jobs(self) -> List[ReplicationJob]:
        """全複製ジョブ取得"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).order_by(ReplicationJobModel.created_at.desc())
            )
            jobs = result.scalars().all()
            return [replication_job_model_to_type(j) for j in jobs]

    @strawberry.field
    async def replication_job(self, id: str) -> Optional[ReplicationJob]:
        """特定複製ジョブ取得"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == id)
            )
            job = result.scalar_one_or_none()
            return replication_job_model_to_type(job) if job else None


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_job(self, input: CreateJobInput) -> Job:
        """ジョブ作成"""
        # バリデーション
        if input.start_page < 1:
            raise ValueError("start_page must be >= 1")
        if input.end_page < input.start_page:
            raise ValueError("end_page must be >= start_page")
        if not validate_dir_name(input.output_dir):
            raise ValueError("Invalid output_dir name. Only alphanumeric, hyphen, and underscore are allowed.")

        # ジョブ作成
        async with get_session() as session:
            job = JobModel(
                id=str(uuid.uuid4()),
                start_page=input.start_page,
                end_page=input.end_page,
                output_dir=input.output_dir,
                status=JobStatus.PENDING,
                total_items=0,
                processed_items=0,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job_model_to_type(job)

    @strawberry.mutation
    async def start_job(self, id: str) -> Job:
        """ジョブ開始 - JobRunnerをバックグラウンドで起動"""
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == id)
            )
            job = result.scalar_one()

            # ステータス確認
            if job.status != JobStatus.PENDING:
                raise ValueError(f"Job {id} is not in PENDING status")

            job.status = JobStatus.RUNNING
            await session.commit()
            await session.refresh(job)

            # 進捗配信
            await publish_job_progress(id, {
                "job_id": id,
                "status": job.status.value,
                "total_items": job.total_items,
                "processed_items": job.processed_items,
            })

            # JobRunnerをバックグラウンドで実行
            runner = JobRunner()
            asyncio.create_task(runner.run(id))

            return job_model_to_type(job)

    @strawberry.mutation
    async def stop_job(self, id: str) -> Job:
        """ジョブ停止"""
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == id)
            )
            job = result.scalar_one()
            return job_model_to_type(job)

    @strawberry.mutation
    async def retry_record(self, id: str) -> Record:
        """失敗したレコードを再試行"""
        async with get_session() as session:
            result = await session.execute(
                select(RecordModel).where(RecordModel.id == id)
            )
            record = result.scalar_one()
            record.status = RecordStatus.PENDING
            record.retry_count = 0
            record.error_message = None
            await session.commit()
            await session.refresh(record)
            return record_model_to_type(record)

    @strawberry.mutation
    async def create_replication_job(self, input: CreateReplicationJobInput) -> ReplicationJob:
        """複製ジョブ作成"""
        # バリデーション
        if not input.source_url.startswith(("http://", "https://")):
            raise ValueError("Invalid source_url. Must start with http:// or https://")
        if not validate_dir_name(input.output_dir):
            raise ValueError("Invalid output_dir name. Only alphanumeric, hyphen, and underscore are allowed.")

        # ジョブ作成
        async with get_session() as session:
            job = ReplicationJobModel(
                id=str(uuid.uuid4()),
                source_url=input.source_url,
                output_dir=input.output_dir,
                status=ReplicationStatus.PENDING,
                current_iteration=0,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return replication_job_model_to_type(job)

    @strawberry.mutation
    async def start_replication(self, id: str) -> ReplicationJob:
        """複製ジョブ開始 - ReplicatorRunnerをバックグラウンドで起動"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == id)
            )
            job = result.scalar_one()

            # ステータス確認
            if job.status != ReplicationStatus.PENDING:
                raise ValueError(f"Replication job {id} is not in PENDING status")

            # ReplicatorRunnerをバックグラウンドで実行
            runner = ReplicatorRunner()
            asyncio.create_task(runner.run(id))

            return replication_job_model_to_type(job)


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def job_progress(
        self, job_id: str
    ) -> AsyncGenerator[JobProgress, None]:
        """ジョブ進捗のリアルタイム配信"""
        queue = await subscribe_to_job_progress(job_id)
        try:
            while True:
                progress_data = await queue.get()
                yield JobProgress(
                    job_id=progress_data["job_id"],
                    status=JobStatusEnum(progress_data["status"]),
                    total_items=progress_data["total_items"],
                    processed_items=progress_data["processed_items"],
                    current_record=None  # Phase 3で実装
                )
        finally:
            await unsubscribe_from_job_progress(job_id, queue)

    @strawberry.subscription
    async def record_update(
        self, job_id: str
    ) -> AsyncGenerator[Record, None]:
        """レコード更新のリアルタイム配信"""
        queue = await subscribe_to_record_update(job_id)
        try:
            while True:
                record = await queue.get()
                yield record_model_to_type(record)
        finally:
            await unsubscribe_from_record_update(job_id, queue)


schema = strawberry.Schema(
    query=Query,
    mutation=Mutation,
    subscription=Subscription
)
