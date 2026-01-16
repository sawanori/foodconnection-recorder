'use client';

import { useQuery } from '@apollo/client';
import { GET_REPLICATION_JOB } from '@/lib/graphql/queries';

interface ReplicationProgressProps {
  jobId: string;
}

const STATUS_LABELS: Record<string, string> = {
  PENDING: '待機中',
  SCRAPING: 'スクレイピング中',
  GENERATING: 'コード生成中',
  VERIFYING_1: '検証中 (1/3)',
  VERIFYING_2: '検証中 (2/3)',
  VERIFYING_3: '検証中 (3/3)',
  COMPLETED: '完了',
  FAILED: '失敗',
};

const STATUS_COLORS: Record<string, string> = {
  PENDING: 'bg-gray-200',
  SCRAPING: 'bg-blue-500',
  GENERATING: 'bg-purple-500',
  VERIFYING_1: 'bg-yellow-500',
  VERIFYING_2: 'bg-yellow-500',
  VERIFYING_3: 'bg-yellow-500',
  COMPLETED: 'bg-green-500',
  FAILED: 'bg-red-500',
};

export function ReplicationProgress({ jobId }: ReplicationProgressProps) {
  const { data, loading, error } = useQuery(GET_REPLICATION_JOB, {
    variables: { id: jobId },
    pollInterval: 2000, // 2秒ごとにポーリング
  });

  if (loading && !data) {
    return (
      <div className="bg-white rounded-lg shadow-md p-6">
        <div className="animate-pulse">
          <div className="h-4 bg-gray-200 rounded w-1/4 mb-4"></div>
          <div className="h-8 bg-gray-200 rounded w-full"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md">
        エラー: {error.message}
      </div>
    );
  }

  const job = data?.replicationJob;
  if (!job) {
    return null;
  }

  const statusLabel = STATUS_LABELS[job.status] || job.status;
  const statusColor = STATUS_COLORS[job.status] || 'bg-gray-200';
  const isCompleted = job.status === 'COMPLETED';
  const isFailed = job.status === 'FAILED';

  // 進捗計算
  const progressSteps = [
    'SCRAPING',
    'GENERATING',
    'VERIFYING_1',
    'VERIFYING_2',
    'VERIFYING_3',
    'COMPLETED',
  ];
  const currentIndex = progressSteps.indexOf(job.status);
  const progress = currentIndex >= 0 ? ((currentIndex + 1) / progressSteps.length) * 100 : 0;

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <h2 className="text-xl font-semibold mb-4">複製進捗</h2>

      {/* ステータス表示 */}
      <div className="mb-4">
        <span
          className={`inline-block px-3 py-1 rounded-full text-white text-sm font-medium ${statusColor}`}
        >
          {statusLabel}
        </span>
      </div>

      {/* プログレスバー */}
      {!isCompleted && !isFailed && (
        <div className="mb-4">
          <div className="w-full bg-gray-200 rounded-full h-4">
            <div
              className={`h-4 rounded-full transition-all duration-300 ${statusColor}`}
              style={{ width: `${progress}%` }}
            ></div>
          </div>
          <p className="text-sm text-gray-600 mt-1">
            イテレーション: {job.currentIteration}/3
          </p>
        </div>
      )}

      {/* 類似度スコア */}
      {job.similarityScore !== null && (
        <div className="mb-4">
          <p className="text-sm text-gray-600">類似度スコア</p>
          <p className="text-3xl font-bold text-blue-600">{job.similarityScore.toFixed(1)}%</p>
        </div>
      )}

      {/* 詳細情報 */}
      <div className="text-sm text-gray-600 space-y-2">
        <p>
          <span className="font-medium">複製元:</span>{' '}
          <a href={job.sourceUrl} target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">
            {job.sourceUrl}
          </a>
        </p>
        <p>
          <span className="font-medium">出力フォルダ:</span> {job.outputDir}
        </p>
      </div>

      {/* 完了時の出力ファイル */}
      {isCompleted && (
        <div className="mt-4 p-4 bg-green-50 rounded-md">
          <h3 className="font-medium text-green-800 mb-2">生成ファイル</h3>
          <ul className="text-sm text-green-700 space-y-1">
            {job.htmlFilename && <li>HTML: {job.htmlFilename}</li>}
            {job.cssFilename && <li>CSS: {job.cssFilename}</li>}
            {job.jsFilename && <li>JS: {job.jsFilename}</li>}
          </ul>
          <p className="text-sm text-green-700 mt-2">
            出力先: output/{job.outputDir}/replicated/
          </p>
        </div>
      )}

      {/* エラー表示 */}
      {isFailed && job.errorMessage && (
        <div className="mt-4 p-4 bg-red-50 rounded-md">
          <h3 className="font-medium text-red-800 mb-2">エラー</h3>
          <p className="text-sm text-red-700">{job.errorMessage}</p>
        </div>
      )}
    </div>
  );
}
