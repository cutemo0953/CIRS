/**
 * xIRS Doctor PWA Service Worker v1.0
 *
 * Provides offline caching for Doctor PWA.
 * Key features:
 * - Cache core assets for offline use
 * - Cache medication catalog
 * - Enable Rx creation without network
 */

const CACHE_NAME = 'xirs-doctor-v1.0.0';

const CORE_ASSETS = [
    '/doctor/',
    '/doctor/index.html',
    '/doctor/manifest.json',
    '/shared/js/xirs-crypto.js',
    '/shared/js/xirs-rx.js',
    '/shared/js/xirs-doctor-db.js'
];

const CDN_ASSETS = [
    'https://cdn.tailwindcss.com',
    'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
    'https://cdn.jsdelivr.net/npm/tweetnacl@1.0.3/nacl-fast.min.js',
    'https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js'
];

// Install
self.addEventListener('install', (event) => {
    console.log('[Doctor SW] Installing...');

    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            // Cache core assets first
            return cache.addAll(CORE_ASSETS);
        }).then(() => {
            // Try to cache CDN assets (non-blocking)
            return caches.open(CACHE_NAME).then((cache) => {
                return Promise.allSettled(
                    CDN_ASSETS.map(url => cache.add(url).catch(() => {
                        console.log('[Doctor SW] Failed to cache:', url);
                    }))
                );
            });
        }).then(() => {
            console.log('[Doctor SW] Install complete');
            return self.skipWaiting();
        })
    );
});

// Activate
self.addEventListener('activate', (event) => {
    console.log('[Doctor SW] Activating...');

    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter(name => name.startsWith('xirs-doctor-') && name !== CACHE_NAME)
                    .map(name => {
                        console.log('[Doctor SW] Deleting old cache:', name);
                        return caches.delete(name);
                    })
            );
        }).then(() => {
            return self.clients.claim();
        })
    );
});

// Fetch - cache-first for assets, network-first for API
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') return;

    // Skip API requests (except medication catalog which could be cached)
    if (url.pathname.startsWith('/api/')) {
        return;
    }

    // Cache-first strategy for static assets
    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                // Return cached version, update cache in background
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

            // Not in cache, fetch from network
            return fetch(event.request).then((networkResponse) => {
                if (networkResponse.ok) {
                    const clone = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, clone);
                    });
                }
                return networkResponse;
            }).catch(() => {
                // Offline fallback for HTML pages
                if (event.request.headers.get('accept')?.includes('text/html')) {
                    return caches.match('/doctor/index.html');
                }
                throw new Error('Offline');
            });
        })
    );
});

// Message handler for cache updates
self.addEventListener('message', (event) => {
    if (event.data?.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }

    if (event.data?.type === 'CACHE_MEDICATIONS') {
        // Cache medication catalog data
        const medications = event.data.medications;
        console.log('[Doctor SW] Caching medications:', medications?.length);
    }
});

console.log('[Doctor SW] Loaded v1.0.0');
