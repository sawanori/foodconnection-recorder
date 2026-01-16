'use client';

import { useState } from 'react';
import { JobForm } from '@/components/JobForm';
import { ProgressBar } from '@/components/ProgressBar';
import { RecordTable } from '@/components/RecordTable';
import { ErrorLog } from '@/components/ErrorLog';
import { ReplicationForm } from '@/components/ReplicationForm';
import { ReplicationProgress } from '@/components/ReplicationProgress';

type TabType = 'recorder' | 'replicator';

export default function HomePage() {
  const [activeTab, setActiveTab] = useState<TabType>('recorder');
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const [activeReplicationJobId, setActiveReplicationJobId] = useState<string | null>(null);

  return (
    <main className="min-h-screen bg-gray-100">
      <div className="container mx-auto px-4 py-8">
        <header className="mb-8">
          <h1 className="text-4xl font-bold text-gray-900 mb-2">
            Food Connection Recorder
          </h1>
          <p className="text-gray-600">
            Web実績ページ自動巡回・録画システム
          </p>
        </header>

        {/* タブ切り替え */}
        <div className="mb-6">
          <nav className="flex space-x-4 border-b border-gray-200">
            <button
              onClick={() => setActiveTab('recorder')}
              className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors ${
                activeTab === 'recorder'
                  ? 'border-blue-500 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              録画機能
            </button>
            <button
              onClick={() => setActiveTab('replicator')}
              className={`px-4 py-2 font-medium text-sm border-b-2 transition-colors ${
                activeTab === 'replicator'
                  ? 'border-green-500 text-green-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
              }`}
            >
              サイト複製
            </button>
          </nav>
        </div>

        {/* 録画機能タブ */}
        {activeTab === 'recorder' && (
          <>
            {/* 入力フォーム */}
            <section className="mb-8">
              <JobForm onJobStarted={setActiveJobId} />
            </section>

            {/* 進捗表示 */}
            {activeJobId && (
              <section className="mb-8">
                <ProgressBar jobId={activeJobId} />
              </section>
            )}

            {/* 結果一覧 */}
            {activeJobId && (
              <section className="mb-8">
                <RecordTable jobId={activeJobId} />
              </section>
            )}

            {/* エラーログ */}
            {activeJobId && (
              <section className="mb-8">
                <ErrorLog jobId={activeJobId} />
              </section>
            )}
          </>
        )}

        {/* サイト複製タブ */}
        {activeTab === 'replicator' && (
          <>
            {/* 複製フォーム */}
            <section className="mb-8">
              <ReplicationForm onJobStarted={setActiveReplicationJobId} />
            </section>

            {/* 複製進捗 */}
            {activeReplicationJobId && (
              <section className="mb-8">
                <ReplicationProgress jobId={activeReplicationJobId} />
              </section>
            )}
          </>
        )}
      </div>
    </main>
  );
}
