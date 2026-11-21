import { useEffect, useRef, useState } from "react";
import axios from "axios";
import { API_BASE_URL } from "../../../../config";
import type { ChatProviderStatus, ReasoningEffort } from "../types";

type ProviderModels = {
  models: string[];
  default: string | null;
  error?: string | null;
  reasoning_efforts?: Record<string, ReasoningEffort[]>;
};

const modelStorageKey = (provider: string) => `chat-model:${provider}`;

export function useChatProviders() {
  const [providers, setProviders] = useState<ChatProviderStatus[]>([]);
  const [loadingProviders, setLoadingProviders] = useState(true);
  const [selectedProvider, setSelectedProvider] = useState<string>("grok");
  const [providerModels, setProviderModels] = useState<string[]>([]);
  const [selectedModel, setSelectedModel] = useState<string>("");
  const [modelsLoading, setModelsLoading] = useState(true);
  const [reasoningEfforts, setReasoningEfforts] = useState<Record<string, ReasoningEffort[]>>({});
  const [effortChoices, setEffortChoices] = useState<Record<string, ReasoningEffort>>({});
  const effortKey = `${selectedProvider}:${selectedModel}`;
  const effortOptions = reasoningEfforts[selectedModel] ?? [];
  const chosenEffort = effortChoices[effortKey];
  const selectedEffort = !modelsLoading && chosenEffort && effortOptions.includes(chosenEffort)
    ? chosenEffort
    : undefined;

  useEffect(() => {
    loadProviders();
  }, []);

  const providersLoaded = providers.length > 0;
  const modelsCache = useRef<Record<string, ProviderModels>>({});
  const [modelListError, setModelListError] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedProvider || !providersLoaded) return;
    let cancelled = false;

    const apply = ({ models, default: defaultModel, error, reasoning_efforts }: ProviderModels) => {
      setModelListError(error ?? null);
      setReasoningEfforts(reasoning_efforts ?? {});
      let saved: string | null = null;
      try {
        saved = localStorage.getItem(modelStorageKey(selectedProvider));
      } catch {
        /* storage unavailable */
      }
      setProviderModels(models);
      setSelectedModel(saved && models.includes(saved) ? saved : (defaultModel ?? models[0] ?? ""));
    };

    const cached = modelsCache.current[selectedProvider];
    if (cached) {
      apply(cached);
      setModelsLoading(false);
      return;
    }

    setProviderModels([]);
    setReasoningEfforts({});
    setSelectedModel("");
    setModelListError(null);
    setModelsLoading(true);
    axios
      .get(`${API_BASE_URL}/api/llm/providers/${selectedProvider}/models`, {
        withCredentials: true,
      })
      .then((response) => {
        if (!response.data.error) modelsCache.current[selectedProvider] = response.data;
        if (cancelled) return;
        apply(response.data);
        setModelsLoading(false);
      })
      .catch((error) => {
        console.error("Failed to load models:", error);
        if (!cancelled) setModelsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedProvider, providersLoaded]);

  const loadProviders = async () => {
    setLoadingProviders(true);
    try {
      const response = await axios.get(`${API_BASE_URL}/api/llm/providers`, {
        withCredentials: true,
      });
      setProviders(response.data.providers);

      const grokProvider = response.data.providers.find(
        (p: ChatProviderStatus) => p.name === "grok" && p.available,
      );
      if (grokProvider) {
        setSelectedProvider("grok");
      } else {
        const availableProvider = response.data.providers.find(
          (p: ChatProviderStatus) => p.available,
        );
        if (availableProvider) {
          setSelectedProvider(availableProvider.name);
        }
      }
    } catch (error) {
      console.error("Failed to load providers:", error);
    } finally {
      setLoadingProviders(false);
    }
  };

  const selectModel = (model: string) => {
    setSelectedModel(model);
    try {
      localStorage.setItem(modelStorageKey(selectedProvider), model);
    } catch {
      /* storage unavailable: the choice just won't persist */
    }
  };

  const selectEffort = (effort: ReasoningEffort | undefined) => {
    setEffortChoices((previous) => {
      const next = { ...previous };
      if (effort) next[effortKey] = effort;
      else delete next[effortKey];
      return next;
    });
  };

  return {
    providers,
    loadingProviders,
    providersLoaded,
    selectedProvider,
    setSelectedProvider,
    providerModels,
    selectedModel,
    selectModel,
    modelsLoading,
    modelListError,
    effortOptions,
    selectedEffort,
    selectEffort,
  };
}

export type ChatProvidersState = ReturnType<typeof useChatProviders>;
