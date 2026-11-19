import { describe, expect, it } from 'vitest';
import { money } from './ProfitabilityView';

describe('money', () => {
  it('writes numbers and the exact decimal text the API sends with a dollar sign and separators', () => {
    expect([money(1234.5), money('29420.00'), money('559632.79'), money(-980), money('-980.5')]).toEqual(['$1,234.50', '$29,420.00', '$559,632.79', '-$980.00', '-$980.50']);
  });
  it('shows a dash for nothing and the text itself for something that is not a number', () => {
    expect([money(null), money(undefined), money(''), money('n/a')]).toEqual(['—', '—', '—', 'n/a']);
  });
});
