// Service worker — keeps the PWA fresh.
// Strategy: network-first for HTML (always get latest), cache-first for assets.
// On every install we bump CACHE version → old caches get wiped on activate.
const CACHE = 'muse-shell-v5';
const SHELL = ['/', '/icon-192.png?v=5', '/icon-512.png?v=5', '/apple-touch-icon.png?v=5'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {})
  );
  // Activate this SW immediately, replacing the previous one.
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)));
    await self.clients.claim();
    // Tell open clients there's a new version.
    const clients = await self.clients.matchAll({ type: 'window' });
    clients.forEach((c) => c.postMessage({ type: 'SW_UPDATED', cache: CACHE }));
  })());
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Never cache backend API or downloads
  if (url.pathname.startsWith('/api/') || url.host.includes('onrender.com')) return;
  if (e.request.method !== 'GET') return;

  // HTML / navigations: ALWAYS network-first (no stale shell)
  if (e.request.mode === 'navigate' || e.request.headers.get('accept')?.includes('text/html')) {
    e.respondWith((async () => {
      try {
        const fresh = await fetch(e.request, { cache: 'no-store' });
        // Update the cached '/' so offline still works
        const cache = await caches.open(CACHE);
        cache.put('/', fresh.clone()).catch(() => {});
        return fresh;
      } catch {
        return (await caches.match('/')) || Response.error();
      }
    })());
    return;
  }

  // Other GETs: cache-first, refill in background
  e.respondWith((async () => {
    const cached = await caches.match(e.request);
    if (cached) return cached;
    try {
      const fresh = await fetch(e.request);
      if (fresh && fresh.ok) {
        const cache = await caches.open(CACHE);
        cache.put(e.request, fresh.clone()).catch(() => {});
      }
      return fresh;
    } catch {
      return Response.error();
    }
  })());
});

// Manual skipWaiting trigger from the page (force-update flow)
self.addEventListener('message', (e) => {
  if (e.data?.type === 'SKIP_WAITING') self.skipWaiting();
});
