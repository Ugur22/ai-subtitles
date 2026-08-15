import { createContext } from 'react';

interface JobsContextValue {
  activeJobCount: number;
  setActiveJobCount: (count: number) => void;
  showJobPanel: boolean;
  setShowJobPanel: (show: boolean) => void;
}

export const JobsContext = createContext<JobsContextValue>({
  activeJobCount: 0,
  setActiveJobCount: () => {},
  showJobPanel: false,
  setShowJobPanel: () => {},
});
