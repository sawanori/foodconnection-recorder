"""
データベース接続とGraphQLエンドポイントのテストスクリプト

使用方法:
    python test_connection.py
"""
import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import select
from app.database import init_db, close_db, get_session
from app.models import JobModel, RecordModel


async def test_database_connection():
    """データベース接続テスト"""
    print("=" * 60)
    print("データベース接続テスト")
    print("=" * 60)

    try:
        # データベース初期化
        print("\n1. データベース初期化中...")
        await init_db()
        print("   ✓ データベース初期化成功")

        # セッション取得テスト
        print("\n2. データベースセッション取得中...")
        async with get_session() as session:
            print("   ✓ セッション取得成功")

            # ジョブテーブル読み込み
            print("\n3. Jobsテーブル読み込み中...")
            result = await session.execute(select(JobModel))
            jobs = result.scalars().all()
            print(f"   ✓ Jobsテーブル読み込み成功（{len(jobs)}件）")

            if jobs:
                print("\n   最新のジョブ:")
                latest_job = jobs[-1]
                print(f"   - ID: {latest_job.id}")
                print(f"   - ページ範囲: {latest_job.start_page} - {latest_job.end_page}")
                print(f"   - 保存先: {latest_job.output_dir}")
                print(f"   - ステータス: {latest_job.status.value}")
                print(f"   - 進捗: {latest_job.processed_items}/{latest_job.total_items}")

            # レコードテーブル読み込み
            print("\n4. Recordsテーブル読み込み中...")
            result = await session.execute(select(RecordModel))
            records = result.scalars().all()
            print(f"   ✓ Recordsテーブル読み込み成功（{len(records)}件）")

            if records:
                # ステータスごとの集計
                status_count = {}
                for record in records:
                    status = record.status.value
                    status_count[status] = status_count.get(status, 0) + 1

                print("\n   レコードステータス集計:")
                for status, count in status_count.items():
                    print(f"   - {status}: {count}件")

        # クローズ
        print("\n5. データベース接続クローズ中...")
        await close_db()
        print("   ✓ クローズ成功")

        print("\n" + "=" * 60)
        print("データベース接続テスト完了")
        print("=" * 60)
        return True

    except Exception as e:
        print(f"\n✗ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_graphql_endpoint():
    """GraphQLエンドポイント確認"""
    print("\n" + "=" * 60)
    print("GraphQLエンドポイント確認")
    print("=" * 60)

    try:
        import httpx

        # ヘルスチェック
        print("\n1. ヘルスチェックエンドポイント確認中...")
        print("   URL: http://localhost:8000/health")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get("http://localhost:8000/health", timeout=5.0)
                if response.status_code == 200:
                    print(f"   ✓ ヘルスチェック成功: {response.json()}")
                else:
                    print(f"   ✗ ヘルスチェック失敗: ステータスコード {response.status_code}")
                    return False
            except httpx.ConnectError:
                print("   ✗ 接続エラー: サーバーが起動していません")
                print("   ヒント: 別のターミナルで 'python run.py' を実行してください")
                return False
            except httpx.TimeoutException:
                print("   ✗ タイムアウト: サーバーが応答しません")
                return False

        # GraphQLエンドポイント
        print("\n2. GraphQLエンドポイント確認中...")
        print("   URL: http://localhost:8000/graphql")

        query = """
        query {
            jobs {
                id
                status
                totalItems
                processedItems
            }
        }
        """

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    "http://localhost:8000/graphql",
                    json={"query": query},
                    timeout=5.0
                )
                if response.status_code == 200:
                    data = response.json()
                    if "data" in data:
                        jobs = data["data"]["jobs"]
                        print(f"   ✓ GraphQLクエリ成功: {len(jobs)}件のジョブ取得")
                        if jobs:
                            print("\n   最新のジョブ:")
                            latest = jobs[-1]
                            print(f"   - ID: {latest['id'][:8]}...")
                            print(f"   - ステータス: {latest['status']}")
                            print(f"   - 進捗: {latest['processedItems']}/{latest['totalItems']}")
                    else:
                        print(f"   ✗ GraphQLエラー: {data}")
                        return False
                else:
                    print(f"   ✗ リクエスト失敗: ステータスコード {response.status_code}")
                    return False
            except Exception as e:
                print(f"   ✗ エラー: {e}")
                return False

        print("\n3. 利用可能なエンドポイント:")
        print("   - GraphiQL UI: http://localhost:8000/graphql")
        print("   - ヘルスチェック: http://localhost:8000/health")
        print("   - フロントエンド: http://localhost:3000")

        print("\n" + "=" * 60)
        print("GraphQLエンドポイント確認完了")
        print("=" * 60)
        return True

    except ImportError:
        print("\n✗ httpxがインストールされていません")
        print("   インストール: pip install httpx")
        return False
    except Exception as e:
        print(f"\n✗ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """メイン処理"""
    print("\n")
    print("*" * 60)
    print("Food Connection Recorder - 接続テスト")
    print("*" * 60)

    # データベース接続テスト
    db_ok = await test_database_connection()

    # GraphQLエンドポイント確認
    api_ok = await test_graphql_endpoint()

    # 結果サマリー
    print("\n" + "=" * 60)
    print("テスト結果サマリー")
    print("=" * 60)
    print(f"データベース接続: {'✓ OK' if db_ok else '✗ NG'}")
    print(f"GraphQLエンドポイント: {'✓ OK' if api_ok else '✗ NG'}")
    print("=" * 60)

    if db_ok and api_ok:
        print("\n全てのテストが成功しました！")
        print("\n次のステップ:")
        print("1. バックエンドが起動していない場合: python run.py")
        print("2. フロントエンドが起動していない場合: cd frontend && npm run dev")
        print("3. ブラウザで http://localhost:3000 にアクセス")
        return 0
    else:
        print("\n一部のテストが失敗しました。上記のエラーメッセージを確認してください。")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
