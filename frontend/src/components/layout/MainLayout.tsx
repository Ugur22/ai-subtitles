/**
 * MainLayout — sidebar + content grid.
 */

import React, { useEffect, useState } from 'react';
import { Sidebar } from './Sidebar';
import { SettingsPanel } from '../settings/SettingsPanel';

interface MainLayoutProps {
  children: React.ReactNode;
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(() => {
    try {
      return window.localStorage.getItem('ai-subs-sidebar-collapsed') === 'true';
    } catch {
      return false;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(
        'ai-subs-sidebar-collapsed',
        String(sidebarCollapsed),
      );
    } catch {
      // Ignore storage failures; collapse state is a convenience only.
    }
  }, [sidebarCollapsed]);

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggleCollapse={() => setSidebarCollapsed((value) => !value)}
      />
      <main>{children}</main>
      <SettingsPanel />
    </div>
  );
};
