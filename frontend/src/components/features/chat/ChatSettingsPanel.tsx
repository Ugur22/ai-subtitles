import { Disclosure, DisclosureButton, DisclosurePanel } from "@headlessui/react";
import { EFFORT_LABELS, FIELD_LABEL_CLASS, FIELD_WIDTH_CLASS, PROVIDER_LABELS, VISION_SUPPORTED_PROVIDERS } from "./chatSettings";
import { SelectChevron, Spinner } from "./controls";
import type { ChatProvidersState } from "./hooks/useChatProviders";

interface ChatSettingsPanelProps {
  chatProviders: ChatProvidersState;
  includeVisuals: boolean;
  setIncludeVisuals: (value: boolean) => void;
  handleReindex: () => void;
  reindexing: boolean;
}

export const ChatSettingsPanel: React.FC<ChatSettingsPanelProps> = ({
  chatProviders,
  includeVisuals,
  setIncludeVisuals,
  handleReindex,
  reindexing,
}) => {
  const {
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
  } = chatProviders;

  return (
    <Disclosure>
      {({ open }) => (
        <div style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--bg-surface)' }}>
          <DisclosureButton
            className="flex items-center gap-1.5 w-full px-4 py-2 text-xs font-medium transition-colors"
            style={{ color: 'var(--text-tertiary)' }}
          >
            <svg
              className={`w-3.5 h-3.5 transition-transform ${open ? 'rotate-90' : ''}`}
              fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            <span>{open ? 'Hide settings' : 'Model & search settings'}</span>
          </DisclosureButton>
          <DisclosurePanel className="px-4 pb-3 pt-1">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <label className={FIELD_LABEL_CLASS} style={{ color: "var(--text-secondary)" }}>
              Provider:
            </label>
            <div className="relative">
              {loadingProviders ? (
                <div className={`flex items-center gap-2 px-4 py-2 text-sm rounded-lg ${FIELD_WIDTH_CLASS} input-base`} style={{ color: "var(--text-secondary)" }}>
                  <Spinner />
                  <span>Loading providers…</span>
                </div>
              ) : (
                <select
                  value={selectedProvider}
                  onChange={(e) => {
                    const newProvider = e.target.value;
                    setSelectedProvider(newProvider);
                    if (!VISION_SUPPORTED_PROVIDERS.includes(newProvider)) {
                      setIncludeVisuals(false);
                    }
                  }}
                  className={`input-base appearance-none text-sm pl-4 pr-10 py-2 transition-colors cursor-pointer font-medium ${FIELD_WIDTH_CLASS}`}
                  title="Select LLM Provider"
                >
                  {providers.map((provider) => (
                    <option
                      key={provider.name}
                      value={provider.name}
                      disabled={!provider.available}
                    >
                      {PROVIDER_LABELS[provider.name] ?? provider.name}{" "}
                      {!provider.available && "(unavailable)"}
                    </option>
                  ))}
                </select>
              )}
              {!loadingProviders && <SelectChevron />}
            </div>
          </div>

          {providersLoaded && (
            <div className="flex items-center gap-2">
              <label htmlFor="chat-model" className={FIELD_LABEL_CLASS} style={{ color: "var(--text-secondary)" }}>
                Model:
              </label>
              {modelsLoading ? (
                <div
                  className={`flex items-center gap-2 px-4 py-2 text-sm rounded-lg ${FIELD_WIDTH_CLASS} input-base`}
                  style={{ color: "var(--text-secondary)" }}
                  aria-busy="true"
                >
                  <Spinner />
                  <span>Loading models…</span>
                </div>
              ) : providerModels.length > 1 ? (
                <div className="relative">
                  <select
                    id="chat-model"
                    value={selectedModel}
                    onChange={(e) => selectModel(e.target.value)}
                    className={`input-base appearance-none text-sm pl-4 pr-10 py-2 transition-colors cursor-pointer font-medium ${FIELD_WIDTH_CLASS} truncate`}
                    title="Select model"
                  >
                    {providerModels.map((id) => (
                      <option key={id} value={id}>
                        {id}
                      </option>
                    ))}
                  </select>
                  <SelectChevron />
                </div>
              ) : (
                <div
                  className={`input-base px-4 py-2 text-sm font-medium ${FIELD_WIDTH_CLASS} truncate cursor-default select-none`}
                  style={{ color: "var(--text-secondary)" }}
                  title="This provider only offers its default model"
                >
                  {selectedModel || "Default model"}
                </div>
              )}
            </div>
          )}

          {!modelsLoading && effortOptions.length > 0 && (
            <div className="flex items-center gap-2">
              <label htmlFor="chat-effort" className={FIELD_LABEL_CLASS} style={{ color: "var(--text-secondary)" }}>
                Thinking effort:
              </label>
              <div className="relative">
                <select
                  id="chat-effort"
                  value={selectedEffort ?? ""}
                  onChange={(event) => selectEffort(effortOptions.find((option) => option === event.target.value))}
                  className={`input-base appearance-none text-sm pl-4 pr-10 py-2 cursor-pointer font-medium ${FIELD_WIDTH_CLASS}`}
                  title="Lower effort can answer faster; higher effort spends more time reasoning."
                >
                  <option value="">Provider default</option>
                  {effortOptions.map((effort) => (
                    <option key={effort} value={effort}>{EFFORT_LABELS[effort]}</option>
                  ))}
                </select>
                <SelectChevron />
              </div>
            </div>
          )}

          {modelListError && (
            <p className="basis-full text-xs" style={{ color: "var(--text-tertiary)" }}>
              Couldn't load the model list, using the default model. {modelListError}
            </p>
          )}

          {VISION_SUPPORTED_PROVIDERS.includes(selectedProvider) && (
            <div className="relative group flex items-center gap-2">
              <button
                onClick={() => setIncludeVisuals(!includeVisuals)}
                className="btn-ghost flex items-center gap-2 px-3 py-1.5 text-sm font-medium"
                style={includeVisuals ? { background: "var(--accent-dim)", color: "var(--accent)" } : {}}
                aria-label={
                  includeVisuals
                    ? "Disable scene search"
                    : "Enable scene search"
                }
              >
                <svg
                  className="w-4 h-4"
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  {includeVisuals ? (
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                    />
                  ) : (
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21"
                    />
                  )}
                </svg>
                <span>Scene search</span>
                {includeVisuals && (
                  <span className="badge badge-accent ml-1">
                    On
                  </span>
                )}
              </button>

              <div className="relative">
                <button
                  className="w-4 h-4 rounded-full flex items-center justify-center text-[11px] font-medium transition-colors"
                  style={{ background: "var(--bg-overlay)", color: "var(--text-secondary)" }}
                  title="Scene Search finds visual moments (actions, objects, settings). Cannot identify specific people by name - use transcript for speaker queries."
                  aria-label="Scene search information"
                >
                  ?
                </button>
                <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none w-64 z-10 shadow-lg" style={{ background: "var(--bg-overlay)", color: "var(--text-primary)", border: "1px solid var(--border-subtle)" }}>
                  <div className="font-medium mb-1.5" style={{ color: "var(--text-primary)" }}>Scene search</div>
                  <div className="mb-1" style={{ color: "var(--text-secondary)" }}>
                    Finds visual moments (actions, objects, settings).
                  </div>
                  <div style={{ color: "var(--text-secondary)" }}>
                    Cannot identify specific people by name - use transcript
                    for speaker queries.
                  </div>
                  <svg
                    className="absolute top-full left-1/2 -translate-x-1/2"
                    style={{ color: "var(--bg-overlay)" }}
                    width="8"
                    height="4"
                    viewBox="0 0 8 4"
                  >
                    <path fill="currentColor" d="M0 0l4 4 4-4z" />
                  </svg>
                </div>
              </div>

              <button
                onClick={handleReindex}
                disabled={reindexing}
                className="btn-ghost !p-0 w-6 h-6 rounded-full flex items-center justify-center transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                title="Re-index images (fixes visual search)"
                aria-label="Re-index images"
              >
                {reindexing ? (
                  <svg className="animate-spin w-3.5 h-3.5" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                  </svg>
                ) : (
                  <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M4 2a1 1 0 011 1v2.101a7.002 7.002 0 0111.601 2.566 1 1 0 11-1.885.666A5.002 5.002 0 005.999 7H9a1 1 0 010 2H4a1 1 0 01-1-1V3a1 1 0 011-1zm.008 9.057a1 1 0 011.276.61A5.002 5.002 0 0014.001 13H11a1 1 0 110-2h5a1 1 0 011 1v5a1 1 0 11-2 0v-2.101a7.002 7.002 0 01-11.601-2.566 1 1 0 01.61-1.276z" clipRule="evenodd" />
                  </svg>
                )}
              </button>
            </div>
          )}
        </div>
          </DisclosurePanel>
        </div>
      )}
    </Disclosure>
  );
};
