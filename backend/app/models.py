from sqlalchemy import Column, String, Integer, Float, DateTime, ForeignKey, Enum
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime
import enum


Base = declarative_base()


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RecordStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReplicationStatus(str, enum.Enum):
    """サイト複製ジョブのステータス"""
    PENDING = "pending"
    SCRAPING = "scraping"
    GENERATING = "generating"
    VERIFYING_1 = "verifying_1"
    VERIFYING_2 = "verifying_2"
    VERIFYING_3 = "verifying_3"
    COMPLETED = "completed"
    FAILED = "failed"


class JobModel(Base):
    __tablename__ = "jobs"

    id = Column(String, primary_key=True)
    start_page = Column(Integer, nullable=False)
    end_page = Column(Integer, nullable=False)
    output_dir = Column(String, nullable=False)
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)
    total_items = Column(Integer, default=0, nullable=False)
    processed_items = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # リレーション
    records = relationship("RecordModel", back_populates="job", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Job(id={self.id}, status={self.status}, {self.processed_items}/{self.total_items})>"


class RecordModel(Base):
    __tablename__ = "records"

    id = Column(String, primary_key=True)
    job_id = Column(String, ForeignKey("jobs.id"), nullable=False)
    shop_name = Column(String, nullable=True)  # 抽出前はNULL
    shop_name_sanitized = Column(String, nullable=True)
    shop_url = Column(String, nullable=True)
    detail_page_url = Column(String, nullable=False)
    video_filename = Column(String, nullable=True)
    screenshot_filename = Column(String, nullable=True)
    status = Column(Enum(RecordStatus), default=RecordStatus.PENDING, nullable=False)
    error_message = Column(String, nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # リレーション
    job = relationship("JobModel", back_populates="records")

    def __repr__(self):
        return f"<Record(id={self.id}, shop={self.shop_name}, status={self.status})>"


class ReplicationJobModel(Base):
    """サイト複製ジョブモデル"""
    __tablename__ = "replication_jobs"

    id = Column(String, primary_key=True)
    source_url = Column(String, nullable=False)
    screenshot_path = Column(String, nullable=True)
    status = Column(Enum(ReplicationStatus), default=ReplicationStatus.PENDING, nullable=False)
    current_iteration = Column(Integer, default=0, nullable=False)
    similarity_score = Column(Float, nullable=True)
    output_dir = Column(String, nullable=False)

    # 生成ファイルパス
    html_filename = Column(String, nullable=True)
    css_filename = Column(String, nullable=True)
    js_filename = Column(String, nullable=True)

    # エラー情報
    error_message = Column(String, nullable=True)

    # タイムスタンプ
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self):
        return f"<ReplicationJob(id={self.id}, url={self.source_url}, status={self.status})>"
