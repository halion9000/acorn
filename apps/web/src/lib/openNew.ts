import { useEffect } from 'react';

/** The window events that ask a list page that is already open to show its "new" dialog. */
export const NEW_EVENTS = { case: 'aisoc:new-case', alert: 'aisoc:new-alert' } as const;
export type NewKind = keyof typeof NEW_EVENTS;

/** Whether an address asks for the "new" dialog (?new=1). */
export function wantsNew(search: string): boolean {
  return new URLSearchParams(search).get('new') === '1';
}

/** The same address without the ?new=1 that opened the dialog, every other part kept, so a reload or a shared link does not open it again. */
export function withoutNew(pathname: string, search: string): string {
  const params = new URLSearchParams(search);
  params.delete('new');
  const rest = params.toString();
  return rest ? `${pathname}?${rest}` : pathname;
}

/**
 * Opens a page's "new" dialog when the page is reached with ?new=1 (the palette, from another page) or when the palette asks while the page is already open. The ?new=1 is taken out of the address
 * once it has been read.
 */
export function useOpenOnNew(kind: NewKind, open: () => void): void {
  useEffect(() => {
    if (wantsNew(window.location.search)) {
      open();
      try {
        window.history.replaceState(null, '', withoutNew(window.location.pathname, window.location.search));
      } catch {
        // the address simply stays as it was
      }
    }
    const onAsk = () => open();
    window.addEventListener(NEW_EVENTS[kind], onAsk);
    return () => window.removeEventListener(NEW_EVENTS[kind], onAsk);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- read once when the page opens; `open` is a state setter wrapper
  }, [kind]);
}
