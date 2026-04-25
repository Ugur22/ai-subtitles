/**
 * MainLayout — sidebar + content grid.
 */

import React from 'react';
import { Sidebar } from './Sidebar';
import { SettingsPanel } from '../settings/SettingsPanel';

interface MainLayoutProps {
  children: React.ReactNode;
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  return (
    <div className="app-shell">
      <Sidebar />
      <main>{children}</main>
      <SettingsPanel />
    </div>
  );
};
