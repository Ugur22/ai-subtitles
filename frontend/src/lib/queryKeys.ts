export const queryKeys = {
  speakers: ["speakers"] as const,
  faceTagSpeakers: (videoHash: string | null) => ["faceTagSpeakers", videoHash] as const,
  llmProviders: ["llmProviders"] as const,
  llmModels: (provider: string) => ["llmModels", provider] as const,
  billingPlans: ["billingPlans"] as const,
};
