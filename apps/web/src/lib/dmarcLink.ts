/** The DMARC page opened on one domain: Settings > DMARC reports, with that domain's detail already showing. */
export function dmarcHref(domain: string): string {
  return `/settings/dmarc?domain=${encodeURIComponent(domain.trim().toLowerCase())}`;
}

// A host name: labels of letters, digits and hyphens joined by dots, 255 characters at most. Anything else in the address is ignored rather than used.
const HOST = /^(?=.{1,255}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

/** The domain asked for in a page address (`?domain=example.com`), lower case, or null when there is none or it is not a host name. */
export function domainFromSearch(search: string): string | null {
  const raw = new URLSearchParams(search).get('domain');
  const value = (raw ?? '').trim().toLowerCase();
  return HOST.test(value) ? value : null;
}
