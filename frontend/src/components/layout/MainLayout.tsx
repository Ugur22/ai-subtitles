/**
 * MainLayout - Main application layout with header
 */

import React from 'react';
import { Header } from './Header';
import { SettingsPanel } from '../settings/SettingsPanel';

interface MainLayoutProps {
  children: React.ReactNode;
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  return (
    <div className="min-h-screen" style={{ backgroundColor: 'var(--bg-base)' }}>
      <Header />
      <main className="w-full">{children}</main>
      <SettingsPanel />
    </div>
  );
};
