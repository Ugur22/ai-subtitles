import { Disclosure, DisclosureButton, DisclosurePanel } from "@headlessui/react";

export const EvidenceDisclosure: React.FC<{
  title: string;
  count?: number;
  defaultOpen?: boolean;
  icon: React.ReactNode;
  children: React.ReactNode;
}> = ({ title, count, defaultOpen = false, icon, children }) => (
  <Disclosure defaultOpen={defaultOpen}>
    {({ open }) => (
      <div className="border-b" style={{ borderColor: "var(--border-subtle)" }}>
        <DisclosureButton
          className="flex w-full items-center justify-between gap-3 py-2 text-left transition-colors"
          style={{ color: "var(--text-secondary)" }}
        >
          <span className="flex min-w-0 items-center gap-2">
            <span className="flex-shrink-0">{icon}</span>
            <span className="truncate text-sm font-medium">
              {title}
            </span>
            {typeof count === "number" && (
              <span
                className="mono text-[11px]"
                style={{ color: "var(--text-tertiary)" }}
              >
                {count}
              </span>
            )}
          </span>
          <svg
            className={`h-4 w-4 flex-shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M9 5l7 7-7 7"
            />
          </svg>
        </DisclosureButton>
        <DisclosurePanel className="pb-3">{children}</DisclosurePanel>
      </div>
    )}
  </Disclosure>
);
