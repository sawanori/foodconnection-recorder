.PHONY: start stop setup

# 起動
start:
	@./start.sh

# 停止
stop:
	@pkill -f "uvicorn app.main:app" 2>/dev/null || true
	@pkill -f "next dev" 2>/dev/null || true
	@echo "停止しました"

# 初回セットアップ
setup:
	@./setup.sh
