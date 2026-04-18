import { useEffect, useRef, useState, useCallback } from 'react';

type Status = 'idle' | 'listening' | 'denied' | 'error';

export interface UseSpeechRecognition {
  isSupported: boolean;
  status: Status;
  interim: string;
  start: () => void;
  stop: () => void;
  error: string | null;
}

interface Options {
  lang?: string;
  onFinalTranscript?: (text: string) => void;
}

export function useSpeechRecognition(opts: Options = {}): UseSpeechRecognition {
  const SR =
    typeof window !== 'undefined'
      ? (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
      : undefined;
  const isSupported = !!SR;

  const [status, setStatus] = useState<Status>('idle');
  const [interim, setInterim] = useState('');
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<any>(null);
  const userStoppedRef = useRef(false);
  const onFinalRef = useRef(opts.onFinalTranscript);
  onFinalRef.current = opts.onFinalTranscript;

  useEffect(() => {
    if (!isSupported) return;
    const rec = new SR();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = opts.lang ?? 'en-US';

    rec.onresult = (e: any) => {
      let interimText = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) {
          onFinalRef.current?.(String(r[0].transcript).trim());
        } else {
          interimText += r[0].transcript;
        }
      }
      setInterim(interimText);
    };
    rec.onerror = (e: any) => {
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        userStoppedRef.current = true;
        setStatus('denied');
        setError(e.error);
      } else {
        // 'no-speech', 'audio-capture', etc. — let onend handle restart
        setError(e.error || 'speech-error');
      }
    };
    rec.onend = () => {
      setInterim('');
      if (userStoppedRef.current) {
        setStatus('idle');
        return;
      }
      try {
        rec.start();
      } catch {
        setStatus('idle');
      }
    };

    recRef.current = rec;
    return () => {
      try { rec.stop(); } catch { /* noop */ }
    };
  }, [isSupported, opts.lang]);

  const start = useCallback(() => {
    if (!recRef.current || status === 'listening') return;
    setError(null);
    userStoppedRef.current = false;
    try {
      recRef.current.start();
      setStatus('listening');
    } catch {
      /* already started */
    }
  }, [status]);

  const stop = useCallback(() => {
    if (!recRef.current) return;
    userStoppedRef.current = true;
    try { recRef.current.stop(); } catch { /* noop */ }
    setStatus('idle');
  }, []);

  return { isSupported, status, interim, start, stop, error };
}
