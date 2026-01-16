"""
CSV出力サービス

ジョブの処理結果をCSV形式で出力します。
"""
import csv
from pathlib import Path
from sqlalchemy import select
from app.database import get_session
from app.models import RecordModel
from app.config import settings


async def export_job_report(job_id: str, output_dir: str) -> str:
    """
    ジョブの処理結果をCSV出力

    Args:
        job_id: ジョブID
        output_dir: 出力ディレクトリ名

    Returns:
        CSV出力パス

    Raises:
        Exception: CSV出力に失敗した場合
    """
    # レコード取得
    async with get_session() as session:
        result = await session.execute(
            select(RecordModel)
            .where(RecordModel.job_id == job_id)
            .order_by(RecordModel.created_at)
        )
        records = result.scalars().all()

    # CSV出力パス
    csv_path = Path(settings.OUTPUT_BASE_DIR) / output_dir / "report.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    # CSV書き込み（UTF-8 BOM付き、Excelで正しく開ける）
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f)

        # ヘッダー
        writer.writerow([
            'id',
            'shop_name',
            'shop_url',
            'detail_page_url',
            'video_file',
            'screenshot_file',
            'status',
            'error_message',
            'processed_at'
        ])

        # データ行
        for idx, record in enumerate(records, start=1):
            writer.writerow([
                idx,
                record.shop_name or '',
                record.shop_url or '',
                record.detail_page_url,
                record.video_filename or '',
                record.screenshot_filename or '',
                record.status.value,
                record.error_message or '',
                record.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

    print(f"CSV report exported: {csv_path}")
    return str(csv_path)
