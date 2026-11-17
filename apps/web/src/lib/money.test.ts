import { describe, expect, it } from 'vitest';
import { dollars } from '@/lib/money';

describe('dollars', () => {
  it('drops the cents of a whole amount, keeps two digits otherwise, and groups thousands', () => {
    expect([dollars(1200), dollars(1200.5), dollars(0), dollars(1234567.89), dollars(99.99)]).toEqual(['$1,200', '$1,200.50', '$0', '$1,234,567.89', '$99.99']);
  });
});
