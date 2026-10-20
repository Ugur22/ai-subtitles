import { useCallback, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { updateSettings } from '../../services/admin';
import { useAuth } from '../../hooks/useAuth';
import { SettingsContext, type SettingsTab } from '../../hooks/useSettings';

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

  const updateUserSettings = useCallback(async (settings: {
    display_name?: string;
    default_llm_provider?: string;
    visual_search_terms?: string;
    visual_search_phrases?: string;
  }) => {
    await updateMutation.mutateAsync(settings);
  }, [updateMutation]);

  return (
    <SettingsContext.Provider value={{
      isOpen,
      activeTab,
      openSettings,
      closeSettings,
      setActiveTab,
      updateUserSettings,
      isUpdating: updateMutation.isPending,
    }}>
      {children}
    </SettingsContext.Provider>
  );
};
