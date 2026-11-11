/** Other words people use for a sidebar page, by its address, so typing "billing" or "2fa" in the palette finds the page that is called something else. */
export const PAGE_WORDS: Record<string, string[]> = {
  '/settings/billing': ['billing', 'invoice', 'invoices', 'licences', 'licenses', 'seats', 'counts', 'charges', 'margin'],
  '/settings/mfa': ['mfa', '2fa', 'two-factor', 'second factor', 'authenticator', 'multi factor'],
  '/settings/secure-score': ['secure score', 'microsoft score', 'posture score'],
  '/settings/signin-scores': ['sign-in', 'signin', 'login', 'risky sign-ins'],
  '/settings/dmarc': ['dmarc', 'spf', 'dkim', 'email authentication', 'spoofing'],
  '/settings/client-posture': ['posture', 'checks', 'nist', 'compliance checks'],
  '/settings/fleet-posture': ['fleet', 'devices posture', 'patching'],
  '/settings/client-docs': ['documentation', 'it glue', 'runbooks'],
  '/vulnerabilities': ['cve', 'patching', 'unpatched', 'end of support'],
  '/inventory': ['stock', 'checkout', 'spares', 'hardware'],
  '/reports/digest': ['executive digest', 'weekly', 'summary', 'report'],
  '/reports/client-review': ['qbr', 'client review', 'quarterly'],
  '/honeytokens': ['canary', 'decoy', 'tripwire'],
  '/fim': ['file integrity', 'file changes'],
  '/devices/environment': ['network map', 'drawing', 'diagram', 'topology'],
  '/remote-tools': ['remote access', 'screen share', 'rmm'],
};

export interface PaletteNavItem {
  label: string;
  href: string;
  keywords: string[];
}

/**
 * The palette's page list: the curated entries as they are, then every other sidebar page (in sidebar order, once each) with its label and the extra words above. A page the person's role
 * hides is not in `sections` and so is not offered.
 */
export function paletteNavItems(
  curated: PaletteNavItem[],
  sections: { items: { label: string; href: string }[] }[],
): PaletteNavItem[] {
  const seen = new Set(curated.map((c) => c.href));
  const extra: PaletteNavItem[] = [];
  for (const section of sections) {
    for (const item of section.items) {
      if (seen.has(item.href)) continue;
      seen.add(item.href);
      extra.push({ label: item.label, href: item.href, keywords: PAGE_WORDS[item.href] ?? [] });
    }
  }
  const words = (c: PaletteNavItem): PaletteNavItem => ({ ...c, keywords: [...c.keywords, ...(PAGE_WORDS[c.href] ?? []).filter((w) => !c.keywords.includes(w))] });
  return [...curated.map(words), ...extra];
}
