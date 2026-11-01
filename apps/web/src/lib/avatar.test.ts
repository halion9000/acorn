import { afterEach, describe, expect, it, vi } from 'vitest';
import { AVATAR_MAX_CHARS, AVATAR_MAX_FILE_BYTES, AVATAR_SIZE, AvatarError, avatarFileProblem, avatarFromFile, avatarOf, isAvatar, squareCrop } from './avatar';

const PNG = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';
const file = (type: string, size = 1000) => ({ type, size }) as File;

afterEach(() => vi.restoreAllMocks());

describe('isAvatar and avatarOf: only a picture the server would accept', () => {
  it('accepts a small PNG, JPEG or WebP data address', () => {
    expect(isAvatar(PNG)).toBe(true);
    expect(isAvatar('data:image/jpeg;base64,/9j/4AAQSkZJRg==')).toBe(true);
    expect(isAvatar('data:image/webp;base64,UklGRg==')).toBe(true);
  });

  it('refuses links, SVGs, scripts, junk and anything over the length limit', () => {
    for (const bad of ['https://x.example/a.png', 'data:image/svg+xml;base64,PHN2Zz4=', 'javascript:alert(1)', 'data:image/png;base64,@@@', '', 5, null, undefined, {}]) expect(isAvatar(bad)).toBe(false);
    expect(isAvatar('data:image/png;base64,' + 'A'.repeat(AVATAR_MAX_CHARS))).toBe(false);
  });

  it('reads the picture off an account, ignoring anything that is not one', () => {
    expect(avatarOf({ preferences: { avatar: PNG } })).toBe(PNG);
    expect(avatarOf({ preferences: { avatar: 'https://x.example/a.png' } })).toBeNull();
    expect(avatarOf({ preferences: {} })).toBeNull();
    expect(avatarOf({})).toBeNull();
    expect(avatarOf(null)).toBeNull();
  });
});

describe('squareCrop: the centred square', () => {
  it('cuts the middle of a wide, a tall and a square picture', () => {
    expect(squareCrop(400, 200)).toEqual({ sx: 100, sy: 0, side: 200 });
    expect(squareCrop(200, 500)).toEqual({ sx: 0, sy: 150, side: 200 });
    expect(squareCrop(64, 64)).toEqual({ sx: 0, sy: 0, side: 64 });
  });
  it('never gives a side of zero', () => {
    expect(squareCrop(0, 0).side).toBe(1);
  });
});

describe('avatarFileProblem', () => {
  it('says what is wrong with a file, and is quiet about a good one', () => {
    expect(avatarFileProblem(file('image/png'))).toBeNull();
    expect(avatarFileProblem(file('image/jpeg'))).toBeNull();
    expect(avatarFileProblem(file('image/gif'))).toBeNull();
    expect(avatarFileProblem(file('application/pdf'))).toMatch(/PNG, JPEG, WebP or GIF/);
    expect(avatarFileProblem(file('image/svg+xml'))).toMatch(/PNG, JPEG, WebP or GIF/);
    expect(avatarFileProblem(file('image/png', AVATAR_MAX_FILE_BYTES + 1))).toMatch(/too large/);
    expect(avatarFileProblem(file('image/png', 0))).toMatch(/empty/);
  });
});

describe('avatarFromFile', () => {
  it('refuses a wrong file before reading it', async () => {
    await expect(avatarFromFile(file('application/pdf'))).rejects.toBeInstanceOf(AvatarError);
  });

  it('cuts the middle square, draws it at the avatar size on a white background, and returns what the server accepts', async () => {
    const draw = vi.fn();
    const fill = vi.fn();
    const context = { fillStyle: '', fillRect: fill, drawImage: draw };
    const canvas = { width: 0, height: 0, getContext: () => context, toDataURL: vi.fn(() => PNG.replace('png', 'jpeg')) };
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => (tag === 'canvas' ? canvas : document.createElementNS('http://www.w3.org/1999/xhtml', tag))) as never);
    const close = vi.fn();
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 400, height: 200, close })));
    const out = await avatarFromFile(file('image/png'));
    expect(isAvatar(out)).toBe(true);
    expect([canvas.width, canvas.height]).toEqual([AVATAR_SIZE, AVATAR_SIZE]);
    expect(draw).toHaveBeenCalledWith(expect.anything(), 100, 0, 200, 200, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
    expect(fill).toHaveBeenCalledWith(0, 0, AVATAR_SIZE, AVATAR_SIZE);
    expect(close).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('says so when the picture cannot be read', async () => {
    vi.stubGlobal('createImageBitmap', vi.fn(async () => Promise.reject(new Error('bad'))));
    await expect(avatarFromFile(file('image/png'))).rejects.toThrow(/could not be read/);
    vi.unstubAllGlobals();
  });

  it('tries a smaller quality when the first is too big for the server', async () => {
    const big = 'data:image/jpeg;base64,' + 'A'.repeat(AVATAR_MAX_CHARS + 10);
    const results = [big, big, 'data:image/jpeg;base64,/9j/4AAQ'];
    const canvas = { width: 0, height: 0, getContext: () => ({ fillStyle: '', fillRect: vi.fn(), drawImage: vi.fn() }), toDataURL: vi.fn(() => results.shift() as string) };
    vi.spyOn(document, 'createElement').mockImplementation(((tag: string) => (tag === 'canvas' ? canvas : document.createElementNS('http://www.w3.org/1999/xhtml', tag))) as never);
    vi.stubGlobal('createImageBitmap', vi.fn(async () => ({ width: 10, height: 10, close: vi.fn() })));
    expect(await avatarFromFile(file('image/jpeg'))).toBe('data:image/jpeg;base64,/9j/4AAQ');
    expect(canvas.toDataURL).toHaveBeenCalledTimes(3);
    vi.unstubAllGlobals();
  });
});
