import { useContext } from 'react';
import { JobsContext } from '../contexts/jobContextValue';

export function useJobs() {
  return useContext(JobsContext);
}
