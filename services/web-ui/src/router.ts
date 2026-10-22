import { useSyncExternalStore } from 'react';

/**
 * A small hash router. Hash URLs work unchanged on GitHub Pages (no 404 fallback needed) and
 * behind nginx, and keep the app free of a router dependency.
 */
export interface Route {
  /** Path without query, always starting with "/". */
  path: string;
  segments: string[];
  query: URLSearchParams;
}

function readRoute(): Route {
  const raw = window.location.hash.replace(/^#/, '') || '/';
  const [pathPart = '/', queryPart = ''] = raw.split('?', 2);
  const path = pathPart.startsWith('/') ? pathPart : `/${pathPart}`;
  const segments = path
    .split('/')
    .filter(Boolean)
    .map((s) => {
      try {
        return decodeURIComponent(s);
      } catch {
        return s;
      }
    });
  return { path, segments, query: new URLSearchParams(queryPart) };
}

let cached: { hash: string; route: Route } | null = null;

function getSnapshot(): Route {
  const hash = window.location.hash;
  if (!cached || cached.hash !== hash) cached = { hash, route: readRoute() };
  return cached.route;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener('hashchange', onChange);
  return () => window.removeEventListener('hashchange', onChange);
}

export function useRoute(): Route {
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

/** Build an app path from segments and query values (empty values are dropped). */
export function buildPath(
  segments: readonly string[],
  query: Record<string, string | number | null | undefined> = {},
): string {
  const path = '/' + segments.map((s) => encodeURIComponent(s)).join('/');
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined && value !== '') params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

export function navigate(to: string, options: { replace?: boolean } = {}): void {
  const hash = `#${to}`;
  if (options.replace) {
    window.history.replaceState(null, '', hash);
    window.dispatchEvent(new HashChangeEvent('hashchange'));
  } else {
    window.location.hash = to;
  }
}

export function hrefFor(to: string): string {
  return `#${to}`;
}
