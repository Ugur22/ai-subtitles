import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getProviderModels, getProviders } from "../../../../services/llm";
import { queryKeys } from "../../../../lib/queryKeys";
import type { ReasoningEffort } from "../types";

const modelStorageKey = (provider: string) => `chat-model:${provider}`;

const readSavedModel = (provider: string): string | null => {
  try {
    return localStorage.getItem(modelStorageKey(provider));
  } catch {
    return null;
  }
};

export function useChatProviders() {
  const providersQuery = useQuery({
    queryKey: queryKeys.llmProviders,
    queryFn: getProviders,
  });
  const providers = providersQuery.data ?? [];
  const providersLoaded = providers.length > 0;

  const [providerChoice, setSelectedProvider] = useState<string | null>(null);
  const selectedProvider =
    providerChoice
    ?? providers.find((p) => p.name === "grok" && p.available)?.name
    ?? providers.find((p) => p.available)?.name
    ?? "grok";

  const modelsQuery = useQuery({
    queryKey: queryKeys.llmModels(selectedProvider),
    queryFn: () => getProviderModels(selectedProvider),
    enabled: providersLoaded,
    // A listing that came back with an error is refetched the next time the provider is picked.
    staleTime: (query) => (query.state.data?.error ? 0 : Infinity),
  });
  const modelsLoading =
    modelsQuery.isPending || (modelsQuery.isFetching && Boolean(modelsQuery.data?.error));
  const listing = modelsLoading ? undefined : modelsQuery.data;
  const providerModels = listing?.models ?? [];
  const modelListError = listing?.error ?? null;
  const reasoningEfforts = listing?.reasoning_efforts ?? {};

  const [modelChoices, setModelChoices] = useState<Record<string, string>>({});
  const wantedModel = modelChoices[selectedProvider] ?? readSavedModel(selectedProvider);
  const selectedModel = !listing
    ? ""
    : wantedModel && providerModels.includes(wantedModel)
      ? wantedModel
      : (listing.default ?? providerModels[0] ?? "");

  const [effortChoices, setEffortChoices] = useState<Record<string, ReasoningEffort>>({});
  const effortKey = `${selectedProvider}:${selectedModel}`;
  const effortOptions = reasoningEfforts[selectedModel] ?? [];
  const chosenEffort = effortChoices[effortKey];
  const selectedEffort = !modelsLoading && chosenEffort && effortOptions.includes(chosenEffort)
    ? chosenEffort
    : undefined;

  const selectModel = (model: string) => {
    setModelChoices((previous) => ({ ...previous, [selectedProvider]: model }));
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
    loadingProviders: providersQuery.isPending,
    providersLoaded,
    selectedProvider,
    setSelectedProvider: (provider: string) => setSelectedProvider(provider),
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
