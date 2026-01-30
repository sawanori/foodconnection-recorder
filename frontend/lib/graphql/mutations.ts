import { gql } from '@apollo/client';

export const CREATE_JOB = gql`
  mutation CreateJob($input: CreateJobInput!) {
    createJob(input: $input) {
      id
      startPage
      endPage
      outputDir
      status
    }
  }
`;

export const START_JOB = gql`
  mutation StartJob($id: ID!) {
    startJob(id: $id) {
      id
      status
    }
  }
`;

export const STOP_JOB = gql`
  mutation StopJob($id: ID!) {
    stopJob(id: $id) {
      id
      status
    }
  }
`;

export const RETRY_RECORD = gql`
  mutation RetryRecord($id: ID!) {
    retryRecord(id: $id) {
      id
      status
      errorMessage
    }
  }
`;

// 単体URLジョブ作成
export const CREATE_SINGLE_URL_JOB = gql`
  mutation CreateSingleUrlJob($input: CreateSingleUrlJobInput!) {
    createSingleUrlJob(input: $input) {
      id
      jobType
      sourceUrl
      outputDir
      status
    }
  }
`;

// サイト複製ミューテーション（フォルダベース）
export const CREATE_REPLICATION_JOB = gql`
  mutation CreateReplicationJob($input: CreateReplicationJobInput!) {
    createReplicationJob(input: $input) {
      id
      inputFolder
      outputDir
      modelType
      status
    }
  }
`;

export const START_REPLICATION = gql`
  mutation StartReplication($id: ID!) {
    startReplication(id: $id) {
      id
      status
      currentIteration
    }
  }
`;
