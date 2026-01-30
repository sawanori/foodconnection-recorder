'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useMutation, useLazyQuery } from '@apollo/client';
import { CREATE_JOB, START_JOB, CREATE_SINGLE_URL_JOB } from '@/lib/graphql/mutations';
import { SELECT_DIRECTORY } from '@/lib/graphql/queries';

interface JobFormProps {
  onJobStarted: (jobId: string) => void;
}

type JobType = 'bulk' | 'single';

export function JobForm({ onJobStarted }: JobFormProps) {
  const [jobType, setJobType] = useState<JobType>('single');
  const [startPage, setStartPage] = useState(1);
  const [endPage, setEndPage] = useState(1);
  const [singleUrl, setSingleUrl] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSelectingDir, setIsSelectingDir] = useState(false);

  // クエリ発行時のカウンターで新しい結果かどうかを判定
  const queryCountRef = useRef(0);
  const lastProcessedCountRef = useRef(0);

  const [createJob] = useMutation(CREATE_JOB);
  const [createSingleUrlJob] = useMutation(CREATE_SINGLE_URL_JOB);
  const [startJob] = useMutation(START_JOB);

  // ディレクトリ選択クエリ
  const [selectDirectory, { data: dirData, loading: dirLoading, error: dirError }] = useLazyQuery(SELECT_DIRECTORY, {
    fetchPolicy: 'network-only',
  });

  // ディレクトリ選択結果を処理
  useEffect(() => {
    if (dirLoading) return;
    if (queryCountRef.current === lastProcessedCountRef.current) return;

    lastProcessedCountRef.current = queryCountRef.current;

    if (dirData?.selectDirectory && isSelectingDir) {
      setOutputDir(dirData.selectDirectory);
      setIsSelectingDir(false);
    } else if (dirData && !dirData.selectDirectory && isSelectingDir) {
      setIsSelectingDir(false);
    }
  }, [dirData, dirLoading, isSelectingDir]);

  useEffect(() => {
    if (dirError && isSelectingDir) {
      setIsSelectingDir(false);
      console.error('Directory selection error:', dirError);
      alert(`フォルダの選択に失敗しました: ${dirError.message}`);
    }
  }, [dirError, isSelectingDir]);

  const handleSelectOutputDir = useCallback(() => {
    setIsSelectingDir(true);
    queryCountRef.current += 1;
    selectDirectory();
  }, [selectDirectory]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // バリデーション
    if (jobType === 'bulk') {
      if (startPage < 1 || endPage < startPage) {
        alert('ページ番号を正しく入力してください');
        return;
      }
    } else {
      if (!singleUrl || !singleUrl.startsWith('http')) {
        alert('有効なURLを入力してください（http:// または https://）');
        return;
      }
    }

    if (!outputDir.trim()) {
      alert('保存先ディレクトリを選択してください');
      return;
    }

    setIsSubmitting(true);

    try {
      let jobId: string;

      if (jobType === 'bulk') {
        // バルクジョブ作成
        const { data: createData } = await createJob({
          variables: {
            input: { startPage, endPage, outputDir }
          }
        });
        jobId = createData.createJob.id;
      } else {
        // 単一URLジョブ作成
        const { data: createData } = await createSingleUrlJob({
          variables: {
            input: { url: singleUrl, outputDir }
          }
        });
        jobId = createData.createSingleUrlJob.id;
      }

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

      {/* ジョブタイプ選択 */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          ジョブタイプ
        </label>
        <div className="flex gap-4">
          <label className="flex items-center cursor-pointer">
            <input
              type="radio"
              name="jobType"
              value="single"
              checked={jobType === 'single'}
              onChange={(e) => setJobType(e.target.value as JobType)}
              disabled={isSubmitting}
              className="mr-2 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm">
              単一URL
              <span className="text-gray-500 ml-1">- 1つのページを録画</span>
            </span>
          </label>
          <label className="flex items-center cursor-pointer">
            <input
              type="radio"
              name="jobType"
              value="bulk"
              checked={jobType === 'bulk'}
              onChange={(e) => setJobType(e.target.value as JobType)}
              disabled={isSubmitting}
              className="mr-2 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-sm">
              バルク
              <span className="text-gray-500 ml-1">- 複数ページを一括録画</span>
            </span>
          </label>
        </div>
      </div>

      {/* 単一URL入力 */}
      {jobType === 'single' && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            URL
          </label>
          <input
            type="url"
            value={singleUrl}
            onChange={(e) => setSingleUrl(e.target.value)}
            disabled={isSubmitting}
            placeholder="https://example.com"
            className="w-full border border-gray-300 px-3 py-2 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            required
          />
          <p className="text-xs text-gray-500 mt-1">
            録画したいWebページのURLを入力してください
          </p>
        </div>
      )}

      {/* バルクジョブ用のページ範囲 */}
      {jobType === 'bulk' && (
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
      )}

      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 mb-2">
          保存先ディレクトリ
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={outputDir}
            onChange={(e) => setOutputDir(e.target.value)}
            disabled={isSubmitting || isSelectingDir}
            placeholder="/path/to/output"
            className="flex-1 border border-gray-300 px-3 py-2 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-100"
            required
          />
          <button
            type="button"
            onClick={handleSelectOutputDir}
            disabled={isSubmitting || isSelectingDir}
            className="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
          >
            {isSelectingDir ? '選択中...' : '参照'}
          </button>
        </div>
        <p className="text-xs text-gray-500 mt-1">
          録画ファイルを保存するディレクトリを選択してください
        </p>
      </div>

      <button
        type="submit"
        disabled={isSubmitting}
        className="w-full bg-blue-600 text-white px-6 py-3 rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors font-medium"
      >
        {isSubmitting ? '録画中...' : 'ジョブ開始'}
      </button>
    </form>
  );
}
