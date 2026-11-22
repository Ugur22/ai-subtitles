import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getProviderModels, getProviders, type ProviderModels } from "../../../../services/llm";
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

const listingFailed = (listing: ProviderModels | undefined) => Boolean(listing?.error);

const pickModel = (listing: ProviderModels, wanted: string | null) =>
  wanted && listing.models.includes(wanted) ? wanted : (listing.default ?? listing.models[0] ?? "");

export function useChatProviders() {
  const providersQuery = useQuery({
    queryKey: queryKeys.llmProviders,
    queryFn: getProviders,
  });
  const providers = providersQuery.data ?? [];
  const providersLoaded = providers.length > 0;

  const [providerChoice, setProviderChoice] = useState<string | null>(null);
  const selectedProvider =
    providerChoice
    ?? providers.find((p) => p.name === "grok" && p.available)?.name
    ?? providers.find((p) => p.available)?.name
    ?? "grok";

  const modelsQuery = useQuery({
    queryKey: queryKeys.llmModels(selectedProvider),
    queryFn: () => getProviderModels(selectedProvider),
    enabled: providersLoaded,
    staleTime: (query) => (listingFailed(query.state.data) ? 0 : Infinity),
  });
  const refetchingFailedListing = modelsQuery.isFetching && listingFailed(modelsQuery.data);
  const modelsLoading = modelsQuery.isPending || refetchingFailedListing;
  const listing = modelsLoading ? undefined : modelsQuery.data;
  const providerModels = listing?.models ?? [];
  const modelListError = listing?.error ?? null;
  const reasoningEfforts = listing?.reasoning_efforts ?? {};

  const [modelChoices, setModelChoices] = useState<Record<string, string>>({});
  const savedModel = useMemo(() => readSavedModel(selectedProvider), [selectedProvider]);
  const selectedModel = listing ? pickModel(listing, modelChoices[selectedProvider] ?? savedModel) : "";

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
    setSelectedProvider: setProviderChoice,
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
