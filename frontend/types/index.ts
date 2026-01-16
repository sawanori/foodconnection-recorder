export enum JobStatus {
  PENDING = 'PENDING',
  RUNNING = 'RUNNING',
  COMPLETED = 'COMPLETED',
  FAILED = 'FAILED',
}

export enum RecordStatus {
  PENDING = 'PENDING',
  PROCESSING = 'PROCESSING',
  SUCCESS = 'SUCCESS',
  FAILED = 'FAILED',
  SKIPPED = 'SKIPPED',
}

export interface Job {
  id: string;
  startPage: number;
  endPage: number;
  outputDir: string;
  status: JobStatus;
  totalItems: number;
  processedItems: number;
  createdAt: string;
  updatedAt: string;
}

export interface Record {
  id: string;
  jobId: string;
  shopName: string;
  shopNameSanitized: string;
  shopUrl?: string;
  detailPageUrl: string;
  videoFilename?: string;
  screenshotFilename?: string;
  status: RecordStatus;
  errorMessage?: string;
  retryCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface JobProgress {
  jobId: string;
  status: JobStatus;
  totalItems: number;
  processedItems: number;
  currentRecord?: Record;
}

export interface CreateJobInput {
  startPage: number;
  endPage: number;
  outputDir: string;
}
