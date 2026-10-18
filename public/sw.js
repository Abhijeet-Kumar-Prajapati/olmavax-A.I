const CACHE = 'olmavax-v32';
const SHELL = ['/', '/index.html', '/style.css', '/app.js', '/i18n.js', '/highlight.js',
               '/icon.svg', '/logo.svg', '/logo-mark.svg', '/manifest.webmanifest'];

self.addEventListener('install', e => e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting())));
self.addEventListener('activate', e => e.waitUntil(
  caches.keys().then(k => Promise.all(k.filter(x => x !== CACHE).map(x => caches.delete(x)))).then(() => self.clients.claim())
));

// Network-first for everything: always the newest code, offline still works
// from the cache we just refreshed.
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return;
  if (u.pathname.startsWith('/api/') || e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request)
      .then(r => { const cp = r.clone(); caches.open(CACHE).then(c => c.put(e.request, cp)); return r; })
      .catch(() => caches.match(e.request).then(hit => hit || caches.match('/index.html')))
  );
});
