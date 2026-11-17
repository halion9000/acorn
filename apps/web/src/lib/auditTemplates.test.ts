import { describe, expect, it } from 'vitest';
import { missingRequests, templateFor } from '@/lib/auditTemplates';

describe('audit request templates', () => {
  it('has a list for each framework the Controls page offers, with no empty or repeated title', () => {
    for (const f of ['SOC2', 'ISO27001', 'NIST-CSF', 'PCI-DSS', 'HIPAA', 'CIS-IG1']) {
      const list = templateFor(f);
      expect(list.length, f).toBeGreaterThanOrEqual(10);
      const titles = list.map((r) => r.title.trim().toLowerCase());
      expect(titles.every((x) => x.length >= 3)).toBe(true);
      expect(new Set(titles).size).toBe(titles.length);
    }
  });

  it('finds a framework however it is written, and knows none for an unknown one', () => {
    expect(templateFor('soc 2')).toEqual(templateFor('SOC2'));
    expect(templateFor('pci_dss')).toEqual(templateFor('PCI-DSS'));
    expect(templateFor('Made Up')).toEqual([]);
    expect(templateFor('')).toEqual([]);
  });

  it('leaves out what the audit already asks for, ignoring case and spacing, and returns all when it has none', () => {
    const all = templateFor('SOC2');
    const first = all[0]!.title;
    const rest = missingRequests('SOC2', [`  ${first.toUpperCase()}  `, 'Something else entirely']);
    expect(rest).toHaveLength(all.length - 1);
    expect(rest.map((r) => r.title)).not.toContain(first);
    expect(missingRequests('SOC2', [])).toEqual(all);
    expect(missingRequests('Nope', [])).toEqual([]);
  });
});
