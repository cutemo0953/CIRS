/**
 * xIRS Storage Library v1.8 - IndexedDB Offline Storage
 *
 * Provides persistent storage for Station PWA:
 * - Inventory management
 * - Action queue (pending reports)
 * - Processed manifests
 * - Person registry
 *
 * All data survives browser close and works offline.
 */

(function(global) {
    'use strict';

    const DB_NAME = 'xIRS_Station';
    const DB_VERSION = 1;

    /**
     * IndexedDB wrapper for xIRS Station
     */
    class StationDB {
        constructor() {
            this.db = null;
            this._initPromise = null;
        }

        /**
         * Initialize database
         * @returns {Promise<IDBDatabase>}
         */
        async init() {
            if (this.db) return this.db;
            if (this._initPromise) return this._initPromise;

            this._initPromise = new Promise((resolve, reject) => {
                const request = indexedDB.open(DB_NAME, DB_VERSION);

                request.onerror = () => {
                    console.error('[StationDB] Failed to open:', request.error);
                    reject(request.error);
                };

                request.onsuccess = () => {
                    this.db = request.result;
                    console.log('[StationDB] Opened successfully');
                    resolve(this.db);
                };

                request.onupgradeneeded = (event) => {
                    const db = event.target.result;
                    console.log('[StationDB] Upgrading schema...');

                    // Inventory store
                    if (!db.objectStoreNames.contains('inventory')) {
                        const invStore = db.createObjectStore('inventory', { keyPath: 'code' });
                        invStore.createIndex('category', 'category', { unique: false });
                        invStore.createIndex('name', 'name', { unique: false });
                    }

                    // Action queue (pending sync)
                    if (!db.objectStoreNames.contains('actions')) {
                        const actStore = db.createObjectStore('actions', { keyPath: 'id', autoIncrement: true });
                        actStore.createIndex('type', 'type', { unique: false });
                        actStore.createIndex('ts', 'ts', { unique: false });
                        actStore.createIndex('synced', 'synced', { unique: false });
                    }

                    // Processed manifests
                    if (!db.objectStoreNames.contains('manifests')) {
                        const manStore = db.createObjectStore('manifests', { keyPath: 'manifest_id' });
                        manStore.createIndex('processed_at', 'processed_at', { unique: false });
                        manStore.createIndex('short_code', 'short_code', { unique: true });
                    }

                    // Person registry
                    if (!db.objectStoreNames.contains('persons')) {
                        const perStore = db.createObjectStore('persons', { keyPath: 'id' });
                        perStore.createIndex('name', 'name', { unique: false });
                        perStore.createIndex('registered_at', 'registered_at', { unique: false });
                    }

                    // Pending reports (encrypted, ready for Runner)
                    if (!db.objectStoreNames.contains('reports')) {
                        const repStore = db.createObjectStore('reports', { keyPath: 'packet_id' });
                        repStore.createIndex('created_at', 'created_at', { unique: false });
                        repStore.createIndex('delivered', 'delivered', { unique: false });
                    }

                    console.log('[StationDB] Schema created');
                };
            });

            return this._initPromise;
        }

        /**
         * Get object store transaction
         * @param {string} storeName - Store name
         * @param {string} mode - 'readonly' or 'readwrite'
         * @returns {IDBObjectStore}
         */
        _getStore(storeName, mode = 'readonly') {
            const tx = this.db.transaction(storeName, mode);
            return tx.objectStore(storeName);
        }

        // ===== Inventory Methods =====

        /**
         * Get all inventory items
         * @returns {Promise<Array>}
         */
        async getInventory() {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('inventory');
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get inventory item by code
         * @param {string} code - Item code
         * @returns {Promise<Object|null>}
         */
        async getItem(code) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('inventory');
                const request = store.get(code);
                request.onsuccess = () => resolve(request.result || null);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Add or update inventory item
         * @param {Object} item - { code, name, quantity, unit, category, ... }
         * @returns {Promise<string>} Item code
         */
        async putItem(item) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('inventory', 'readwrite');
                const request = store.put(item);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Update item quantity
         * @param {string} code - Item code
         * @param {number} delta - Change in quantity (positive or negative)
         * @returns {Promise<Object>} Updated item
         */
        async adjustQuantity(code, delta) {
            await this.init();
            const item = await this.getItem(code);
            if (!item) throw new Error(`Item not found: ${code}`);

            item.quantity = Math.max(0, (item.quantity || 0) + delta);
            item.updated_at = new Date().toISOString();
            await this.putItem(item);
            return item;
        }

        /**
         * Bulk update inventory (from manifest)
         * @param {Array} items - Array of { code, qty, unit, ... }
         * @param {string} operation - 'add' or 'set'
         * @returns {Promise<number>} Number of items updated
         */
        async bulkUpdateInventory(items, operation = 'add') {
            await this.init();
            let count = 0;

            for (const item of items) {
                let existing = await this.getItem(item.code);

                if (!existing) {
                    existing = {
                        code: item.code,
                        name: item.code,  // Default name to code
                        quantity: 0,
                        unit: item.unit || 'unit',
                        category: 'supplies',
                        created_at: new Date().toISOString()
                    };
                }

                if (operation === 'add') {
                    existing.quantity = (existing.quantity || 0) + (item.qty || 0);
                } else {
                    existing.quantity = item.qty || 0;
                }

                existing.updated_at = new Date().toISOString();
                await this.putItem(existing);
                count++;
            }

            return count;
        }

        // ===== Action Queue Methods =====

        /**
         * Queue an action for sync
         * @param {Object} action - Action object
         * @returns {Promise<number>} Action ID
         */
        async queueAction(action) {
            await this.init();
            const record = {
                ...action,
                queued_at: new Date().toISOString(),
                synced: false
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('actions', 'readwrite');
                const request = store.add(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get all pending (unsynced) actions
         * @returns {Promise<Array>}
         */
        async getPendingActions() {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('actions');
                const index = store.index('synced');
                const request = index.getAll(IDBKeyRange.only(false));
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Mark actions as synced
         * @param {Array<number>} ids - Action IDs to mark
         * @returns {Promise<number>} Count updated
         */
        async markActionsSynced(ids) {
            await this.init();
            let count = 0;

            for (const id of ids) {
                await new Promise((resolve, reject) => {
                    const store = this._getStore('actions', 'readwrite');
                    const request = store.get(id);
                    request.onsuccess = () => {
                        const action = request.result;
                        if (action) {
                            action.synced = true;
                            action.synced_at = new Date().toISOString();
                            store.put(action);
                            count++;
                        }
                        resolve();
                    };
                    request.onerror = () => reject(request.error);
                });
            }

            return count;
        }

        /**
         * Get action count summary
         * @returns {Promise<Object>} { pending, synced, total }
         */
        async getActionStats() {
            await this.init();
            const all = await new Promise((resolve, reject) => {
                const store = this._getStore('actions');
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });

            const pending = all.filter(a => !a.synced).length;
            return {
                pending,
                synced: all.length - pending,
                total: all.length
            };
        }

        // ===== Manifest Methods =====

        /**
         * Check if manifest was already processed
         * @param {string} manifestId - Manifest ID
         * @returns {Promise<boolean>}
         */
        async isManifestProcessed(manifestId) {
            await this.init();
            const manifest = await new Promise((resolve, reject) => {
                const store = this._getStore('manifests');
                const request = store.get(manifestId);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
            return !!manifest;
        }

        /**
         * Record processed manifest
         * @param {Object} manifest - Manifest object
         * @returns {Promise<string>} Manifest ID
         */
        async recordManifest(manifest) {
            await this.init();
            const record = {
                manifest_id: manifest.manifest_id,
                short_code: manifest.short_code,
                station_id: manifest.station_id,
                items: manifest.items,
                processed_at: new Date().toISOString()
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('manifests', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get all processed manifests
         * @returns {Promise<Array>}
         */
        async getManifests() {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('manifests');
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        // ===== Person Methods =====

        /**
         * Register a person
         * @param {Object} person - { id, name, ... }
         * @returns {Promise<string>} Person ID
         */
        async registerPerson(person) {
            await this.init();
            const record = {
                ...person,
                registered_at: new Date().toISOString()
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('persons', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get person by ID
         * @param {string} id - Person ID
         * @returns {Promise<Object|null>}
         */
        async getPerson(id) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('persons');
                const request = store.get(id);
                request.onsuccess = () => resolve(request.result || null);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get all persons
         * @returns {Promise<Array>}
         */
        async getPersons() {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('persons');
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Generate next person ID
         * @returns {Promise<string>} e.g., "P0042"
         */
        async generatePersonId() {
            const persons = await this.getPersons();
            const maxNum = persons.reduce((max, p) => {
                const match = p.id.match(/^P(\d+)$/);
                return match ? Math.max(max, parseInt(match[1], 10)) : max;
            }, 0);
            return `P${String(maxNum + 1).padStart(4, '0')}`;
        }

        // ===== Report Methods =====

        /**
         * Store a report ready for delivery
         * @param {string} packetId - Packet ID
         * @param {Object} encryptedEnvelope - Encrypted envelope
         * @param {Array<string>} qrChunks - QR chunk strings
         * @returns {Promise<string>}
         */
        async storeReport(packetId, encryptedEnvelope, qrChunks) {
            await this.init();
            const record = {
                packet_id: packetId,
                envelope: encryptedEnvelope,
                chunks: qrChunks,
                created_at: new Date().toISOString(),
                delivered: false
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('reports', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get pending (undelivered) reports
         * @returns {Promise<Array>}
         */
        async getPendingReports() {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('reports');
                const index = store.index('delivered');
                const request = index.getAll(IDBKeyRange.only(false));
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Mark report as delivered
         * @param {string} packetId - Packet ID
         * @returns {Promise<void>}
         */
        async markReportDelivered(packetId) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('reports', 'readwrite');
                const request = store.get(packetId);
                request.onsuccess = () => {
                    const report = request.result;
                    if (report) {
                        report.delivered = true;
                        report.delivered_at = new Date().toISOString();
                        store.put(report);
                    }
                    resolve();
                };
                request.onerror = () => reject(request.error);
            });
        }

        // ===== Utility Methods =====

        /**
         * Clear all data (factory reset)
         * @returns {Promise<void>}
         */
        async clearAll() {
            await this.init();
            const stores = ['inventory', 'actions', 'manifests', 'persons', 'reports'];

            for (const storeName of stores) {
                await new Promise((resolve, reject) => {
                    const store = this._getStore(storeName, 'readwrite');
                    const request = store.clear();
                    request.onsuccess = () => resolve();
                    request.onerror = () => reject(request.error);
                });
            }

            console.log('[StationDB] All data cleared');
        }

        /**
         * Export all data for backup
         * @returns {Promise<Object>}
         */
        async exportAll() {
            await this.init();
            return {
                inventory: await this.getInventory(),
                actions: await new Promise((resolve, reject) => {
                    const store = this._getStore('actions');
                    const request = store.getAll();
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                }),
                manifests: await this.getManifests(),
                persons: await this.getPersons(),
                reports: await this.getPendingReports(),
                exported_at: new Date().toISOString()
            };
        }
    }

    // Export singleton
    global.xIRS = global.xIRS || {};
    global.xIRS.StationDB = new StationDB();

    console.log('[xIRS Storage] v1.8.0 loaded');

})(typeof window !== 'undefined' ? window : global);
