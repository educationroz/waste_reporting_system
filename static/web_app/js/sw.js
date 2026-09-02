const CACHE_NAME = 'waste-management-v2';

// ── Offline route caching ──────────────────────────────────────────────────
// GET endpoints the driver dashboard reads to draw the route map and its
// performance stats. Responses to these are cached stale-while-revalidate so
// the map/stats can still render (from the last-good snapshot) on patchy
// mobile data or full offline. Only 200 responses are saved; backend scopes
// each response to the authenticated driver, so nothing cross-leaks.
const ROUTE_API_PREFIXES = [
    '/api/waste-requests/',
    '/api/routes/',
    '/api/checkpoints/',
    '/api/drivers/',
];

function isRouteApiRequest(requestUrl) {
    if (!requestUrl || !requestUrl.pathname) return false;
    return ROUTE_API_PREFIXES.some((prefix) =>
        requestUrl.pathname.startsWith(prefix)
    );
}

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

// ── Web Push (VAPID) ──────────────────────────────────────────────────────
// The backend sends a small JSON envelope via send_web_push(); parse it so we
// can show a notification and, on click, open the right page. The title/body
// can also arrive as plain text from services that only support string data.
self.addEventListener('push', (event) => {
    let data = {};
    try {
        data = event.data ? event.data.json() : {};
    } catch (e) {
        data = event.data ? { body: event.data.text() } : {};
    }

    const title = data.title || 'SafhaSahar';
    const options = {
        body: data.body || '',
        icon: data.icon || '/static/web_app/image/SafhaSahar.png',
        badge: '/static/web_app/image/SafhaSahar.png',
        data: { url: data.url || '/' },
        vibrate: [100, 50, 100],
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

// Clicking the notification focuses an existing tab if possible, otherwise
// opens the target URL (falls back to the app root).
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = (event.notification.data && event.notification.data.url) || '/';

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if ('focus' in client) {
                    client.navigate(targetUrl).catch(() => client.focus());
                    return;
                }
            }
            if (self.clients.openWindow) {
                return self.clients.openWindow(targetUrl);
            }
        })
    );
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

    // WebSocket upgrades are never cached.
    if (url.pathname.startsWith('/ws/')) {
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

    // Route-data API reads: stale-while-revalidate. Serve the last good
    // snapshot immediately if present, and refresh the cache in the
    // background when the network allows. This keeps the route map and
    // performance stats usable while offline or on slow links.
    if (isRouteApiRequest(url)) {
        event.respondWith(
            caches.match(req).then((cached) => {
                const network = fetch(req)
                    .then((res) => {
                        if (res && res.status === 200) {
                            const copy = res.clone();
                            caches.open(CACHE_NAME).then((cache) => {
                                cache.put(req, copy).catch(() => {});
                            });
                        }
                        return res;
                    })
                    .catch(() => cached);
                // Always return a valid Response: cached, or network, or offline fallback.
                return cached || network || Promise.resolve(
                    new Response(JSON.stringify({ error: 'Offline', cached: false }), {
                        status: 503,
                        statusText: 'Service Unavailable',
                        headers: { 'Content-Type': 'application/json' },
                    })
                );
            })
        );
        return;
    }

    // Never cache other API calls
    if (url.pathname.startsWith('/api/')) {
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

            // Always return a valid Response
            return cached || network || Promise.resolve(
                new Response('Offline', {
                    status: 503,
                    statusText: 'Service Unavailable',
                    headers: { 'Content-Type': 'text/plain' },
                })
            );
        })
    );
});