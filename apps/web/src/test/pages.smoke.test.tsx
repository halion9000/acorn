/**
 * Render smoke test for every page file: each page of the console is rendered once while the API is down (every call answers 503), and none may throw. A page that crashes on a failed
 * call shows a blank screen instead of saying it could not load; this finds it before a client does.
 *
 * What is mocked: the router and address, and the API (every call answers 503). A page that redirects, or a
 * server-only page that renders nothing here, counts as fine. Only a thrown error while rendering fails a page, and the test names every page that did.
 */
import { act, cleanup, render } from '@testing-library/react';
import { Suspense } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('next/navigation', () => {
  const params = new URLSearchParams();
  return {
    useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn(), refresh: vi.fn(), prefetch: vi.fn() }),
    usePathname: () => '/',
    useSearchParams: () => params,
    useParams: () => ({ framework: 'soc2', id: 'x', slug: 'x', client: 'x' }),
    redirect: () => {
      throw new Error('NEXT_REDIRECT');
    },
    permanentRedirect: () => {
      throw new Error('NEXT_REDIRECT');
    },
    notFound: () => {
      throw new Error('NEXT_NOT_FOUND');
    },
  };
});
vi.mock('next/link', () => ({ default: ({ children, href, ...rest }: { children: React.ReactNode; href: string } & Record<string, unknown>) => <a href={String(href)} {...(rest as object)}>{children}</a> }));
vi.mock('next/image', () => ({ default: ({ alt }: { alt: string }) => <span role="img" aria-label={alt} /> }));

// The API is down: every call answers 503. A page must show that it could not load, not crash.
const answer = () => Promise.resolve(new Response(JSON.stringify({ detail: 'The server is not available.' }), { status: 503, headers: { 'content-type': 'application/json' } }));
vi.mock('@/lib/auth-session', async (importOriginal) => {
  const real = await importOriginal<Record<string, unknown>>();
  return { ...real, authFetch: () => answer() };
});

const pages = import.meta.glob('../app/**/page.tsx');

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('every page survives the API being down', () => {
  it('has a page to test', () => {
    expect(Object.keys(pages).length).toBeGreaterThan(50);
  });

  it('no page throws while rendering when every API call fails', async () => {
    vi.stubGlobal('fetch', () => answer());
    vi.spyOn(console, 'error').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    const crashed: string[] = [];
    for (const [file, load] of Object.entries(pages)) {
      const name = file.replace('../app/', '').replace('/page.tsx', '') || '/';
      try {
        const mod = (await load()) as { default?: unknown };
        const Page = mod.default as React.ComponentType<Record<string, unknown>> | undefined;
        if (typeof Page !== 'function') continue;
        // Server pages that wait on data (async) cannot be rendered here; they have no client code to crash.
        if (Page.constructor.name === 'AsyncFunction') continue;
        render(
          <Suspense fallback={null}>
            <Page params={{ framework: 'soc2', id: 'x' }} searchParams={{}} />
          </Suspense>,
        );
        // Let the failed answers arrive, so a page that crashes on one does it here and is named.
        await act(async () => {
          await new Promise((r) => setTimeout(r, 15));
        });
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (/NEXT_REDIRECT|NEXT_NOT_FOUND/.test(msg)) continue;
        crashed.push(`${name}: ${msg.split('\n')[0]!.slice(0, 160)}`);
      } finally {
        cleanup();
      }
    }
    expect(crashed).toEqual([]);
  }, 240_000);
});
