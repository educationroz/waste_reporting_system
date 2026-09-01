const CACHE_NAME = 'waste-management-v1';

// Install event - cache the app shell
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll([
                '/',
                '/static/web_app/css/style.css',
                '/static/web_app/js/main.js',
            ]).catch(() => {
                // Ignore cache.addAll failures (e.g., if a file is temporarily missing)
            });
        })
    );
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter((name) => name !== CACHE_NAME)
                    .map((name) => caches.delete(name))
            );
        })
    );
    self.clients.claim();
});

// Fetch event
self.addEventListener('fetch', (event) => {
    const req = event.request;

    // Only handle GET requests
    if (req.method !== 'GET') return;

    const url = new URL(req.url);

    // SKIP caching for unsupported schemes (chrome-extension, blob, data, etc.)
    if (url.protocol === 'chrome-extension:' || 
        url.protocol === 'chrome:' ||
        url.protocol === 'extension:' ||
        url.protocol === 'about:' ||
        url.protocol === 'blob:' ||
        url.protocol === 'data:') {
        return;
    }

    // Never cache API calls or WebSocket upgrades
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) {
        return;
    }

    // Only handle same-origin requests. Cross-origin resources (OpenStreetMap
    // tiles, CDN scripts, Google fonts) must NOT be proxied or cached by the
    // service worker: doing so triggers CSP connect-src blockages (fetch() in
    // a SW is governed by connect-src, and third-party hosts aren't listed
    // there) and bloats the cache with thousands of third-party files.
    if (url.origin !== location.origin) {
        return;
    }

    // Full-page navigations: network-first
    if (req.mode === 'navigate') {
        event.respondWith(
            fetch(req)
                .then((res) => {
                    // Only cache successful responses
                    if (res && res.status === 200) {
                        const copy = res.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(req, copy).catch(() => {
                                // Silently ignore caching errors (e.g., CSP blocks)
                            });
                        });
                    }
                    return res;
                })
                .catch(() =>
                    caches.match(req).then(
                        (cached) =>
                            cached ||
                            caches.match('/') ||
                            new Response('Offline', {
                                status: 503,
                                statusText: 'Service Unavailable',
                                headers: { 'Content-Type': 'text/plain' },
                            })
                    )
                )
        );
        return;
    }

    // Static assets: cache-first, refresh in background
    event.respondWith(
        caches.match(req).then((cached) => {
            const network = fetch(req)
                .then((res) => {
                    // Only cache successful responses
                    if (res && res.status === 200) {
                        const copy = res.clone();
                        caches.open(CACHE_NAME).then((cache) => {
                            cache.put(req, copy).catch(() => {
                                // Silently ignore caching errors
                            });
                        });
                    }
                    return res;
                })
                .catch(() => cached); // Return cached version if network fails

            return cached || network;
        })
    );
});