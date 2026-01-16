#!/bin/bash
# Food Connection Recorder - 起動スクリプト
# バックエンド(8000)とフロントエンド(3000)を同時起動

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

# 色付き出力
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Food Connection Recorder ===${NC}"
echo ""

# 既存プロセスを停止
cleanup() {
    echo -e "\n${YELLOW}サーバーを停止中...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

# バックエンド起動
echo -e "${GREEN}[1/2] バックエンド起動中... (port 8000)${NC}"
cd "$BACKEND_DIR"
PYTHONPATH=. python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# バックエンドの起動を待機
sleep 2

# フロントエンド起動
echo -e "${GREEN}[2/2] フロントエンド起動中... (port 3000)${NC}"
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}サーバー起動完了!${NC}"
echo -e "  バックエンド:   http://localhost:8000"
echo -e "  GraphQL:        http://localhost:8000/graphql"
echo -e "  フロントエンド: http://localhost:3000"
echo -e "${GREEN}========================================${NC}"
echo -e "${YELLOW}Ctrl+C で停止${NC}"
echo ""

# プロセスを監視
wait
