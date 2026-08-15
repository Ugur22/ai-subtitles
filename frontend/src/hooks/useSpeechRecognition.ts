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

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  [index: number]: { transcript: string };
}

interface SpeechRecognitionEventLike extends Event {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
}

interface SpeechRecognitionErrorEventLike extends Event {
  error: string;
}

interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onstart: (() => void) | null;
  onaudiostart: (() => void) | null;
  onspeechstart: (() => void) | null;
  onspeechend: (() => void) | null;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionLike;

const SpeechRecognitionApi = typeof window !== 'undefined'
  ? (window as Window & {
      SpeechRecognition?: SpeechRecognitionConstructor;
      webkitSpeechRecognition?: SpeechRecognitionConstructor;
    }).SpeechRecognition
    || (window as Window & { webkitSpeechRecognition?: SpeechRecognitionConstructor }).webkitSpeechRecognition
  : undefined;

export function useSpeechRecognition(opts: Options = {}): UseSpeechRecognition {
  const isSupported = !!SpeechRecognitionApi;

  const [status, setStatus] = useState<Status>('idle');
  const [interim, setInterim] = useState('');
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const userStoppedRef = useRef(false);
  const onFinalRef = useRef(opts.onFinalTranscript);
  onFinalRef.current = opts.onFinalTranscript;

  useEffect(() => {
    if (!isSupported) return;
    if (!SpeechRecognitionApi) return;
    const rec = new SpeechRecognitionApi();
    rec.continuous = true;
    rec.interimResults = true;
    rec.lang = opts.lang ?? 'en-US';

    rec.onstart = () => {
      console.log('[speech] start');
      setStatus('listening');
      setError(null);
    };
    rec.onaudiostart = () => console.log('[speech] audiostart');
    rec.onspeechstart = () => console.log('[speech] speechstart');
    rec.onspeechend = () => console.log('[speech] speechend');

    rec.onresult = (e: SpeechRecognitionEventLike) => {
      console.log('[speech] result event, results.length =', e.results.length);
      let interimText = '';
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const r = e.results[i];
        if (r.isFinal) {
          const finalText = String(r[0].transcript).trim();
          console.log('[speech] final:', finalText);
          onFinalRef.current?.(finalText);
        } else {
          interimText += r[0].transcript;
        }
      }
      setInterim(interimText);
    };

    rec.onerror = (e: SpeechRecognitionErrorEventLike) => {
      console.warn('[speech] error:', e.error);
      if (e.error === 'not-allowed' || e.error === 'service-not-allowed') {
        userStoppedRef.current = true;
        setStatus('denied');
        setError(e.error);
      } else if (e.error === 'aborted') {
        userStoppedRef.current = true;
        setStatus('idle');
        setError(e.error);
      } else {
        // 'no-speech', 'audio-capture', etc. — benign, let onend restart
        setError(e.error || 'speech-error');
      }
    };

    rec.onend = () => {
      console.log('[speech] end (userStopped=', userStoppedRef.current, ')');
      setInterim('');
      if (userStoppedRef.current) {
        setStatus('idle');
        return;
      }
      setTimeout(() => {
        if (userStoppedRef.current) return;
        try {
          rec.start();
        } catch (err) {
          console.warn('[speech] restart failed:', err);
          setStatus('idle');
        }
      }, 200);
    };

    recRef.current = rec;
    return () => {
      userStoppedRef.current = true;
      try { rec.stop(); } catch { /* noop */ }
    };
  }, [isSupported, opts.lang]);

  const start = useCallback(() => {
    if (!recRef.current || status === 'listening') return;
    setError(null);
    userStoppedRef.current = false;
    try {
      recRef.current.start();
      // status flips to 'listening' from rec.onstart
    } catch (err) {
      console.warn('[speech] start failed:', err);
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
