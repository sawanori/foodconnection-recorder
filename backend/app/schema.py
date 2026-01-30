import strawberry
from typing import List, Optional, AsyncGenerator
from datetime import datetime
from enum import Enum
import uuid
import re
import asyncio
import subprocess
import platform
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
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"  # 追加
    FAILED = "failed"


@strawberry.type
class Job:
    id: strawberry.ID
    job_type: str
    start_page: Optional[int]
    end_page: Optional[int]
    source_url: Optional[str]
    output_dir: str
    status: JobStatusEnum
    total_items: int
    processed_items: int
    created_at: datetime
    updated_at: datetime


@strawberry.type
class Record:
    id: strawberry.ID
    job_id: strawberry.ID
    shop_name: str
    shop_name_sanitized: str
    shop_url: Optional[str]
    detail_page_url: str
    video_filename: Optional[str]
    screenshot_filename: Optional[str]
    html_filename: Optional[str]
    status: RecordStatusEnum
    error_message: Optional[str]
    retry_count: int
    created_at: datetime
    updated_at: datetime


@strawberry.type
class ReplicationJob:
    id: strawberry.ID
    input_folder: str
    source_url: Optional[str]  # 後方互換性のため残す
    model_type: Optional[str]  # 使用するモデル（claude/gemini）
    status: ReplicationStatusEnum
    current_iteration: int
    similarity_score: Optional[float]
    output_dir: str
    html_filename: Optional[str]
    css_filename: Optional[str]
    js_filename: Optional[str]
    error_message: Optional[str]
    warnings: Optional[str]  # 追加
    created_at: datetime
    updated_at: datetime


@strawberry.type
class JobProgress:
    job_id: strawberry.ID
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
class CreateSingleUrlJobInput:
    url: str
    output_dir: str


@strawberry.enum
class ImageGeneratorModelEnum(Enum):
    CLAUDE = "claude"
    GEMINI = "gemini"


@strawberry.input
class CreateReplicationJobInput:
    input_folder: str  # 入力フォルダパス（.png含む）
    output_dir: str
    model: Optional[ImageGeneratorModelEnum] = None  # 使用するモデル（デフォルトはClaude）


def job_model_to_type(job: JobModel) -> Job:
    """JobModelをGraphQL型に変換"""
    return Job(
        id=job.id,
        job_type=job.job_type,
        start_page=job.start_page,
        end_page=job.end_page,
        source_url=job.source_url,
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
        html_filename=record.html_filename,
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
        input_folder=job.input_folder,
        source_url=job.source_url,
        model_type=job.model_type,
        status=ReplicationStatusEnum[job.status.name],
        current_iteration=job.current_iteration,
        similarity_score=job.similarity_score,
        output_dir=job.output_dir,
        html_filename=job.html_filename,
        css_filename=job.css_filename,
        js_filename=job.js_filename,
        error_message=job.error_message,
        warnings=job.warnings,  # 追加
        created_at=job.created_at,
        updated_at=job.updated_at
    )


