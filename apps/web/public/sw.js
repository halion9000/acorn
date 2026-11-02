/*
 * The phone Responder app was removed (2026-11-02). Browsers that installed it still hold the old service worker, which kept serving
 * an "offline" page. This replacement removes itself: it clears every cache, unregisters, and reloads the open pages so they load
 * from the network. It can be deleted once no browser still has the old worker.
 */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
      await self.registration.unregister();
      const clients = await self.clients.matchAll({ type: 'window' });
      clients.forEach((c) => c.navigate(c.url));
    })(),
  );
});
self.addEventListener('fetch', () => {
  /* never intercept: everything goes to the network */
});
