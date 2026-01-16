'use client';

import { useState } from 'react';
import { useMutation } from '@apollo/client';
import { CREATE_JOB, START_JOB } from '@/lib/graphql/mutations';

interface JobFormProps {
  onJobStarted: (jobId: string) => void;
}

export function JobForm({ onJobStarted }: JobFormProps) {
  const [startPage, setStartPage] = useState(1);
  const [endPage, setEndPage] = useState(1);
  const [outputDir, setOutputDir] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [createJob] = useMutation(CREATE_JOB);
  const [startJob] = useMutation(START_JOB);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // バリデーション
    if (startPage < 1 || endPage < startPage) {
      alert('ページ番号を正しく入力してください');
      return;
    }
    if (!/^[a-zA-Z0-9_-]+$/.test(outputDir)) {
      alert('出力ディレクトリ名は英数字・ハイフン・アンダースコアのみ使用可能です');
      return;
    }

    setIsSubmitting(true);

    try {
      // ジョブ作成
      const { data: createData } = await createJob({
        variables: {
          input: { startPage, endPage, outputDir }
        }
      });

      const jobId = createData.createJob.id;

      // ジョブ開始
      await startJob({
        variables: { id: jobId }
      });

      onJobStarted(jobId);

    } catch (error) {
      console.error('Job creation failed:', error);
      alert('ジョブの作成に失敗しました');
      setIsSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="bg-white p-6 rounded-lg shadow-md">
      <h2 className="text-xl font-bold mb-4">ジョブ設定</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            開始ページ
          </label>
          <input
            type="number"
            min="1"
            value={startPage}
            onChange={(e) => setStartPage(Number(e.target.value))}
            disabled={isSubmitting}
            className="w-full border border-gray-300 px-3 py-2 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            終了ページ
          </label>
          <input
            type="number"
            min="1"
            value={endPage}
            onChange={(e) => setEndPage(Number(e.target.value))}
            disabled={isSubmitting}
            className="w-full border border-gray-300 px-3 py-2 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            required
          />
        </div>
      </div>

      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          保存先ディレクトリ名
        </label>
        <input
          type="text"
          value={outputDir}
          onChange={(e) => setOutputDir(e.target.value)}
          disabled={isSubmitting}
          placeholder="output-2026-01-16"
          pattern="^[a-zA-Z0-9_-]+$"
          className="w-full border border-gray-300 px-3 py-2 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
          required
        />
        <p className="text-xs text-gray-500 mt-1">
          英数字・ハイフン・アンダースコアのみ使用可能
        </p>
      </div>

      <button
        type="submit"
        disabled={isSubmitting}
        className="w-full bg-blue-600 text-white px-6 py-3 rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors font-medium"
      >
        {isSubmitting ? '実行中...' : '実行'}
      </button>
    </form>
  );
}
