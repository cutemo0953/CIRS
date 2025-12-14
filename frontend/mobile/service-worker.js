// CIRS Satellite PWA Service Worker
const CACHE_VERSION = 'v1.0.0';
const STATIC_CACHE = `cirs-satellite-static-${CACHE_VERSION}`;
const DYNAMIC_CACHE = `cirs-satellite-dynamic-${CACHE_VERSION}`;
const SYNC_QUEUE_KEY = 'cirs-satellite-sync-queue';

// Static assets to cache on install
const STATIC_ASSETS = [
    '/mobile/',
    '/mobile/index.html',
    '/mobile/manifest.json',
    '/mobile/icons/icon-192x192.png',
    '/mobile/icons/icon-512x512.png'
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
    console.log('[SW] Installing Service Worker...');
    event.waitUntil(
        caches.open(STATIC_CACHE)
            .then((cache) => {
                console.log('[SW] Caching static assets');
                return cache.addAll(STATIC_ASSETS);
            })
            .then(() => self.skipWaiting())
    );
});

// Activate event - clean old caches
self.addEventListener('activate', (event) => {
    console.log('[SW] Activating Service Worker...');
    event.waitUntil(
        caches.keys()
            .then((keys) => {
                return Promise.all(
                    keys.filter((key) => {
                        return key.startsWith('cirs-satellite-') &&
                               key !== STATIC_CACHE &&
                               key !== DYNAMIC_CACHE;
                    }).map((key) => {
                        console.log('[SW] Removing old cache:', key);
                        return caches.delete(key);
                    })
                );
            })
            .then(() => self.clients.claim())
    );
});

// Fetch event - network first for API, cache first for static
self.addEventListener('fetch', (event) => {
    const url = new URL(event.request.url);

    // Skip non-GET requests for caching
    if (event.request.method !== 'GET') {
        return;
    }

    // API requests - network first with dynamic cache fallback
    if (url.pathname.startsWith('/api/')) {
        event.respondWith(networkFirstStrategy(event.request));
        return;
    }

    // Static assets - cache first
    event.respondWith(cacheFirstStrategy(event.request));
});

// Cache first strategy (for static assets)
async function cacheFirstStrategy(request) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
        return cachedResponse;
    }

    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        console.log('[SW] Fetch failed, returning offline fallback');
        // Return a basic offline response
        return new Response(
            JSON.stringify({ error: 'offline', message: 'You are offline' }),
            {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            }
        );
    }
}

// Network first strategy (for API calls)
async function networkFirstStrategy(request) {
    try {
        const networkResponse = await fetch(request);
        if (networkResponse.ok) {
            // Cache successful API responses
            const cache = await caches.open(DYNAMIC_CACHE);
            cache.put(request, networkResponse.clone());
        }
        return networkResponse;
    } catch (error) {
        console.log('[SW] Network failed, trying cache');
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }

        return new Response(
            JSON.stringify({ error: 'offline', message: 'Network unavailable' }),
            {
                status: 503,
                headers: { 'Content-Type': 'application/json' }
            }
        );
    }
}

// Message handler for sync operations (iOS Safari fallback)
self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SYNC_NOW') {
        console.log('[SW] Received sync request from client');
        processSyncQueue().then((results) => {
            // Notify all clients about sync completion
            self.clients.matchAll().then((clients) => {
                clients.forEach((client) => {
                    client.postMessage({
                        type: 'SYNC_COMPLETE',
                        results: results
                    });
                });
            });
        });
    }

    if (event.data && event.data.type === 'ADD_TO_SYNC_QUEUE') {
        addToSyncQueue(event.data.payload);
    }
});

// Background Sync (for browsers that support it)
self.addEventListener('sync', (event) => {
    console.log('[SW] Background sync triggered:', event.tag);
    if (event.tag === 'cirs-sync') {
        event.waitUntil(processSyncQueue());
    }
});

// Process the sync queue
async function processSyncQueue() {
    const queue = await getSyncQueue();
    const results = [];

    for (const item of queue) {
        try {
            const response = await fetch(item.url, {
                method: item.method,
                headers: item.headers,
                body: item.body
            });

            if (response.ok) {
                results.push({ id: item.id, success: true });
            } else {
                results.push({ id: item.id, success: false, error: response.status });
            }
        } catch (error) {
            results.push({ id: item.id, success: false, error: error.message });
        }
    }

    // Clear successfully synced items
    const failedItems = queue.filter((item, index) => !results[index]?.success);
    await saveSyncQueue(failedItems);

    return results;
}

// Get sync queue from IndexedDB
async function getSyncQueue() {
    return new Promise((resolve) => {
        const request = indexedDB.open('cirs-satellite', 1);

        request.onupgradeneeded = (event) => {
            const db = event.target.result;
            if (!db.objectStoreNames.contains('syncQueue')) {
                db.createObjectStore('syncQueue', { keyPath: 'id' });
            }
        };

        request.onsuccess = (event) => {
            const db = event.target.result;
            const tx = db.transaction('syncQueue', 'readonly');
            const store = tx.objectStore('syncQueue');
            const getAllRequest = store.getAll();

            getAllRequest.onsuccess = () => {
                resolve(getAllRequest.result || []);
            };

            getAllRequest.onerror = () => {
                resolve([]);
            };
        };

        request.onerror = () => {
            resolve([]);
        };
    });
}

// Save sync queue to IndexedDB
async function saveSyncQueue(queue) {
    return new Promise((resolve) => {
        const request = indexedDB.open('cirs-satellite', 1);

        request.onsuccess = (event) => {
            const db = event.target.result;
            const tx = db.transaction('syncQueue', 'readwrite');
            const store = tx.objectStore('syncQueue');

            store.clear();
            queue.forEach((item) => store.add(item));

            tx.oncomplete = () => resolve();
            tx.onerror = () => resolve();
        };

        request.onerror = () => resolve();
    });
}

// Add item to sync queue
async function addToSyncQueue(item) {
    const queue = await getSyncQueue();
    queue.push({
        ...item,
        id: item.id || Date.now().toString(),
        timestamp: Date.now()
    });
    await saveSyncQueue(queue);
    console.log('[SW] Added to sync queue:', item.id);
}

// Periodic sync check (for iOS Safari workaround)
// This is triggered by the client sending SYNC_NOW messages
console.log('[SW] Service Worker loaded');
