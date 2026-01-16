'use client';

import { useSubscription } from '@apollo/client';
import { JOB_PROGRESS_SUBSCRIPTION } from '@/lib/graphql/subscriptions';
import { JobStatus } from '@/types';

interface ProgressBarProps {
  jobId: string;
}

export function ProgressBar({ jobId }: ProgressBarProps) {
  const { data, loading } = useSubscription(JOB_PROGRESS_SUBSCRIPTION, {
    variables: { jobId }
  });

  if (loading || !data) {
    return (
      <div className="bg-white p-6 rounded-lg shadow-md">
        <div className="text-gray-600">進捗読み込み中...</div>
      </div>
    );
  }

  const progress = data.jobProgress;
  const percentage = progress.totalItems > 0
    ? Math.round((progress.processedItems / progress.totalItems) * 100)
    : 0;

  const getStatusColor = (status: JobStatus) => {
    switch (status) {
      case JobStatus.RUNNING:
        return 'text-blue-600';
      case JobStatus.COMPLETED:
        return 'text-green-600';
      case JobStatus.FAILED:
        return 'text-red-600';
      default:
        return 'text-gray-600';
    }
  };

  const getStatusText = (status: JobStatus) => {
    switch (status) {
      case JobStatus.PENDING:
        return '待機中';
      case JobStatus.RUNNING:
        return '実行中';
      case JobStatus.COMPLETED:
        return '完了';
      case JobStatus.FAILED:
        return '失敗';
      default:
        return status;
    }
  };

  return (
    <div className="bg-white p-6 rounded-lg shadow-md">
      <div className="flex justify-between items-center mb-3">
        <h2 className="text-xl font-bold">進捗状況</h2>
        <span className={`font-semibold ${getStatusColor(progress.status)}`}>
          {getStatusText(progress.status)}
        </span>
      </div>

      <div className="w-full bg-gray-200 rounded-full h-6 mb-3 overflow-hidden">
        <div
          className="bg-blue-600 h-6 rounded-full transition-all duration-300 flex items-center justify-center text-white text-sm font-medium"
          style={{ width: `${percentage}%` }}
        >
          {percentage > 0 && `${percentage}%`}
        </div>
      </div>

      <div className="text-sm text-gray-600 mb-4">
        {progress.processedItems} / {progress.totalItems} 件処理済み
      </div>

      {progress.currentRecord && (
        <div className="mt-4 p-4 bg-blue-50 rounded-md border border-blue-200">
          <div className="text-sm font-semibold text-blue-800 mb-1">
            現在処理中:
          </div>
          <div className="text-sm text-blue-900">
            {progress.currentRecord.shopName}
          </div>
        </div>
      )}
    </div>
  );
}
