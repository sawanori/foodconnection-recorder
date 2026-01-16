'use client';

import { useQuery, useSubscription } from '@apollo/client';
import { GET_RECORDS } from '@/lib/graphql/queries';
import { RECORD_UPDATE_SUBSCRIPTION } from '@/lib/graphql/subscriptions';
import { useState } from 'react';
import { RecordStatus, Record } from '@/types';

interface RecordTableProps {
  jobId: string;
}

export function RecordTable({ jobId }: RecordTableProps) {
  const [filter, setFilter] = useState<string>('all');

  // 初期データ取得
  const { data, loading } = useQuery(GET_RECORDS, {
    variables: { jobId }
  });

  // リアルタイム更新購読
  useSubscription(RECORD_UPDATE_SUBSCRIPTION, {
    variables: { jobId },
    onData: ({ client, data: subData }) => {
      if (subData?.data?.recordUpdate) {
        const updatedRecord = subData.data.recordUpdate;

        // クエリのキャッシュを更新
        const existingData = client.cache.readQuery<{ records: Record[] }>({
          query: GET_RECORDS,
          variables: { jobId }
        });

        if (existingData?.records) {
          const updatedRecords = existingData.records.map((record) =>
            record.id === updatedRecord.id ? updatedRecord : record
          );

          client.cache.writeQuery({
            query: GET_RECORDS,
            variables: { jobId },
            data: { records: updatedRecords }
          });
        }
      }
    }
  });

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="text-gray-600">読み込み中...</div>
      </div>
    );
  }

  const records: Record[] = data?.records || [];
  const filteredRecords = filter === 'all'
    ? records
    : records.filter((r) => r.status === filter);

  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden">
      <div className="p-4 border-b border-gray-200 bg-gray-50">
        <div className="flex justify-between items-center">
          <h2 className="text-xl font-bold">処理結果一覧</h2>
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="border border-gray-300 px-3 py-2 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="all">全て ({records.length})</option>
            <option value={RecordStatus.SUCCESS}>
              成功 ({records.filter(r => r.status === RecordStatus.SUCCESS).length})
            </option>
            <option value={RecordStatus.FAILED}>
              失敗 ({records.filter(r => r.status === RecordStatus.FAILED).length})
            </option>
            <option value={RecordStatus.PENDING}>
              待機中 ({records.filter(r => r.status === RecordStatus.PENDING).length})
            </option>
            <option value={RecordStatus.PROCESSING}>
              処理中 ({records.filter(r => r.status === RecordStatus.PROCESSING).length})
            </option>
          </select>
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-100 border-b border-gray-200">
            <tr>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">#</th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">店舗名</th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">URL</th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">ステータス</th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">動画</th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">スクリーンショット</th>
              <th className="px-4 py-3 text-left text-sm font-semibold text-gray-700">エラー</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200">
            {filteredRecords.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-8 text-center text-gray-500">
                  データがありません
                </td>
              </tr>
            ) : (
              filteredRecords.map((record, index) => (
                <tr key={record.id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3 text-sm text-gray-900">{index + 1}</td>
                  <td className="px-4 py-3 text-sm text-gray-900 max-w-xs truncate">
                    {record.shopName || '-'}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {record.shopUrl ? (
                      <a
                        href={record.shopUrl}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-blue-600 hover:underline"
                      >
                        開く
                      </a>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={record.status} />
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {record.videoFilename ? (
                      <div className="flex gap-2">
                        <button
                          className="text-blue-600 hover:underline text-sm"
                          onClick={() => alert('プレビュー機能は未実装')}
                        >
                          プレビュー
                        </button>
                        <a
                          href={`/api/download/${jobId}/${record.videoFilename}`}
                          download
                          className="text-green-600 hover:underline text-sm"
                        >
                          DL
                        </a>
                      </div>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {record.screenshotFilename ? (
                      <div className="flex gap-2">
                        <button
                          className="text-blue-600 hover:underline text-sm"
                          onClick={() => {
                            const imgUrl = `/api/download/${jobId}/${record.screenshotFilename}`;
                            window.open(imgUrl, '_blank');
                          }}
                        >
                          プレビュー
                        </button>
                        <a
                          href={`/api/download/${jobId}/${record.screenshotFilename}`}
                          download
                          className="text-green-600 hover:underline text-sm"
                        >
                          DL
                        </a>
                      </div>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {record.errorMessage ? (
                      <span className="text-red-600 text-xs" title={record.errorMessage}>
                        {record.errorMessage.substring(0, 50)}
                        {record.errorMessage.length > 50 ? '...' : ''}
                      </span>
                    ) : (
                      <span className="text-gray-400">-</span>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: RecordStatus }) {
  const getStatusStyle = (status: RecordStatus) => {
    switch (status) {
      case RecordStatus.SUCCESS:
        return 'bg-green-100 text-green-800 border-green-200';
      case RecordStatus.FAILED:
        return 'bg-red-100 text-red-800 border-red-200';
      case RecordStatus.PENDING:
        return 'bg-gray-100 text-gray-800 border-gray-200';
      case RecordStatus.PROCESSING:
        return 'bg-blue-100 text-blue-800 border-blue-200';
      case RecordStatus.SKIPPED:
        return 'bg-yellow-100 text-yellow-800 border-yellow-200';
      default:
        return 'bg-gray-100 text-gray-800 border-gray-200';
    }
  };

  const getStatusText = (status: RecordStatus) => {
    switch (status) {
      case RecordStatus.SUCCESS:
        return '成功';
      case RecordStatus.FAILED:
        return '失敗';
      case RecordStatus.PENDING:
        return '待機中';
      case RecordStatus.PROCESSING:
        return '処理中';
      case RecordStatus.SKIPPED:
        return 'スキップ';
      default:
        return status;
    }
  };

  return (
    <span className={`px-3 py-1 rounded-full text-xs font-medium border ${getStatusStyle(status)}`}>
      {getStatusText(status)}
    </span>
  );
}
