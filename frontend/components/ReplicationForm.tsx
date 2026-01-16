'use client';

import { useState } from 'react';
import { useMutation } from '@apollo/client';
import { CREATE_REPLICATION_JOB, START_REPLICATION } from '@/lib/graphql/mutations';

interface ReplicationFormProps {
  onJobStarted: (jobId: string) => void;
}

export function ReplicationForm({ onJobStarted }: ReplicationFormProps) {
  const [sourceUrl, setSourceUrl] = useState('');
  const [outputDir, setOutputDir] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [createJob] = useMutation(CREATE_REPLICATION_JOB);
  const [startReplication] = useMutation(START_REPLICATION);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      // バリデーション
      if (!sourceUrl.startsWith('http://') && !sourceUrl.startsWith('https://')) {
        throw new Error('URLはhttp://またはhttps://で始まる必要があります');
      }
      if (!outputDir || !/^[a-zA-Z0-9_-]+$/.test(outputDir)) {
        throw new Error('出力フォルダ名は英数字、ハイフン、アンダースコアのみ使用できます');
      }

      // ジョブ作成
      const { data: createData } = await createJob({
        variables: {
          input: {
            sourceUrl,
            outputDir,
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

  return (
    <div className="bg-white rounded-lg shadow-md p-6">
      <h2 className="text-2xl font-semibold mb-4">サイト複製</h2>
      <p className="text-gray-600 mb-4">
        URLを入力してサイトを複製します。Claude CLIを使用してHTML/CSS/JSを生成し、
        Playwrightで検証を3回行います。
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div>
          <label htmlFor="sourceUrl" className="block text-sm font-medium text-gray-700 mb-1">
            複製元URL
          </label>
          <input
            type="url"
            id="sourceUrl"
            value={sourceUrl}
            onChange={(e) => setSourceUrl(e.target.value)}
            placeholder="https://example.com"
            className="w-full px-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            required
          />
        </div>

        <div>
          <label htmlFor="outputDir" className="block text-sm font-medium text-gray-700 mb-1">
            出力フォルダ名
          </label>
          <input
            type="text"
            id="outputDir"
            value={outputDir}
            onChange={(e) => setOutputDir(e.target.value)}
            placeholder="my-site-copy"
            className="w-full px-4 py-2 border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            required
          />
          <p className="text-sm text-gray-500 mt-1">
            英数字、ハイフン、アンダースコアのみ使用可能
          </p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting}
          className={`w-full py-3 px-4 rounded-md text-white font-medium transition-colors ${
            isSubmitting
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
