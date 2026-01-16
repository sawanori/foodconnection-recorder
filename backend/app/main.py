from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from strawberry.fastapi import GraphQLRouter
from contextlib import asynccontextmanager

from app.schema import schema
from app.database import init_db, close_db
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションライフサイクル管理"""
    # Startup
    await init_db()
    print("Database initialized")
    yield
    # Shutdown
    await close_db()
    print("Database connection closed")


app = FastAPI(
    title="Food Connection Recorder API",
    version="1.0.0",
    lifespan=lifespan
)

# CORS設定
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GraphQLエンドポイント
graphql_app = GraphQLRouter(
    schema,
    graphiql=True,
    subscription_protocols=["graphql-transport-ws", "graphql-ws"]
)

app.include_router(graphql_app, prefix="/graphql")


@app.get("/health")
async def health_check():
    """ヘルスチェックエンドポイント"""
    return {"status": "ok"}


@app.get("/")
async def root():
    """ルートエンドポイント"""
    return {
        "message": "Food Connection Recorder API",
        "graphql": "/graphql",
        "health": "/health"
    }
