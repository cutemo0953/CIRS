/**
 * xIRS Station PWA Service Worker v1.8
 *
 * Provides offline-first caching for Station PWA.
 * All core assets are cached for full offline operation.
 */

const CACHE_NAME = 'xirs-station-v1.8.0';

const CORE_ASSETS = [
    '/station/',
    '/station/index.html',
    '/station/manifest.json',
    '/shared/js/xirs-crypto.js',
    '/shared/js/xirs-protocol.js',
    '/shared/js/xirs-storage.js'
];

const CDN_ASSETS = [
    'https://cdn.tailwindcss.com',
    'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
    'https://cdn.jsdelivr.net/npm/tweetnacl@1.0.3/nacl-fast.min.js',
    'https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js',
    'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js'
];

// Install event - cache core assets
self.addEventListener('install', (event) => {
    console.log('[Station SW] Installing...');

    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            console.log('[Station SW] Caching core assets');
            return cache.addAll(CORE_ASSETS);
        }).then(() => {
            // Cache CDN assets (best effort)
            return caches.open(CACHE_NAME).then((cache) => {
                return Promise.allSettled(
                    CDN_ASSETS.map(url => cache.add(url).catch(() => {
                        console.log('[Station SW] Failed to cache CDN:', url);
                    }))
                );
            });
        }).then(() => {
            console.log('[Station SW] Install complete');
            return self.skipWaiting();
        })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('[Station SW] Activating...');

    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter(name => name.startsWith('xirs-station-') && name !== CACHE_NAME)
                    .map(name => {
                        console.log('[Station SW] Deleting old cache:', name);
                        return caches.delete(name);
                    })
            );
        }).then(() => {
            console.log('[Station SW] Activation complete');
            return self.clients.claim();
        })
    );
});

// Fetch event - offline-first strategy
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // Skip API requests (let them fail offline)
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // Offline-first for core assets
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                // Return cache, but also update cache in background
                event.waitUntil(
                    fetch(event.request).then((networkResponse) => {
                        if (networkResponse.ok) {
                            caches.open(CACHE_NAME).then((cache) => {
                                cache.put(event.request, networkResponse);
                            });
                        }
                    }).catch(() => {})
                );
                return cachedResponse;
            }

            // Not in cache, try network
            return fetch(event.request).then((networkResponse) => {
                // Cache successful responses
                if (networkResponse.ok) {
                    const responseClone = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, responseClone);
                    });
                }
                return networkResponse;
            }).catch(() => {
                // Offline fallback for HTML requests
                if (event.request.headers.get('accept')?.includes('text/html')) {
                    return caches.match('/station/index.html');
                }
                throw new Error('Offline');
            });
        })
    );
});

// Message event - for manual cache control
self.addEventListener('message', (event) => {
    if (event.data === 'skipWaiting') {
        self.skipWaiting();
    }

    if (event.data === 'clearCache') {
        caches.delete(CACHE_NAME).then(() => {
            console.log('[Station SW] Cache cleared');
        });
    }
});

console.log('[Station SW] Loaded v1.8.0');
