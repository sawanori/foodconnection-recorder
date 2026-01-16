import { gql } from '@apollo/client';

export const GET_JOBS = gql`
  query GetJobs {
    jobs {
      id
      startPage
      endPage
      outputDir
      status
      totalItems
      processedItems
      createdAt
    }
  }
`;

export const GET_JOB = gql`
  query GetJob($id: ID!) {
    job(id: $id) {
      id
      startPage
      endPage
      outputDir
      status
      totalItems
      processedItems
      createdAt
      updatedAt
    }
  }
`;

export const GET_RECORDS = gql`
  query GetRecords($jobId: ID!) {
    records(jobId: $jobId) {
      id
      jobId
      shopName
      shopUrl
      videoFilename
      screenshotFilename
      status
      errorMessage
      retryCount
    }
  }
`;

// サイト複製クエリ
export const GET_REPLICATION_JOBS = gql`
  query GetReplicationJobs {
    replicationJobs {
      id
      sourceUrl
      status
      currentIteration
      similarityScore
      outputDir
      htmlFilename
      cssFilename
      jsFilename
      errorMessage
      createdAt
      updatedAt
    }
  }
`;

export const GET_REPLICATION_JOB = gql`
  query GetReplicationJob($id: ID!) {
    replicationJob(id: $id) {
      id
      sourceUrl
      status
      currentIteration
      similarityScore
      outputDir
      htmlFilename
      cssFilename
      jsFilename
      errorMessage
      createdAt
      updatedAt
    }
  }
`;
