/**
 * useSettings - Manage user settings and settings panel state
 */

import { createContext, useContext } from 'react';

export type SettingsTab = 'api-keys' | 'profile' | 'account';

export interface SettingsContextType {
  isOpen: boolean;
  activeTab: SettingsTab;
  openSettings: (tab?: SettingsTab) => void;
  closeSettings: () => void;
  setActiveTab: (tab: SettingsTab) => void;
  updateUserSettings: (settings: {
    display_name?: string;
    default_llm_provider?: string;
    visual_search_terms?: string;
    visual_search_phrases?: string;
  }) => Promise<void>;
  isUpdating: boolean;
}

export const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

export const useSettings = (): SettingsContextType => {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error('useSettings must be used within SettingsProvider');
  }
  return context;
};
