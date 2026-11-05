import { describe, expect, it } from 'vitest';
import { CASE_TEMPLATES, templateDescription } from './caseTemplates';

describe('case templates', () => {
  it('have unique ids, a title to finish, a real severity and at least three steps each', () => {
    expect(new Set(CASE_TEMPLATES.map((t) => t.id)).size).toBe(CASE_TEMPLATES.length);
    for (const t of CASE_TEMPLATES) {
      expect(['critical', 'high', 'medium', 'low'], t.id).toContain(t.severity);
      expect(t.title.length, t.id).toBeGreaterThan(5);
      expect(t.steps.length, t.id).toBeGreaterThanOrEqual(3);
    }
  });
  it('write the steps as a checklist', () => {
    expect(templateDescription({ id: 'x', label: 'X', title: 'X: ', severity: 'low', steps: ['one', 'two'] })).toBe('Steps:\n- [ ] one\n- [ ] two');
  });
});
