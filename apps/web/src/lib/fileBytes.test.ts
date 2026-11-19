import { describe, expect, it } from 'vitest';
import { MAX_UPLOAD_BYTES, fileToBase64, formatSize } from './fileBytes';

describe('formatSize', () => {
  it('says bytes, kilobytes and megabytes in plain words', () => {
    expect([formatSize(0), formatSize(512), formatSize(2048), formatSize(1536 * 1024), formatSize(MAX_UPLOAD_BYTES)]).toEqual(['0 B', '512 B', '2.0 KB', '1.5 MB', '10.0 MB']);
  });
});

describe('fileToBase64', () => {
  it('gives the base64 text of the bytes without the data-URL start', async () => {
    expect(await fileToBase64(new Blob(['hello']))).toBe(btoa('hello'));
    expect(await fileToBase64(new Blob([]))).toBe('');
  });
});
