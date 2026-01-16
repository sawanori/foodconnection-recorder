import asyncio
from typing import Dict, List


# グローバル変数で管理（シンプルな実装）
_job_progress_subscribers: Dict[str, List[asyncio.Queue]] = {}
_record_update_subscribers: Dict[str, List[asyncio.Queue]] = {}


async def subscribe_to_job_progress(job_id: str) -> asyncio.Queue:
    """
    ジョブ進捗更新を購読

    Args:
        job_id: ジョブID

    Returns:
        更新を受け取るQueue
    """
    queue = asyncio.Queue()
    if job_id not in _job_progress_subscribers:
        _job_progress_subscribers[job_id] = []
    _job_progress_subscribers[job_id].append(queue)
    return queue


async def unsubscribe_from_job_progress(job_id: str, queue: asyncio.Queue):
    """
    ジョブ進捗更新の購読解除

    Args:
        job_id: ジョブID
        queue: 購読時に取得したQueue
    """
    if job_id in _job_progress_subscribers:
        if queue in _job_progress_subscribers[job_id]:
            _job_progress_subscribers[job_id].remove(queue)


async def publish_job_progress(job_id: str, progress: dict):
    """
    ジョブ進捗を配信

    Args:
        job_id: ジョブID
        progress: 進捗情報（辞書）
    """
    if job_id in _job_progress_subscribers:
        for queue in _job_progress_subscribers[job_id]:
            await queue.put(progress)


async def subscribe_to_record_update(job_id: str) -> asyncio.Queue:
    """
    レコード更新を購読

    Args:
        job_id: ジョブID

    Returns:
        更新を受け取るQueue
    """
    queue = asyncio.Queue()
    if job_id not in _record_update_subscribers:
        _record_update_subscribers[job_id] = []
    _record_update_subscribers[job_id].append(queue)
    return queue


async def unsubscribe_from_record_update(job_id: str, queue: asyncio.Queue):
    """
    レコード更新の購読解除

    Args:
        job_id: ジョブID
        queue: 購読時に取得したQueue
    """
    if job_id in _record_update_subscribers:
        if queue in _record_update_subscribers[job_id]:
            _record_update_subscribers[job_id].remove(queue)


async def publish_record_update(job_id: str, record):
    """
    レコード更新を配信

    Args:
        job_id: ジョブID
        record: レコード情報
    """
    if job_id in _record_update_subscribers:
        for queue in _record_update_subscribers[job_id]:
            await queue.put(record)
