'use client';

/**
 * A command prompt for one machine, on an open device that ScreenConnect knows. A.C.O.R.N runs nothing itself: the command is queued for CORE, which sends it through ScreenConnect and brings back what the
 * machine printed (usually within a few seconds, up to half a minute). The machine runs it as SYSTEM, so every command is written to the audit log and one waits at a time.
 */
import { useEffect, useRef, useState } from 'react';
import { apiErrorDetail, devicesApi, type ConsoleLine } from '@/lib/api';

const POLL_MS = 2000;

export function CommandPrompt({ deviceId, hostname }: { deviceId: string; hostname: string }) {
  const [open, setOpen] = useState(false);
  const [lines, setLines] = useState<ConsoleLine[]>([]);
  const [blocked, setBlocked] = useState<string | null>(null);
  const [problem, setProblem] = useState('');
  const [typed, setTyped] = useState('');
  const [recall, setRecall] = useState(-1);
  const end = useRef<HTMLDivElement | null>(null);
  const waiting = lines.some((l) => l.status === 'pending' || l.status === 'claimed');

  useEffect(() => {
    if (!open) return;
    let live = true;
    devicesApi
      .consoleHistory(deviceId)
      .then((h) => {
        if (!live) return;
        setLines(h.lines);
        setBlocked(h.available ? null : h.blocked);
      })
      .catch((e) => live && setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not open the prompt.')));
    return () => {
      live = false;
    };
  }, [open, deviceId]);

  // While a command waits, ask for its answer until it comes.
  useEffect(() => {
    if (!open || !waiting) return;
    const pending = lines.find((l) => l.status === 'pending' || l.status === 'claimed');
    if (!pending) return;
    const timer = setInterval(() => {
      devicesApi
        .consoleLine(pending.request_id)
        .then((fresh) => setLines((all) => all.map((l) => (l.request_id === fresh.request_id ? fresh : l))))
        .catch(() => undefined);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [open, waiting, lines]);

  useEffect(() => {
    end.current?.scrollIntoView?.({ block: 'nearest' });
  }, [lines.length, waiting]);

  const send = async () => {
    const command = typed.trim();
    if (!command || waiting) return;
    setProblem('');
    try {
      const line = await devicesApi.consoleSend(deviceId, command);
      setLines((all) => [...all, line]);
      setTyped('');
      setRecall(-1);
    } catch (e) {
      setProblem(apiErrorDetail(e) ?? (e instanceof Error ? e.message : 'Could not send the command.'));
    }
  };

  const past = lines.map((l) => l.command).reverse();
  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void send();
    } else if (e.key === 'ArrowUp' && past.length > 0) {
      e.preventDefault();
      const next = Math.min(recall + 1, past.length - 1);
      setRecall(next);
      setTyped(past[next]);
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      const next = recall - 1;
      setRecall(next);
      setTyped(next >= 0 ? past[next] : '');
    }
  };

  if (!open) {
    return (
      <div className="mt-3" data-testid="command-prompt">
        <button type="button" onClick={(e) => { e.stopPropagation(); setOpen(true); }} className="rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300 hover:bg-emerald-500/20">
          Open command prompt
        </button>
      </div>
    );
  }
  return (
    <div className="mt-3 rounded-lg border border-gray-700 bg-black" data-testid="command-prompt" onClick={(e) => e.stopPropagation()}>
      <div className="flex items-center justify-between border-b border-gray-800 px-3 py-1.5 text-xs text-gray-400">
        <span>
          Command prompt: <span className="text-gray-200">{hostname}</span> (runs as SYSTEM through ScreenConnect; every command is logged)
        </span>
        <button type="button" onClick={() => setOpen(false)} className="text-gray-500 hover:text-gray-200">
          Close
        </button>
      </div>
      <div className="max-h-72 overflow-y-auto px-3 py-2 font-mono text-xs text-gray-200" data-testid="prompt-lines">
        {blocked && <p className="text-amber-300">{blocked}</p>}
        {lines.length === 0 && !blocked && <p className="text-gray-500">Type a command and press Enter. Up and Down recall earlier ones.</p>}
        {lines.map((l) => (
          <div key={l.request_id} className="mb-2">
            <div className="text-emerald-300">&gt; {l.command}</div>
            {(l.status === 'pending' || l.status === 'claimed') && <div className="text-gray-500">waiting for the machine...</div>}
            {l.status === 'failed' && <div className="whitespace-pre-wrap text-red-300">{l.output || 'The command failed.'}</div>}
            {l.status === 'done' && <div className="whitespace-pre-wrap text-gray-200">{l.output ?? ''}</div>}
          </div>
        ))}
        <div ref={end} />
      </div>
      {problem && (
        <p role="alert" className="px-3 pb-1 text-xs text-red-300">
          {problem}
        </p>
      )}
      <div className="flex items-center gap-2 border-t border-gray-800 px-3 py-1.5 font-mono text-xs">
        <span className="text-emerald-300">&gt;</span>
        <input
          aria-label="Command"
          value={typed}
          disabled={blocked !== null || waiting}
          onChange={(e) => setTyped(e.target.value)}
          onKeyDown={onKey}
          placeholder={waiting ? 'waiting for the machine...' : 'hostname'}
          className="flex-1 bg-transparent text-gray-100 outline-none placeholder:text-gray-600"
          autoComplete="off"
          spellCheck={false}
        />
      </div>
    </div>
  );
}
