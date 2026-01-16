'use client';

import { useQuery, useMutation } from '@apollo/client';
import { GET_RECORDS } from '@/lib/graphql/queries';
import { RETRY_RECORD } from '@/lib/graphql/mutations';
import { RecordStatus, Record } from '@/types';
import { useState } from 'react';

interface ErrorLogProps {
  jobId: string;
}

export function ErrorLog({ jobId }: ErrorLogProps) {
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());

  const { data, loading, refetch } = useQuery(GET_RECORDS, {
    variables: { jobId }
  });

  const [retryRecord] = useMutation(RETRY_RECORD);

  const handleRetry = async (recordId: string) => {
    setRetryingIds(prev => new Set(prev).add(recordId));

    try {
      await retryRecord({
        variables: { id: recordId }
      });

      // データ再取得
      await refetch();

      alert('レコードを再実行キューに追加しました');
    } catch (error) {
      console.error('Retry failed:', error);
      alert('再実行に失敗しました');
    } finally {
      setRetryingIds(prev => {
        const next = new Set(prev);
        next.delete(recordId);
        return next;
      });
    }
  };

  if (loading) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="text-gray-600">読み込み中...</div>
      </div>
    );
  }

  const records: Record[] = data?.records || [];
  const failedRecords = records.filter(
    r => r.status === RecordStatus.FAILED || r.status === RecordStatus.SKIPPED
  );

  if (failedRecords.length === 0) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <h2 className="text-xl font-bold mb-4">エラーログ</h2>
        <div className="text-gray-600 text-center py-8">
          エラーはありません
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow-md overflow-hidden">
      <div className="p-4 border-b border-gray-200 bg-red-50">
        <h2 className="text-xl font-bold text-red-800">
          エラーログ ({failedRecords.length}件)
        </h2>
      </div>

      <div className="divide-y divide-gray-200">
        {failedRecords.map((record, index) => (
          <div key={record.id} className="p-4 hover:bg-gray-50">
            <div className="flex justify-between items-start mb-2">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-sm font-semibold text-gray-700">
                    #{index + 1}
                  </span>
                  <span className="text-sm font-medium text-gray-900">
                    {record.shopName || '(店舗名未取得)'}
                  </span>
                  <span className={`px-2 py-1 rounded text-xs font-medium ${
                    record.status === RecordStatus.FAILED
                      ? 'bg-red-100 text-red-800'
                      : 'bg-yellow-100 text-yellow-800'
                  }`}>
                    {record.status === RecordStatus.FAILED ? '失敗' : 'スキップ'}
                  </span>
                </div>

                <div className="text-sm text-gray-600 mb-2">
                  <a
                    href={record.detailPageUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-600 hover:underline"
                  >
                    {record.detailPageUrl}
                  </a>
                </div>

                {record.errorMessage && (
                  <div className="text-sm text-red-600 bg-red-50 p-2 rounded border border-red-200">
                    <span className="font-semibold">エラー: </span>
                    {record.errorMessage}
                  </div>
                )}

                {record.retryCount > 0 && (
                  <div className="text-xs text-gray-500 mt-1">
                    リトライ回数: {record.retryCount}
                  </div>
                )}
              </div>

              <button
                onClick={() => handleRetry(record.id)}
                disabled={retryingIds.has(record.id)}
                className="ml-4 px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
              >
                {retryingIds.has(record.id) ? '再実行中...' : '再実行'}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
