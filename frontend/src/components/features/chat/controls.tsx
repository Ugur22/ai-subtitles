export const SelectChevron = () => (
  <div className="absolute inset-y-0 right-0 flex items-center pr-3 pointer-events-none">
    <svg
      className="w-4 h-4"
      style={{ color: "var(--text-secondary)" }}
      fill="none"
      stroke="currentColor"
      viewBox="0 0 24 24"
    >
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
    </svg>
  </div>
);

export const Spinner = () => (
  <svg className="w-4 h-4 animate-spin" style={{ color: "var(--text-secondary)" }} fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path
      className="opacity-75"
      fill="currentColor"
      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
    />
  </svg>
);
