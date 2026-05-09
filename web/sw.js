// Minimal service worker — solo para que Muse sea instalable como PWA.
// No cacheamos respuestas porque las descargas son siempre frescas.
const CACHE = 'muse-shell-v3';
const SHELL = ['/', '/icon-192.png?v=3', '/icon-512.png?v=3', '/apple-touch-icon.png?v=3'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).catch(() => {}));
  self.skipWaiting();
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // Nunca cachees el backend ni descargas
  if (url.pathname.startsWith('/api/') || url.host.includes('onrender.com')) return;
  if (e.request.method !== 'GET') return;
  // Network-first para HTML, cache-first para assets
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).catch(() => caches.match('/'))
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then((cached) => cached || fetch(e.request))
  );
});
