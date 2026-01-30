'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { useMutation, useLazyQuery } from '@apollo/client';
import { CREATE_REPLICATION_JOB, START_REPLICATION } from '@/lib/graphql/mutations';
import { SELECT_DIRECTORY } from '@/lib/graphql/queries';

interface ReplicationFormProps {
  onJobStarted: (jobId: string) => void;
}

type SelectionTarget = 'input' | 'output' | null;

type ModelType = 'CLAUDE' | 'GEMINI';

export function ReplicationForm({ onJobStarted }: ReplicationFormProps) {
  const [inputFolder, setInputFolder] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [model, setModel] = useState<ModelType>('CLAUDE');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [selectionTarget, setSelectionTarget] = useState<SelectionTarget>(null);

  // クエリ発行時のカウンターで新しい結果かどうかを判定
  const queryCountRef = useRef(0);
  const lastProcessedCountRef = useRef(0);

  const [createJob] = useMutation(CREATE_REPLICATION_JOB);
  const [startReplication] = useMutation(START_REPLICATION);

  // ディレクトリ選択クエリ（1つだけ使用）
  const [selectDirectory, { data: dirData, loading: dirLoading, error: dirError }] = useLazyQuery(SELECT_DIRECTORY, {
    fetchPolicy: 'network-only',
  });

  // ディレクトリ選択結果を処理（loadingがfalseになった時のみ処理）
  useEffect(() => {
    // ローディング中は処理しない
    if (dirLoading) return;

    // 新しい結果でない場合はスキップ
    if (queryCountRef.current === lastProcessedCountRef.current) return;

    // この結果を処理済みとしてマーク
    lastProcessedCountRef.current = queryCountRef.current;

    if (dirData?.selectDirectory && selectionTarget) {
      if (selectionTarget === 'input') {
        setInputFolder(dirData.selectDirectory);
      } else if (selectionTarget === 'output') {
        setOutputDir(dirData.selectDirectory);
      }
      setSelectionTarget(null);
    } else if (dirData && !dirData.selectDirectory && selectionTarget) {
      // キャンセルされた場合
      setSelectionTarget(null);
    }
  }, [dirData, dirLoading, selectionTarget]);

  useEffect(() => {
    if (dirError && selectionTarget) {
      setSelectionTarget(null);
      console.error('Directory selection error:', dirError);
      setError(`フォルダの選択に失敗しました: ${dirError.message}`);
    }
  }, [dirError, selectionTarget]);

  const handleSelectInputFolder = useCallback(() => {
    setSelectionTarget('input');
    setError(null);
    queryCountRef.current += 1;
    selectDirectory();
  }, [selectDirectory]);

  const handleSelectOutputDir = useCallback(() => {
    setSelectionTarget('output');
    setError(null);
    queryCountRef.current += 1;
    selectDirectory();
  }, [selectDirectory]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      // バリデーション
      if (!inputFolder.trim()) {
        throw new Error('入力フォルダを選択してください');
      }
      if (!outputDir.trim()) {
        throw new Error('出力先を選択してください');
      }

      // ジョブ作成
      const { data: createData } = await createJob({
        variables: {
          input: {
            inputFolder,
            outputDir,
            model,
          },
        },
      });

      const jobId = createData.createReplicationJob.id;

      // ジョブ開始
      await startReplication({
        variables: { id: jobId },
      });

      onJobStarted(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : '不明なエラーが発生しました');
    } finally {
      setIsSubmitting(false);
    }
  };

  const isSelectingInput = selectionTarget === 'input';
  const isSelectingOutput = selectionTarget === 'output';
  const isSelecting = selectionTarget !== null;

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <h2 className="text-2xl font-semibold mb-4">サイト複製</h2>
      <p className="text-gray-600 mb-4">
        録画機能で作成したフォルダ（スクリーンショット含む）を選択して、
        HTML/CSS/JSを生成します。最大3回の検証・修正を行います。
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* 入力フォルダ選択 */}
        <div>
          <label htmlFor="inputFolder" className="block text-sm font-medium text-gray-700 mb-1">
            入力フォルダ（録画済みフォルダ）
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              id="inputFolder"
              value={inputFolder}
              onChange={(e) => setInputFolder(e.target.value)}
              disabled={isSubmitting || isSelecting}
              placeholder="/path/to/shop_folder"
              className="flex-1 px-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-green-500 focus:border-transparent disabled:bg-gray-100"
              required
            />
            <button
              type="button"
              onClick={handleSelectInputFolder}
              disabled={isSubmitting || isSelecting}
              className="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
            >
              {isSelectingInput ? '選択中...' : '参照'}
            </button>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            .pngファイルを含むフォルダを選択してください
          </p>
        </div>

        {/* 出力先選択 */}
        <div>
          <label htmlFor="outputDir" className="block text-sm font-medium text-gray-700 mb-1">
            出力先フォルダ
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              id="outputDir"
              value={outputDir}
              onChange={(e) => setOutputDir(e.target.value)}
              disabled={isSubmitting || isSelecting}
              placeholder="/path/to/output"
              className="flex-1 px-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-green-500 focus:border-transparent disabled:bg-gray-100"
              required
            />
            <button
              type="button"
              onClick={handleSelectOutputDir}
              disabled={isSubmitting || isSelecting}
              className="px-4 py-2 bg-gray-600 text-white rounded-md hover:bg-gray-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors whitespace-nowrap"
            >
              {isSelectingOutput ? '選択中...' : '参照'}
            </button>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            HTML/CSS/JSファイルの出力先フォルダ
          </p>
        </div>

        {/* モデル選択 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            生成モデル
          </label>
          <div className="flex gap-4">
            <label className="flex items-center cursor-pointer">
              <input
                type="radio"
                name="model"
                value="CLAUDE"
                checked={model === 'CLAUDE'}
                onChange={(e) => setModel(e.target.value as ModelType)}
                disabled={isSubmitting || isSelecting}
                className="mr-2 text-green-600 focus:ring-green-500"
              />
              <span className="text-sm">
                Claude (Opus 4.5)
                <span className="text-gray-500 ml-1">- 高品質</span>
              </span>
            </label>
            <label className="flex items-center cursor-pointer">
              <input
                type="radio"
                name="model"
                value="GEMINI"
                checked={model === 'GEMINI'}
                onChange={(e) => setModel(e.target.value as ModelType)}
                disabled={isSubmitting || isSelecting}
                className="mr-2 text-blue-600 focus:ring-blue-500"
              />
              <span className="text-sm">
                Gemini (3 Flash)
                <span className="text-gray-500 ml-1">- Web開発最高評価</span>
              </span>
            </label>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Geminiを使用する場合は、GOOGLE_API_KEY環境変数が必要です
          </p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting || isSelecting}
          className={`w-full py-3 px-4 rounded-md text-white font-medium transition-colors ${
            isSubmitting || isSelecting
              ? 'bg-gray-400 cursor-not-allowed'
              : 'bg-green-600 hover:bg-green-700'
          }`}
        >
          {isSubmitting ? '処理中...' : '複製開始'}
        </button>
      </form>
    </div>
  );
}
