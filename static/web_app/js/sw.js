// Bump this whenever precache/handling changes. Old caches are only purged by
// the activate handler when their name differs, so shipping the authenticated
// API-cache removal under the previous name would have left every previously
// cached /api/ response sitting on the user's disk indefinitely.
const CACHE_NAME = 'waste-management-v5';

// Dev passthrough: when the page registers this worker as /sw.js?debug=1
// (base.html does that while DEBUG=True via runserver), the worker never
// caches anything — it lets every request hit the network so template,
// static (CSS/JS) and Python edits show up live without a hard refresh.
// It still activates and claims, purging every stale cache left behind by
// an earlier prod-mode registration so old assets can never resurface.
const DEBUG_SW = new URL(self.location.href).searchParams.has('debug');

// Background Sync tags
const SYNC_TAGS = {
    OFFLINE_REQUESTS: 'offline-requests-sync',
    GPS_PINGS: 'gps-pings-sync',
};

// ── Offline route caching ──────────────────────────────────────────────────
// DISABLED. These are authenticated, per-user endpoints (addresses, photos,
// driver usernames/phones, live GPS). The Cache Storage API is keyed by URL
// only and never by user, so on a shared device `caches.match(req)` would serve
// the previous user's response to whoever signs in next. The backend scoping
// the response does not help: the leak happens in the browser cache, before
// any request is made. Kept as an empty list rather than deleted so the intent
// stays visible.
const ROUTE_API_PREFIXES = [];

function isRouteApiRequest(requestUrl) {
    if (!requestUrl || !requestUrl.pathname) return false;
    return ROUTE_API_PREFIXES.some((prefix) =>
        requestUrl.pathname.startsWith(prefix)
    );
}

// Install event - cache the app shell
self.addEventListener('install', (event) => {
    // In dev (DEBUG_SW) there is nothing to pre-cache: the app shell and
    // every static asset must stay network-served so changes appear live.
    if (!DEBUG_SW) {
        event.waitUntil(
            caches.open(CACHE_NAME).then((cache) => {
                // cache.addAll() is atomic: a single 404 rejects the whole batch,
                // so every entry must be a URL that actually exists. These are
                // the files base.html loads.
                return cache.addAll([
                    '/',
                    '/static/web_app/css/layout.css',
                    '/static/web_app/css/main.css',
                    '/static/web_app/js/main.js',
                ]).catch(() => {
                    // Ignore cache.addAll failures (e.g., if a file is temporarily missing)
                });
            })
        );
    }
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    // Dev mode: delete ALL caches so nothing stale from a
                    // previous prod-mode worker can be served while working.
                    .filter((name) => DEBUG_SW || name !== CACHE_NAME)
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

// ── Background Sync ──────────────────────────────────────────────────────────
// Handles reliable replay of queued requests and GPS pings when connectivity
// is restored. Uses the Background Sync API which persists across browser
// restarts and guarantees execution when network becomes available.
self.addEventListener('sync', (event) => {
    if (event.tag === SYNC_TAGS.OFFLINE_REQUESTS) {
        event.waitUntil(syncOfflineRequests());
    } else if (event.tag === SYNC_TAGS.GPS_PINGS) {
        event.waitUntil(syncGpsPings());
    }
});

// ── IndexedDB helpers (mirrors base.html OfflineQueue v2) ────────────────
// The queue lives in IndexedDB ('safhasahar-offline' / 'requests') precisely
// so BOTH pages and this worker can see it. localStorage is invisible here.
const OFFLINE_DB = 'safhasahar-offline';
const OFFLINE_STORE = 'requests';

function swIdbAll() {
    return new Promise((resolve, reject) => {
        if (!('indexedDB' in self)) {
            reject(new Error('IndexedDB not supported in SW'));
            return;
        }
        let req;
        try {
            req = self.indexedDB.open(OFFLINE_DB, 1);
        } catch (e) {
            reject(e);
            return;
        }
        req.onupgradeneeded = () => {
            const db = req.result;
            if (!db.objectStoreNames.contains(OFFLINE_STORE)) {
                db.createObjectStore(OFFLINE_STORE, { keyPath: 'id' });
            }
        };
        req.onsuccess = () => {
            const db = req.result;
            let tx;
            try {
                tx = db.transaction(OFFLINE_STORE, 'readonly');
            } catch (e) {
                db.close();
                reject(e);
                return;
            }
            const rq = tx.objectStore(OFFLINE_STORE).getAll();
            rq.onsuccess = () => {
                db.close();
                resolve(rq.result || []);
            };
            rq.onerror = () => {
                db.close();
                reject(rq.error || new Error('SW IDB read failed'));
            };
        };
        req.onerror = () => reject(req.error || new Error('SW IDB open failed'));
    });
}

function swIdbDelete(id) {
    return new Promise((resolve) => {
        let req;
        try {
            req = self.indexedDB.open(OFFLINE_DB, 1);
        } catch (e) {
            resolve(false);
            return;
        }
        req.onsuccess = () => {
            const db = req.result;
            let done = false;
            const finish = () => {
                if (!done) { done = true; try { db.close(); } catch (e2) {} resolve(true); }
            };
            try {
                const tx = db.transaction(OFFLINE_STORE, 'readwrite');
                tx.objectStore(OFFLINE_STORE).delete(id);
                tx.oncomplete = finish;
                tx.onerror = finish;
                tx.onabort = finish;
            } catch (e) {
                finish();
            }
        };
        req.onerror = () => resolve(false);
    });
}

function swBuildFormData(item) {
    const fd = new FormData();
    const fields = item.fields || item.body || {};
    Object.keys(fields).forEach((k) => {
        const v = fields[k];
        if (v === undefined || v === null || v === '') return;
        if (Array.isArray(v)) {
            v.forEach((x) => { if (x !== '' && x !== null && x !== undefined) fd.append(k, String(x)); });
        } else {
            fd.append(k, String(v));
        }
    });
    const photos = Array.isArray(item.photos) ? item.photos : [];
    photos.forEach((p, idx) => {
        if (!p || !p.blob) return;
        const name = p.name || ('photo-' + (idx + 1) + '.jpg');
        const type = p.type || p.blob.type || 'image/jpeg';
        let file = p.blob;
        try {
            file = new File([p.blob], name, { type });
        } catch (e) {
            file = p.blob;
        }
        if (idx === 0) {
            fd.append('photo', file, name);
            if (p.gps && p.gps.lat !== undefined && p.gps.lat !== null && p.gps.lat !== '') {
                fd.append('photo_latitude', String(p.gps.lat));
            }
            if (p.gps && p.gps.lng !== undefined && p.gps.lng !== null && p.gps.lng !== '') {
                fd.append('photo_longitude', String(p.gps.lng));
            }
        } else {
            fd.append('extra_photos', file, name);
            fd.append('extra_photos_latitude', (p.gps && p.gps.lat !== undefined && p.gps.lat !== null) ? String(p.gps.lat) : '');
            fd.append('extra_photos_longitude', (p.gps && p.gps.lng !== undefined && p.gps.lng !== null) ? String(p.gps.lng) : '');
        }
    });
    return fd;
}

async function syncOfflineRequests() {
    try {
        const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });

        if (clients.length > 0) {
            // A tab is open: it holds a fresh CSRF token, so let IT replay.
            for (const client of clients) {
                client.postMessage({ type: 'SYNC_OFFLINE_REQUESTS' });
            }
            console.log('[SW] Background sync forwarded to', clients.length, 'client(s)');
            return;
        }

        // No tab open: replay directly from IndexedDB so closing the tab
        // while offline no longer strands the report. Cookies ride along via
        // credentials:include; the stored enqueue-time CSRF is best-effort
        // (a page flush with a fresh token will retry anything we cannot).
        let items = [];
        try {
            items = await swIdbAll();
        } catch (e) {
            console.warn('[SW] IDB read failed:', e);
            return;
        }
        if (!items.length) return;

        let flushed = 0;
        for (const item of items) {
            try {
                const fd = swBuildFormData(item);
                const headers = {};
                if (item.csrf) headers['X-CSRFToken'] = item.csrf;
                const res = await fetch(item.url || '/api/waste-requests/', {
                    method: item.method || 'POST',
                    credentials: 'include',
                    headers,
                    body: fd,
                });
                if (res.ok) {
                    await swIdbDelete(item.id);
                    flushed++;
                } else if (res.status >= 400 && res.status <= 422) {
                    // Permanent validation error — drop so it cannot jam later items.
                    await swIdbDelete(item.id);
                    console.warn('[SW] Dropping permanently rejected offline item', item.id, res.status);
                }
                // Else transient (401/403/5xx/network): keep for a page flush.
            } catch (e) {
                // Network still down — stop; the next sync event retries.
                break;
            }
        }
        console.log('[SW] Background sync direct replay flushed', flushed, 'item(s)');
    } catch (e) {
        console.error('[SW] Offline requests sync failed:', e);
    }
}

