/**
 * useSettings - Manage user settings and settings panel state
 */

import React, { useState, useCallback, createContext, useContext } from 'react';
import { useMutation } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { updateSettings } from '../services/admin';
import { useAuth } from './useAuth';

type SettingsTab = 'api-keys' | 'profile' | 'account';

interface SettingsContextType {
  isOpen: boolean;
  activeTab: SettingsTab;
  openSettings: (tab?: SettingsTab) => void;
  closeSettings: () => void;
  setActiveTab: (tab: SettingsTab) => void;
  updateUserSettings: (settings: {
    display_name?: string;
    default_llm_provider?: string;
  }) => Promise<void>;
  isUpdating: boolean;
}

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

export const SettingsProvider = ({ children }: { children: React.ReactNode }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<SettingsTab>('api-keys');
  const { refetchUser } = useAuth();

  const updateMutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: async () => {
      toast.success('Settings updated successfully');
      await refetchUser();
    },
    onError: (error: Error) => {
      toast.error(error.message || 'Failed to update settings');
    },
  });

  const openSettings = useCallback((tab: SettingsTab = 'api-keys') => {
    setActiveTab(tab);
    setIsOpen(true);
  }, []);

  const closeSettings = useCallback(() => {
    setIsOpen(false);
  }, []);

  const updateUserSettings = useCallback(
    async (settings: { display_name?: string; default_llm_provider?: string }) => {
      await updateMutation.mutateAsync(settings);
    },
    [updateMutation]
  );

  return (
    <SettingsContext.Provider
      value={{
        isOpen,
        activeTab,
        openSettings,
        closeSettings,
        setActiveTab,
        updateUserSettings,
        isUpdating: updateMutation.isPending,
      }}
    >
      {children}
    </SettingsContext.Provider>
  );
};

export const useSettings = (): SettingsContextType => {
  const context = useContext(SettingsContext);
  if (!context) {
    throw new Error('useSettings must be used within SettingsProvider');
  }
  return context;
};
