/** Helpers for sending and saving files in the browser. */

/** The biggest file the server takes (10 MB), so the page can say so before sending. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

/** A size in plain words: 512 B, 4.2 KB, 1.3 MB (pure). */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** The base64 text of a file's bytes, without the "data:...;base64," start. */
export function fileToBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('Could not read that file.'));
    reader.onload = () => {
      const text = String(reader.result ?? '');
      resolve(text.slice(text.indexOf(',') + 1));
    };
    reader.readAsDataURL(file);
  });
}

/** Offer bytes to the person as a file download. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
