import { createContext, useContext, useState } from 'react';

interface JobsContextValue {
  activeJobCount: number;
  setActiveJobCount: (count: number) => void;
  showJobPanel: boolean;
  setShowJobPanel: (show: boolean) => void;
}

const JobsContext = createContext<JobsContextValue>({
  activeJobCount: 0,
  setActiveJobCount: () => {},
  showJobPanel: false,
  setShowJobPanel: () => {},
});

export function JobsProvider({ children }: { children: React.ReactNode }) {
  const [activeJobCount, setActiveJobCount] = useState(0);
  const [showJobPanel, setShowJobPanel] = useState(false);

  return (
    <JobsContext.Provider value={{ activeJobCount, setActiveJobCount, showJobPanel, setShowJobPanel }}>
      {children}
    </JobsContext.Provider>
  );
}

export function useJobs() {
  return useContext(JobsContext);
}
