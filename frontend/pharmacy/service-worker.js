/**
 * xIRS Pharmacy Station Service Worker v2.3
 * Provides offline-first capabilities for the Pharmacy PWA
 */

const CACHE_NAME = 'xirs-pharmacy-v2.3.0';

const STATIC_ASSETS = [
    '/pharmacy/',
    '/pharmacy/index.html',
    '/pharmacy/manifest.json',
    '/shared/js/xirs-crypto.js',
    '/shared/js/xirs-protocol.js',
    '/shared/js/xirs-storage.js',
    '/shared/js/xirs-pairing.js',
    '/shared/js/xirs-pharmacy-db.js',
    '/shared/js/xirs-rx.js'
];

const CDN_ASSETS = [
    'https://cdn.tailwindcss.com',
    'https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js',
    'https://cdn.jsdelivr.net/npm/tweetnacl@1.0.3/nacl-fast.min.js',
    'https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js',
    'https://unpkg.com/html5-qrcode@2.3.8/html5-qrcode.min.js'
];

// Install event
self.addEventListener('install', event => {
    console.log('[Pharmacy SW] Installing...');
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('[Pharmacy SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event
self.addEventListener('activate', event => {
    console.log('[Pharmacy SW] Activating...');
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames
                    .filter(name => name.startsWith('xirs-pharmacy-') && name !== CACHE_NAME)
                    .map(name => {
                        console.log('[Pharmacy SW] Deleting old cache:', name);
                        return caches.delete(name);
                    })
            );
        }).then(() => self.clients.claim())
    );
});

// Fetch event
self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);

    // Skip non-GET requests
    if (event.request.method !== 'GET') {
        return;
    }

    // API requests: network-first
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(
            fetch(event.request)
                .catch(() => {
                    return new Response(
                        JSON.stringify({ error: 'Offline', offline: true }),
                        { headers: { 'Content-Type': 'application/json' } }
                    );
                })
        );
        return;
    }

    // CDN assets: cache-first with network fallback
    if (CDN_ASSETS.some(cdn => event.request.url.startsWith(cdn))) {
        event.respondWith(
            caches.match(event.request)
                .then(cached => {
                    if (cached) return cached;
                    return fetch(event.request).then(response => {
                        if (response.ok) {
                            const clone = response.clone();
                            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                        }
                        return response;
                    });
                })
        );
        return;
    }

    // Static assets: cache-first
    event.respondWith(
        caches.match(event.request)
            .then(cached => {
                if (cached) return cached;

                return fetch(event.request)
                    .then(response => {
                        if (response.ok && url.pathname.startsWith('/pharmacy/')) {
                            const clone = response.clone();
                            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
                        }
                        return response;
                    })
                    .catch(() => {
                        // Return index.html for navigation requests
                        if (event.request.mode === 'navigate') {
                            return caches.match('/pharmacy/index.html');
                        }
                        return new Response('Offline', { status: 503 });
                    });
            })
    );
});

console.log('[Pharmacy SW] v2.3.0 loaded');
