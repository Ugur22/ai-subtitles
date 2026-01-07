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
    <div className="min-h-screen bg-gradient-to-br from-gray-50 to-gray-100">
      <Header />
      <main className="w-full">{children}</main>
      <SettingsPanel />
    </div>
  );
};
