/**
 * Realtime WebSocket client for A.C.O.R.N.
 *
 * Wraps the `realtime` service (port 8086) with a small typed hook that
 * handles automatic reconnection, JSON parsing, and channel subscription.
 *
 * Usage:
 *
 *   const { last, send, status } = useRealtimeChannel<Alert>('alerts');
 *
 * The hook returns the latest decoded message plus a `send` callback for
 * outbound control frames (subscribe / unsubscribe / ping).
 */

'use client';

import { useEffect, useRef, useState } from 'react';
import { realtimeApi } from './api';

export type RealtimeChannel = 'alerts' | 'cases' | 'agents' | 'insights' | 'all';
export type RealtimeStatus =
  | 'connecting'
  | 'open'
  | 'closing'
  | 'closed'
  | 'error';

interface UseRealtimeOptions {
  /** When false the hook is a no-op — useful for SSR / disabled features. */
  enabled?: boolean;
  /** Override the URL (e.g. tests). Defaults to `realtimeApi.channelUrl`. */
  url?: string;
  /** Reconnect backoff cap in ms. */
  maxBackoffMs?: number;
  /** How long the ticket request and the opening of the socket may each take before it counts as a failed try. */
  connectTimeoutMs?: number;
}

interface UseRealtimeResult<T> {
  status: RealtimeStatus;
  last: T | null;
  history: T[];
  /** Why the last try failed, in words a person can act on; null while connected or before any failure. */
  problem: string | null;
  /** Which step the current try is on, and which try it is (1 for the first), so a stuck "connecting" can say where it is stuck. */
  step: { name: 'ticket' | 'socket'; attempt: number } | null;
  send: (message: unknown) => void;
  reset: () => void;
}

const DEFAULT_HISTORY = 50;

export function useRealtimeChannel<T = unknown>(
  channel: RealtimeChannel,
  options: UseRealtimeOptions = {},
): UseRealtimeResult<T> {
  const { enabled = true, url, maxBackoffMs = 15_000, connectTimeoutMs = 10_000 } = options;
  const [status, setStatus] = useState<RealtimeStatus>('connecting');
  const [last, setLast] = useState<T | null>(null);
  const [history, setHistory] = useState<T[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [step, setStep] = useState<{ name: 'ticket' | 'socket'; attempt: number } | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectRef = useRef<number>(0);

  useEffect(() => {
    if (!enabled || typeof window === 'undefined') return;
    // Local to THIS run of the effect. A flag shared between runs let a reconnect timer left over from the previous channel see "not cancelled" once the next run reset it, and open a second connection for the old channel.
    let cancelled = false;
    let timer: number | undefined;
    let watchdog: number | undefined;
    let tries = 0;
    const retryLater = (delay: number) => {
      timer = window.setTimeout(connect, delay);
    };
    const retryWithBackoff = () => {
      const attempt = reconnectRef.current + 1;
      reconnectRef.current = attempt;
      retryLater(Math.min(1000 * 2 ** Math.min(attempt, 6), maxBackoffMs));
    };

    async function connect() {
      if (cancelled) return;
      setStatus('connecting');
      const attempt = tries + 1;
      tries = attempt;
      setStep({ name: 'ticket', attempt });

      // Mint a fresh short-lived ticket and attach it as `?token=` immediately
      // before opening the socket (Issue #239). On reconnect this re-mints, so
      // an expired ticket never blocks recovery. A test-supplied `url` override
      // bypasses ticketing.
      let target: string;
      try {
        target = url ?? (await withTimeout(realtimeApi.channelUrl(channel), connectTimeoutMs, 'ticket'));
      } catch (e) {
        // Could not authenticate (e.g. signed-out, or realtime ticketing is
        // not configured server-side → 503). Surface as error and retry with
        // backoff rather than opening an unauthenticated socket.
        if (cancelled) return;
        setStatus('error');
        setProblem(
          e instanceof TimeoutError
            ? `Asking for a connection ticket took more than ${Math.round(connectTimeoutMs / 1000)} seconds.`
            : `Could not get a connection ticket${e instanceof Error && e.message ? ` (${e.message.slice(0, 120)})` : ''}.`,
        );
        retryWithBackoff();
        return;
      }
      if (cancelled) return;

      setStep({ name: 'socket', attempt });
      let ws: WebSocket;
      try {
        ws = new WebSocket(target);
      } catch (e) {
        // The browser refuses some addresses before trying anything (an insecure ws:// address from an https page, a malformed address). That used to be an unhandled error and the panel sat on "connecting"
        // for good; say what happened and try again.
        if (cancelled) return;
        setStatus('error');
        const why = String((e as { message?: unknown } | null)?.message ?? '').slice(0, 140);
        setProblem(`The browser refused to open the live connection${why ? ` (${why})` : ''}.`);
        retryWithBackoff();
        return;
      }
      wsRef.current = ws;

      // A socket that never opens (a proxy holding the upgrade, a blocked port) stays "connecting" for a long time and says nothing; give it a limit and say what happened.
      watchdog = window.setTimeout(() => {
        if (cancelled || ws.readyState === WebSocket.OPEN) return;
        setProblem(`The live connection did not open within ${Math.round(connectTimeoutMs / 1000)} seconds.`);
        setStatus('error');
        ws.onclose = null; // this try is over; the retry is scheduled here, once, not by the socket's own close event
        ws.onerror = null;
        ws.close();
        retryWithBackoff();
      }, connectTimeoutMs);

      ws.onopen = () => {
        window.clearTimeout(watchdog);
        reconnectRef.current = 0;
        setProblem(null);
        setStep(null);
        setStatus('open');
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as T;
          setLast(data);
          setHistory((prev) => {
            const next = [data, ...prev];
            return next.slice(0, DEFAULT_HISTORY);
          });
        } catch {
          // Non-JSON frames are silently dropped — surface as last-string?
        }
      };

      ws.onerror = () => {
        setStatus('error');
        setProblem((prev) => prev ?? 'The live connection was refused or dropped.');
      };

      ws.onclose = () => {
        window.clearTimeout(watchdog);
        if (cancelled) return;
        setStatus('closed');
        retryWithBackoff();
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
      if (watchdog !== undefined) window.clearTimeout(watchdog);
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        setStatus('closing');
        ws.close();
      } else if (ws && ws.readyState === WebSocket.CONNECTING) {
        // Still opening: close it too, or it connects after nobody is listening.
        ws.close();
      }
    };
  }, [channel, enabled, url, maxBackoffMs]);

  function send(message: unknown) {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    ws.send(typeof message === 'string' ? message : JSON.stringify(message));
  }

  function reset() {
    setLast(null);
    setHistory([]);
  }

  return { status, last, history, problem, step, send, reset };
}

class TimeoutError extends Error {}

function withTimeout<V>(work: Promise<V>, ms: number, what: string): Promise<V> {
  return new Promise<V>((resolve, reject) => {
    const t = window.setTimeout(() => reject(new TimeoutError(what)), ms);
    work.then(
      (v) => {
        window.clearTimeout(t);
        resolve(v);
      },
      (e) => {
        window.clearTimeout(t);
        reject(e);
      },
    );
  });
}
