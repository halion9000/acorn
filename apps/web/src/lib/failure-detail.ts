/** The server's own explanation of a failed response (its `detail`), or the bare status when it gave none. */
export async function failureDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string' && body.detail) return body.detail;
  } catch {
    /* not JSON: fall through to the status */
  }
  return `HTTP ${res.status}`;
}
