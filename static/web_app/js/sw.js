/* SafhaSahar Service Worker
   Scope: '/' (served from the app root via a Django view at /sw.js, not
   from /static/, so its scope covers the whole app — every page, not
   just static assets.)

   Responsibility here is deliberately narrow:
   - Cache the app shell (root HTML + core CSS/JS/logo) so pages that
     were already visited still open when offline (patchy mobile data
     is the whole reason this exists).
   - NEVER intercept POST/PATCH/DELETE — those are left to the browser's
     normal (failing) behavior offline. The "retry later" logic lives in
     page JS (see OfflineQueue in base.html), which is far more reliable
     than trying to replay request bodies from inside a service worker
     via the Background Sync API (spotty support, especially iOS Safari
     — a real concern given the mixed device usage in the field here).
*/

const CACHE_NAME = 'safhasahar-shell-v1';

// Keep this list small and stable — it's meant for "can the app open at
// all offline", not a general asset cache. Runtime caching below handles
// everything else opportunistically as pages are visited.
const APP_SHELL = [
    '/',
    '/static/web_app/css/layout.css',
    '/static/web_app/css/main.css',
    '/static/web_app/js/main.js',
    '/static/web_app/image/SafhaSahar.png',
];

self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            // addAll() fails entirely if even one URL 404s — add
            // individually so one missing/renamed asset (e.g. after a
            // static file rename) doesn't block the whole install.
            return Promise.all(
                APP_SHELL.map((url) =>
                    cache.add(url).catch((err) => {
                        console.warn('SW: failed to precache', url, err);
                    })
                )
            );
        }).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((names) =>
            Promise.all(
                names
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => caches.delete(name))
            )
        ).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', (event) => {
    const req = event.request;

    // Only ever handle GET. Everything else (the API POST/PATCH/DELETE
    // calls the app makes) passes straight through untouched, so the
    // page's own try/catch + OfflineQueue logic sees the real network
    // failure and queues it — the service worker doesn't get involved.
    if (req.method !== 'GET') return;

    const url = new URL(req.url);

    // Never cache API calls or WebSocket upgrades — these must always
    // hit the network (or fail visibly) so badges, notifications, and
    // live driver-location updates behave correctly instead of showing
    // stale cached data.
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) {
        return;
    }

    // Full-page navigations (typing a URL, hard refresh, tapping a
    // bookmark): network-first so users always see fresh content when
    // online, falling back to a cached copy of that exact page if
    // offline, and finally falling back to the cached shell ('/') so at
    // least something renders instead of the browser's offline error page.
    if (req.mode === 'navigate') {
        event.respondWith(
            fetch(req)
                .then((res) => {
                    const copy = res.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
                    return res;
                })
                .catch(() =>
                    caches.match(req).then((cached) => cached || caches.match('/'))
                )
        );
        return;
    }

    // Static assets (css/js/images/fonts): cache-first, refresh the
    // cache in the background from the network when available.
    event.respondWith(
        caches.match(req).then((cached) => {
            const network = fetch(req)
                .then((res) => {
                    if (res && res.status === 200) {
                        const copy = res.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
                    }
                    return res;
                })
                .catch(() => cached); // offline and not cached — nothing we can do

            return cached || network;
        })
    );
});