import { useState } from 'react';
import { JobsContext } from './jobContextValue';

export function JobsProvider({ children }: { children: React.ReactNode }) {
  const [activeJobCount, setActiveJobCount] = useState(0);
  const [showJobPanel, setShowJobPanel] = useState(false);

  return (
    <JobsContext.Provider value={{ activeJobCount, setActiveJobCount, showJobPanel, setShowJobPanel }}>
      {children}
    </JobsContext.Provider>
  );
}
