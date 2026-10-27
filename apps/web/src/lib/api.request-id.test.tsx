/** A failed call keeps the API's X-Request-ID so the error screen can show it, and a malformed one is dropped. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ApiError, tenantsApi } from './api';
import { AUTH_TOKEN_KEY } from './auth-session';
import { ErrorState } from '@/components/ui/ErrorState';

function respondWith(requestId: string | null) {
  vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ detail: 'nope' }), { status: 500, headers: { 'Content-Type': 'application/json', ...(requestId ? { 'X-Request-ID': requestId } : {}) } }));
}
async function failure(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (e) {
    return e as ApiError;
  }
  throw new Error('expected the call to fail');
}

beforeEach(() => {
  window.localStorage.clear();
  window.localStorage.setItem(AUTH_TOKEN_KEY, 'tok1');
});
afterEach(() => vi.unstubAllGlobals());

describe('the request id on a failed call', () => {
  it('is kept on the ApiError, and left off when the API sent none', async () => {
    respondWith('req-abc_123.4');
    expect((await failure(tenantsApi.me())).requestId).toBe('req-abc_123.4');
    respondWith(null);
    expect((await failure(tenantsApi.me())).requestId).toBeUndefined();
  });
  it('is dropped when it is not a plain id (nothing odd is ever shown)', async () => {
    respondWith('<script>alert(1)</script>');
    expect((await failure(tenantsApi.me())).requestId).toBeUndefined();
  });
  it('shows on the error screen as a reference, and not for an error without one', () => {
    const err = new ApiError('API 500', 500, '', undefined, 'req-9f');
    const { rerender } = render(<ErrorState error={err} />);
    expect(screen.getByTestId('request-id').textContent).toBe('Reference: req-9f');
    rerender(<ErrorState error={new ApiError('API 500', 500, '')} />);
    expect(screen.queryByTestId('request-id')).toBeNull();
    rerender(<ErrorState error="a plain string" />);
    expect(screen.queryByTestId('request-id')).toBeNull();
  });
});
