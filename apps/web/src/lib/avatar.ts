/**
 * A person's picture. It is saved with their account (the `avatar` preference, see the server's PreferencesPatch), as a small square picture written into the data itself:
 * the browser makes it from the chosen file, so nothing is uploaded to a file store and nothing is fetched from another site.
 */

export const AVATAR_SIZE = 128;
/** The largest file we will even try to read. The picture saved is far smaller (it is cut to a square and shrunk to AVATAR_SIZE). */
export const AVATAR_MAX_FILE_BYTES = 8 * 1024 * 1024;
export const AVATAR_FILE_TYPES = ['image/png', 'image/jpeg', 'image/webp', 'image/gif'] as const;
/** The same limit the server applies. */
export const AVATAR_MAX_CHARS = 100_000;

const AVATAR_PATTERN = /^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/]+={0,2}$/;

/** True for a picture the server would accept (and so one that is safe to put in an image tag). */
export function isAvatar(value: unknown): value is string {
  return typeof value === 'string' && value.length <= AVATAR_MAX_CHARS && AVATAR_PATTERN.test(value);
}

/** The picture saved on an account, or null (nothing, or something that is not a valid picture). */
export function avatarOf(user: { preferences?: Record<string, unknown> } | null | undefined): string | null {
  const value = user?.preferences?.avatar;
  return isAvatar(value) ? value : null;
}

/** The centred square to cut out of a picture of this size. */
export function squareCrop(width: number, height: number): { sx: number; sy: number; side: number } {
  const side = Math.max(1, Math.min(width, height));
  return { sx: Math.floor((width - side) / 2), sy: Math.floor((height - side) / 2), side };
}

export class AvatarError extends Error {}

/** Why a chosen file cannot be used, or null. */
export function avatarFileProblem(file: { type: string; size: number }): string | null {
  if (!(AVATAR_FILE_TYPES as readonly string[]).includes(file.type)) return 'Choose a PNG, JPEG, WebP or GIF picture.';
  if (file.size > AVATAR_MAX_FILE_BYTES) return 'That file is too large. Choose a picture under 8 MB.';
  if (file.size === 0) return 'That file is empty.';
  return null;
}

async function decode(file: File): Promise<{ source: CanvasImageSource; width: number; height: number; close: () => void }> {
  if (typeof createImageBitmap === 'function') {
    const bitmap = await createImageBitmap(file);
    return { source: bitmap, width: bitmap.width, height: bitmap.height, close: () => bitmap.close() };
  }
  const url = URL.createObjectURL(file);
  try {
    const image = new Image();
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new AvatarError('That picture could not be read.'));
      image.src = url;
    });
    return { source: image, width: image.naturalWidth, height: image.naturalHeight, close: () => URL.revokeObjectURL(url) };
  } catch (error) {
    URL.revokeObjectURL(url);
    throw error;
  }
}

/** Cut the chosen picture to a centred square, shrink it to AVATAR_SIZE and return it as a JPEG data address the server accepts. Throws an AvatarError saying what is wrong. */
export async function avatarFromFile(file: File): Promise<string> {
  const problem = avatarFileProblem(file);
  if (problem) throw new AvatarError(problem);
  let decoded;
  try {
    decoded = await decode(file);
  } catch (error) {
    throw error instanceof AvatarError ? error : new AvatarError('That picture could not be read.');
  }
  try {
    const canvas = document.createElement('canvas');
    canvas.width = AVATAR_SIZE;
    canvas.height = AVATAR_SIZE;
    const context = canvas.getContext('2d');
    if (!context) throw new AvatarError('This browser cannot resize pictures.');
    const { sx, sy, side } = squareCrop(decoded.width, decoded.height);
    // A flat background first, so a transparent picture does not turn black when it is saved as a JPEG.
    context.fillStyle = '#ffffff';
    context.fillRect(0, 0, AVATAR_SIZE, AVATAR_SIZE);
    context.drawImage(decoded.source, sx, sy, side, side, 0, 0, AVATAR_SIZE, AVATAR_SIZE);
    for (const quality of [0.9, 0.8, 0.65, 0.5]) {
      const data = canvas.toDataURL('image/jpeg', quality);
      if (isAvatar(data)) return data;
    }
    throw new AvatarError('That picture could not be made small enough.');
  } finally {
    decoded.close();
  }
}
