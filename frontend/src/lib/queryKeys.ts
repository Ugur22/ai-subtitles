import { queryOptions } from "@tanstack/react-query";
import { listSpeakers } from "../services/api";

export const queryKeys = {
  speakers: ["speakers"] as const,
  faceTagSpeakers: (videoHash: string | null) => ["faceTagSpeakers", videoHash] as const,
  apiKeys: ["apiKeys"] as const,
  llmProviders: ["llmProviders"] as const,
  llmModelsAll: ["llmModels"] as const,
  llmModels: (provider: string) => ["llmModels", provider] as const,
  billingPlans: ["billingPlans"] as const,
};

export const speakersQuery = queryOptions({
  queryKey: queryKeys.speakers,
  queryFn: listSpeakers,
  staleTime: 5 * 60_000,
});
