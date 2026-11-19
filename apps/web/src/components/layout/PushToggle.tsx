'use client';

/** Turn push notifications for critical alerts on or off for this browser (roadmap r7-af-39). The browser asks permission; the server keeps the subscription. */
import { useEffect, useState } from 'react';

import { authFetch } from '@/lib/auth-session';

/** The key as the browser's subscribe call wants it: URL-safe base64 text to bytes (pure). */
export function keyBytes(text: string): Uint8Array {
  const raw = atob((text + '='.repeat((4 - (text.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** What to show for the browser's state (pure): unsupported, blocked, on or off. */
export function pushLabel(supported: boolean, permission: string, subscribed: boolean): { text: string; canToggle: boolean } {
  if (!supported) return { text: 'This browser cannot show push notifications.', canToggle: false };
  if (permission === 'denied') return { text: 'Notifications are blocked for this site in the browser settings.', canToggle: false };
  return { text: subscribed ? 'Critical alerts are pushed to this device. Turn off' : 'Push critical alerts to this device', canToggle: true };
}

const supportedHere = (): boolean => typeof window !== 'undefined' && 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;

export function PushToggle() {
  const [subscribed, setSubscribed] = useState(false);
  const [permission, setPermission] = useState('default');
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const supported = supportedHere();

  useEffect(() => {
    if (!supported) return;
    setPermission(Notification.permission);
    void navigator.serviceWorker
      .getRegistration('/push-sw.js')
      .then((reg) => reg?.pushManager.getSubscription())
      .then((sub) => setSubscribed(Boolean(sub)))
      .catch(() => undefined);
  }, [supported]);

  const toggle = async () => {
    setBusy(true);
    setProblem(null);
    try {
      const reg = (await navigator.serviceWorker.getRegistration('/push-sw.js')) ?? (await navigator.serviceWorker.register('/push-sw.js'));
      const existing = await reg.pushManager.getSubscription();
      if (existing) {
        await authFetch('/api/v1/alert-push/unsubscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: existing.endpoint }) });
        await existing.unsubscribe();
        setSubscribed(false);
        return;
      }
      const asked = await Notification.requestPermission();
      setPermission(asked);
      if (asked !== 'granted') return;
      const key = (await (await authFetch('/api/v1/alert-push/public-key')).json()) as { public_key: string };
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key.public_key) as BufferSource });
      const json = sub.toJSON() as { endpoint?: string; keys?: { p256dh?: string; auth?: string } };
      const res = await authFetch('/api/v1/alert-push/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: json.endpoint, keys: json.keys }) });
      if (!res.ok) throw new Error('The server did not accept the subscription.');
      setSubscribed(true);
    } catch (e) {
      setProblem(e instanceof Error && e.message ? e.message : 'Could not change notifications.');
    } finally {
      setBusy(false);
    }
  };

  const label = pushLabel(supported, permission, subscribed);
  return (
    <div className="px-4 py-2.5 border-t border-gray-800" data-testid="push-toggle">
      {label.canToggle ? (
        <button type="button" disabled={busy} onClick={() => void toggle()} className="text-sm text-blue-400 hover:underline disabled:opacity-50">
          {label.text}
        </button>
      ) : (
        <p className="text-xs text-gray-500">{label.text}</p>
      )}
      {problem && (
        <p role="alert" className="mt-1 text-xs text-red-300">
          {problem}
        </p>
      )}
    </div>
  );
}