def validate_dir_name(dir_name: str) -> bool:
    """ディレクトリ名のバリデーション
    
    絶対パスまたは相対パス（英数字・ハイフン・アンダースコアのみ）を許可。
    パストラバーサル攻撃を防ぐため、相対パスに .. が含まれる場合は拒否。
    """
    import os
    
    # 空文字列は拒否
    if not dir_name or not dir_name.strip():
        return False
    
    # 絶対パスの場合は、パストラバーサルをチェック
    if os.path.isabs(dir_name):
        # 正規化したパスが元のパスと異なる場合は拒否（../ などが含まれる）
        normalized = os.path.normpath(dir_name)
        # 基本的に絶対パスは許可（ただし .. を含む不正なパスは除外）
        if '..' in dir_name:
            return False
        return True
    else:
        # 相対パスの場合は、英数字・ハイフン・アンダースコアのみ許可
        pattern = r"^[a-zA-Z0-9_-]+$"
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
    async def job(self, id: strawberry.ID) -> Optional[Job]:
        """特定ジョブ取得"""
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == id)
            )
            job = result.scalar_one_or_none()
            return job_model_to_type(job) if job else None

    @strawberry.field
    async def records(self, job_id: strawberry.ID) -> List[Record]:
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
    async def replication_job(self, id: strawberry.ID) -> Optional[ReplicationJob]:
        """特定複製ジョブ取得"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == id)
            )
            job = result.scalar_one_or_none()
            return replication_job_model_to_type(job) if job else None

    @strawberry.field
    def select_directory(self) -> Optional[str]:
        """macOSのFinderでディレクトリ選択ダイアログを開く"""
        if platform.system() != "Darwin":
            raise ValueError("この機能はmacOSでのみ利用可能です")

        script = '''
        tell application "Finder"
            activate
        end tell
        set selectedFolder to choose folder with prompt "保存先フォルダを選択してください"
        return POSIX path of selectedFolder
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                return path if path else None
            elif result.returncode == -128 or "User canceled" in result.stderr or "キャンセル" in result.stderr:
                # ユーザーがキャンセルした場合は正常終了
                print("ディレクトリ選択がキャンセルされました")
                return None
            else:
                # その他のエラー
                error_msg = result.stderr.strip() or f"osascriptがエラーを返しました (returncode: {result.returncode})"
                print(f"osascript error: {error_msg}")
                raise RuntimeError(f"ディレクトリ選択に失敗しました: {error_msg}")
        except subprocess.TimeoutExpired:
            error_msg = "ディレクトリ選択がタイムアウトしました（120秒）"
            print(error_msg)
            raise RuntimeError(error_msg)
        except RuntimeError:
            # 上で発生させたエラーを再度raiseする
            raise
        except Exception as e:
            error_msg = f"予期しないエラーが発生しました: {str(e)}"
            print(error_msg)
            raise RuntimeError(error_msg)


@strawberry.type
class Mutation:
    @strawberry.mutation
    async def create_job(self, input: CreateJobInput) -> Job:
        """一括ジョブ作成"""
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
                job_type="bulk",
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
    async def create_single_url_job(self, input: CreateSingleUrlJobInput) -> Job:
        """単体URLジョブ作成"""
        # バリデーション
        if not input.url.startswith(("http://", "https://")):
            raise ValueError("Invalid URL. Must start with http:// or https://")
        if not validate_dir_name(input.output_dir):
            raise ValueError("Invalid output_dir name. Only alphanumeric, hyphen, and underscore are allowed.")

        # ジョブ作成
        async with get_session() as session:
            job = JobModel(
                id=str(uuid.uuid4()),
                job_type="single",
                source_url=input.url,
                output_dir=input.output_dir,
                status=JobStatus.PENDING,
                total_items=1,
                processed_items=0,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return job_model_to_type(job)

    @strawberry.mutation
    async def start_job(self, id: strawberry.ID) -> Job:
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
    async def stop_job(self, id: strawberry.ID) -> Job:
        """ジョブ停止"""
        async with get_session() as session:
            result = await session.execute(
                select(JobModel).where(JobModel.id == id)
            )
            job = result.scalar_one()
            return job_model_to_type(job)

    @strawberry.mutation
    async def retry_record(self, id: strawberry.ID) -> Record:
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
        """複製ジョブ作成（フォルダベース）"""
        import os

        # バリデーション
        if not input.input_folder:
            raise ValueError("input_folder is required")
        if not os.path.isdir(input.input_folder):
            raise ValueError(f"Input folder does not exist: {input.input_folder}")

        # .pngファイルの存在確認（screenshots/サブフォルダも検索）
        import glob as glob_module

        # パターン1: screenshots/サブフォルダから検索（優先）
        png_files = glob_module.glob(os.path.join(input.input_folder, "screenshots", "*.png"))

        # パターン2: 直下から検索（後方互換性）
        if not png_files:
            png_files = glob_module.glob(os.path.join(input.input_folder, "*.png"))

        # パターン3: 再帰検索（フォールバック）
        if not png_files:
            png_files = glob_module.glob(os.path.join(input.input_folder, "**", "*.png"), recursive=True)

        if not png_files:
            raise ValueError(
                f"No PNG files found in: {input.input_folder}\n"
                f"Searched: screenshots/, root, and subdirectories"
            )

        if not input.output_dir:
            raise ValueError("output_dir is required")

        # モデルタイプ決定
        model_type = input.model.value if input.model else "claude"

        # ジョブ作成
        async with get_session() as session:
            job = ReplicationJobModel(
                id=str(uuid.uuid4()),
                input_folder=input.input_folder,
                output_dir=input.output_dir,
                model_type=model_type,
                status=ReplicationStatus.PENDING,
                current_iteration=0,
            )
            session.add(job)
            await session.commit()
            await session.refresh(job)
            return replication_job_model_to_type(job)

    @strawberry.mutation
    async def start_replication(self, id: strawberry.ID) -> ReplicationJob:
        """複製ジョブ開始 - ReplicatorRunnerをバックグラウンドで起動"""
        async with get_session() as session:
            result = await session.execute(
                select(ReplicationJobModel).where(ReplicationJobModel.id == id)
            )
            job = result.scalar_one()

            # ステータス確認
            if job.status != ReplicationStatus.PENDING:
                raise ValueError(f"Replication job {id} is not in PENDING status")

            # モデルタイプを取得
            model_type = job.model_type or "claude"

            # ReplicatorRunnerをバックグラウンドで実行
            runner = ReplicatorRunner(model_type=model_type)
            asyncio.create_task(runner.run(id))

            return replication_job_model_to_type(job)


@strawberry.type
class Subscription:
    @strawberry.subscription
    async def job_progress(
        self, job_id: strawberry.ID
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
        self, job_id: strawberry.ID
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
