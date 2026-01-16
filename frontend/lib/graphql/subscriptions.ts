import { gql } from '@apollo/client';

export const JOB_PROGRESS_SUBSCRIPTION = gql`
  subscription JobProgress($jobId: ID!) {
    jobProgress(jobId: $jobId) {
      jobId
      status
      totalItems
      processedItems
      currentRecord {
        id
        shopName
        status
      }
    }
  }
`;

export const RECORD_UPDATE_SUBSCRIPTION = gql`
  subscription RecordUpdate($jobId: ID!) {
    recordUpdate(jobId: $jobId) {
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
