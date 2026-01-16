#!/bin/bash
# Food Connection Recorder - 初回セットアップスクリプト

set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
FRONTEND_DIR="$PROJECT_DIR/frontend"

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}=== Food Connection Recorder セットアップ ===${NC}"
echo ""

# バックエンド依存関係
echo -e "${GREEN}[1/3] バックエンド依存関係インストール...${NC}"
cd "$BACKEND_DIR"
pip install -r requirements.txt

# Playwrightブラウザ
echo -e "${GREEN}[2/3] Playwrightブラウザインストール...${NC}"
python -m playwright install chromium

# フロントエンド依存関係
echo -e "${GREEN}[3/3] フロントエンド依存関係インストール...${NC}"
cd "$FRONTEND_DIR"
npm install

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}セットアップ完了!${NC}"
echo -e "起動コマンド: ./start.sh"
echo -e "${GREEN}========================================${NC}"
