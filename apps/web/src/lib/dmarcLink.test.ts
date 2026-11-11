import { describe, expect, it } from 'vitest';
import { dmarcHref, domainFromSearch } from './dmarcLink';

describe('dmarcHref and domainFromSearch', () => {
  it('make a link that reads back as the same domain, lower case', () => {
    expect(dmarcHref(' Acme-Dental.COM ')).toBe('/settings/dmarc?domain=acme-dental.com');
    expect(domainFromSearch('?domain=acme-dental.com')).toBe('acme-dental.com');
    expect(domainFromSearch(new URL('http://x' + dmarcHref('Sub.Example.co.uk')).search)).toBe('sub.example.co.uk');
  });

  it('ignores a missing value and anything that is not a host name', () => {
    for (const search of ['', '?x=1', '?domain=', '?domain=localhost', '?domain=a b.com', '?domain=<script>.com', '?domain=http://evil.com', '?domain=a..com', '?domain=-a.com', '?domain=' + 'a'.repeat(300) + '.com']) {
      expect(domainFromSearch(search), search).toBeNull();
    }
  });
});
