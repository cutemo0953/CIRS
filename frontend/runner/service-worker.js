/**
 * xIRS Runner PWA Service Worker v1.8
 *
 * Provides offline caching for Runner PWA.
 * Minimal footprint - Runner only needs to store and display QR codes.
 */

const CACHE_NAME = 'xirs-runner-v1.8.0';

const CORE_ASSETS = [
    '/runner/',
    '/runner/index.html',
    '/runner/manifest.json',
    '/shared/js/xirs-runner.js'
];

const CDN_ASSETS = [
    'https://cdn.tailwindcss.com',
    'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
    'https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js',
    'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js'
];

// Install
self.addEventListener('install', (event) => {
    console.log('[Runner SW] Installing...');

    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(CORE_ASSETS);
        }).then(() => {
            return caches.open(CACHE_NAME).then((cache) => {
                return Promise.allSettled(
                    CDN_ASSETS.map(url => cache.add(url).catch(() => {}))
                );
            });
        }).then(() => {
            console.log('[Runner SW] Install complete');
            return self.skipWaiting();
        })
    );
});

// Activate
self.addEventListener('activate', (event) => {
    console.log('[Runner SW] Activating...');

    event.waitUntil(
        caches.keys().then((cacheNames) => {
            return Promise.all(
                cacheNames
                    .filter(name => name.startsWith('xirs-runner-') && name !== CACHE_NAME)
                    .map(name => caches.delete(name))
            );
        }).then(() => {
            return self.clients.claim();
        })
    );
});

// Fetch - offline first
self.addEventListener('fetch', (event) => {
    if (event.request.method !== 'GET') return;
    if (new URL(event.request.url).pathname.startsWith('/api/')) return;

    event.respondWith(
        caches.match(event.request).then((cachedResponse) => {
            if (cachedResponse) {
                // Update cache in background
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

            return fetch(event.request).then((networkResponse) => {
                if (networkResponse.ok) {
                    const clone = networkResponse.clone();
                    caches.open(CACHE_NAME).then((cache) => {
                        cache.put(event.request, clone);
                    });
                }
                return networkResponse;
            }).catch(() => {
                if (event.request.headers.get('accept')?.includes('text/html')) {
                    return caches.match('/runner/index.html');
                }
                throw new Error('Offline');
            });
        })
    );
});

console.log('[Runner SW] Loaded v1.8.0');
