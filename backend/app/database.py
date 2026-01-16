from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from contextlib import asynccontextmanager
from app.models import Base
from app.config import settings


# 非同期エンジン作成
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=True,  # 開発時はTrue（SQLログ出力）
    future=True
)

# セッションファクトリー
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


async def init_db():
    """DB初期化（テーブル作成）"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def close_db():
    """DB接続クローズ"""
    await engine.dispose()


@asynccontextmanager
async def get_session():
    """セッション取得（contextmanager）"""
    async with AsyncSessionLocal() as session:
        yield session
