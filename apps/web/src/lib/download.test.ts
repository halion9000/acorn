import { afterEach, describe, expect, it, vi } from 'vitest';
import { downloadText } from './download';

afterEach(() => vi.restoreAllMocks());

describe('downloadText', () => {
  it('saves the text under the file name with the given type, and leaves nothing behind in the page', async () => {
    const blobs: Blob[] = [];
    const revoked = vi.fn();
    Object.assign(URL, { createObjectURL: vi.fn((b: Blob) => { blobs.push(b); return 'blob:x'; }), revokeObjectURL: revoked });
    const saved: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      saved.push(`${this.download}|${this.href}|${document.body.contains(this)}`);
    });
    const before = document.body.querySelectorAll('a').length;
    downloadText('report.json', '{"a":1}', 'application/json');
    expect(saved).toEqual(['report.json|blob:x|true']);
    expect(blobs[0].type).toBe('application/json');
    expect(await blobs[0].text()).toBe('{"a":1}');
    expect(revoked).toHaveBeenCalledWith('blob:x');
    expect(document.body.querySelectorAll('a').length).toBe(before);
  });
});
