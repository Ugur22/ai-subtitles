import React, { useState } from "react";
import { Dialog, DialogPanel, DialogTitle } from "@headlessui/react";
import { secondsToTimeString } from "../../../utils/time";

interface JumpToTimeModalProps {
  isOpen: boolean;
  onClose: () => void;
  onJump: (seconds: number) => void;
  duration: number;
  currentTime: number;
}

const parseTimeInput = (input: string): number | null => {
  const parts = input
    .trim()
    .split(":")
    .map((p) => p.trim());
  if (parts.length === 0) return null;
  let seconds = 0;
  if (parts.length === 3) {
    seconds =
      parseFloat(parts[0]) * 3600 +
      parseFloat(parts[1]) * 60 +
      parseFloat(parts[2]);
  } else if (parts.length === 2) {
    seconds = parseFloat(parts[0]) * 60 + parseFloat(parts[1]);
  } else if (parts.length === 1) {
    seconds = parseFloat(parts[0]);
  } else {
    return null;
  }
  return isNaN(seconds) ? null : seconds;
};

export const JumpToTimeModal: React.FC<JumpToTimeModalProps> = ({
  isOpen,
  onClose,
  ...formProps
}) => (
  <Dialog open={isOpen} onClose={onClose} className="relative z-50">
    <div className="modal-overlay">
      <DialogPanel className="modal-content max-w-sm p-6">
        <JumpToTimeForm onClose={onClose} {...formProps} />
      </DialogPanel>
    </div>
  </Dialog>
);

const JumpToTimeForm: React.FC<Omit<JumpToTimeModalProps, "isOpen">> = ({
  onClose,
  onJump,
  duration,
  currentTime,
}) => {
  const [input, setInput] = useState(() => secondsToTimeString(currentTime));
  const [error, setError] = useState("");
  const hasDuration = duration > 0;
  const durationLabel = secondsToTimeString(duration);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const seconds = parseTimeInput(input);
    if (seconds === null || seconds < 0 || (hasDuration && seconds > duration)) {
      setError(
        hasDuration
          ? `Enter a time between 00:00 and ${durationLabel}`
          : "Enter a time like 20:35 or 1:30:45"
      );
      return;
    }
    onJump(seconds);
    onClose();
  };

  return (
    <form onSubmit={handleSubmit}>
      <DialogTitle
        className="text-base font-medium"
        style={{ color: "var(--text-primary)" }}
      >
        Jump to time
      </DialogTitle>
      {hasDuration && (
        <p className="mt-1 text-sm" style={{ color: "var(--text-secondary)" }}>
          Video length{" "}
          <span className="font-mono tabular-nums">{durationLabel}</span>
        </p>
      )}
      <input
        data-autofocus
        className="input-base mt-4 font-mono tabular-nums text-lg"
        placeholder="mm:ss or h:mm:ss"
        aria-label="Time"
        aria-invalid={!!error}
        value={input}
        onFocus={(e) => e.target.select()}
        onChange={(e) => {
          setInput(e.target.value);
          if (error) setError("");
        }}
      />
      {error && (
        <p className="mt-2 text-sm" style={{ color: "var(--c-error)" }}>
          {error}
        </p>
      )}
      <div className="mt-6 flex justify-end gap-2">
        <button type="button" className="btn-secondary" onClick={onClose}>
          Cancel
        </button>
        <button type="submit" className="btn-primary">
          Jump
        </button>
      </div>
    </form>
  );
};