async function syncGpsPings() {
    try {
        const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
        
        for (const client of clients) {
            client.postMessage({
                type: 'SYNC_GPS_PINGS',
            });
        }
        
        console.log('[SW] Background sync triggered for GPS pings');
        
    } catch (e) {
        console.error('[SW] GPS pings sync failed:', e);
    }
}

// Fetch event
self.addEventListener('fetch', (event) => {
    const req = event.request;

    // Only handle GET requests
    if (req.method !== 'GET') return;

    // Dev mode: never intercept — plain network request, nothing cached, so
    // every edit is visible on the next poll/refresh.
    if (DEBUG_SW) return;

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
                // Always return a valid Response: cached, else network, else a 503.
                // `network` is a Promise and therefore always truthy, so the
                // fallback must be resolved INSIDE the then() — testing it in the
                // || chain made the 503 unreachable and turned a rejected fetch
                // into respondWith(undefined), which throws a TypeError.
                const offlineFallback = new Response(
                    JSON.stringify({ error: 'Offline', cached: false }),
                    {
                        status: 503,
                        statusText: 'Service Unavailable',
                        headers: { 'Content-Type': 'application/json' },
                    }
                );
                return cached || network.then((res) => res || offlineFallback);
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
                    caches.match(req)
                        .then((cached) => cached || caches.match('/'))
                        // caches.match resolves to undefined on a miss, and
                        // respondWith(undefined) throws a TypeError — so a real
                        // offline Response has to be the final fallback.
                        .then((cached) => cached || new Response(
                            '<!doctype html><html><head><meta charset="utf-8">'
                            + '<title>Offline</title></head><body>'
                            + '<h1>You are offline</h1>'
                            + '<p>Please reconnect and try again.</p>'
                            + '</body></html>',
                            { status: 503, statusText: 'Service Unavailable',
                              headers: { 'Content-Type': 'text/html; charset=utf-8' } }
                        ))
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

            // Always return a valid Response. As above, `network` is a Promise
            // and always truthy, so the 503 must be resolved inside then().
            const offlineFallback = new Response('Offline', {
                status: 503,
                statusText: 'Service Unavailable',
                headers: { 'Content-Type': 'text/plain' },
            });
            return cached || network.then((res) => res || offlineFallback);
        })
    );
});