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

// サイト複製ミューテーション
export const CREATE_REPLICATION_JOB = gql`
  mutation CreateReplicationJob($input: CreateReplicationJobInput!) {
    createReplicationJob(input: $input) {
      id
      sourceUrl
      outputDir
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
