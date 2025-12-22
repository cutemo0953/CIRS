/**
 * xIRS Storage Library v2.0 - IndexedDB Offline Storage
 *
 * Provides persistent storage for Station/Pharmacy PWA:
 * - Inventory management
 * - Action queue (pending reports)
 * - Processed manifests
 * - Person registry
 * - Prescriber certificates (Pharmacy)
 * - Clinical records (Pharmacy, encrypted)
 * - Consumption tickets
 *
 * All data survives browser close and works offline.
 *
 * v2.0 Changes:
 * - Added PharmacyDB class with clinical stores
 * - Added prescribers store for certificate management
 * - Added clinical store for encrypted Class B data
 * - Added consumption_tickets store
 * - Added processed_rx store for Rx deduplication
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

    /**
     * PharmacyDB - Extended storage for Pharmacy Station
     * Includes clinical data stores with encryption support
     */
    const PHARMACY_DB_NAME = 'xIRS_Pharmacy';
    const PHARMACY_DB_VERSION = 1;

    class PharmacyDB {
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
                const request = indexedDB.open(PHARMACY_DB_NAME, PHARMACY_DB_VERSION);

                request.onerror = () => {
                    console.error('[PharmacyDB] Failed to open:', request.error);
                    reject(request.error);
                };

                request.onsuccess = () => {
                    this.db = request.result;
                    console.log('[PharmacyDB] Opened successfully');
                    resolve(this.db);
                };

                request.onupgradeneeded = (event) => {
                    const db = event.target.result;
                    console.log('[PharmacyDB] Upgrading schema...');

                    // Config store (station config, keys)
                    if (!db.objectStoreNames.contains('config')) {
                        db.createObjectStore('config', { keyPath: 'key' });
                    }

                    // Inventory store (medications)
                    if (!db.objectStoreNames.contains('inventory')) {
                        const invStore = db.createObjectStore('inventory', { keyPath: 'code' });
                        invStore.createIndex('category', 'category', { unique: false });
                        invStore.createIndex('is_controlled', 'is_controlled', { unique: false });
                        invStore.createIndex('name', 'name', { unique: false });
                    }

                    // Prescriber certificates
                    if (!db.objectStoreNames.contains('prescribers')) {
                        const presStore = db.createObjectStore('prescribers', { keyPath: 'id' });
                        presStore.createIndex('name', 'name', { unique: false });
                        presStore.createIndex('expires_at', 'expires_at', { unique: false });
                        presStore.createIndex('revoked', 'revoked', { unique: false });
                    }

                    // Processed prescriptions (Rx deduplication)
                    if (!db.objectStoreNames.contains('processed_rx')) {
                        const rxStore = db.createObjectStore('processed_rx', { keyPath: 'rx_id' });
                        rxStore.createIndex('processed_at', 'processed_at', { unique: false });
                        rxStore.createIndex('status', 'status', { unique: false });
                        rxStore.createIndex('nonce', 'nonce', { unique: false });
                    }

                    // Clinical records (encrypted Class B data)
                    if (!db.objectStoreNames.contains('clinical')) {
                        const clinStore = db.createObjectStore('clinical', { keyPath: 'record_id' });
                        clinStore.createIndex('type', 'type', { unique: false });
                        clinStore.createIndex('patient_ref', 'patient_ref', { unique: false });
                        clinStore.createIndex('ts', 'ts', { unique: false });
                        clinStore.createIndex('synced', 'synced', { unique: false });
                    }

                    // Dispense queue (pending Rx to fill)
                    if (!db.objectStoreNames.contains('dispense_queue')) {
                        const qStore = db.createObjectStore('dispense_queue', { keyPath: 'rx_id' });
                        qStore.createIndex('priority', 'priority', { unique: false });
                        qStore.createIndex('received_at', 'received_at', { unique: false });
                        qStore.createIndex('status', 'status', { unique: false });
                    }

                    // Action queue (pending sync)
                    if (!db.objectStoreNames.contains('actions')) {
                        const actStore = db.createObjectStore('actions', { keyPath: 'id', autoIncrement: true });
                        actStore.createIndex('type', 'type', { unique: false });
                        actStore.createIndex('ts', 'ts', { unique: false });
                        actStore.createIndex('synced', 'synced', { unique: false });
                    }

                    // Pending reports
                    if (!db.objectStoreNames.contains('reports')) {
                        const repStore = db.createObjectStore('reports', { keyPath: 'packet_id' });
                        repStore.createIndex('created_at', 'created_at', { unique: false });
                        repStore.createIndex('delivered', 'delivered', { unique: false });
                    }

                    console.log('[PharmacyDB] Schema created');
                };
            });

            return this._initPromise;
        }

        /**
         * Get object store transaction
         */
        _getStore(storeName, mode = 'readonly') {
            const tx = this.db.transaction(storeName, mode);
            return tx.objectStore(storeName);
        }

        // ===== Prescriber Certificate Methods =====

        /**
         * Add or update prescriber certificate
         * @param {Object} cert - { id, name, public_key, expires_at, revoked }
         * @returns {Promise<string>}
         */
        async putPrescriber(cert) {
            await this.init();
            const record = {
                ...cert,
                updated_at: new Date().toISOString()
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('prescribers', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get prescriber by ID
         * @param {string} id - Prescriber ID
         * @returns {Promise<Object|null>}
         */
        async getPrescriber(id) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('prescribers');
                const request = store.get(id);
                request.onsuccess = () => resolve(request.result || null);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get all valid (non-revoked, non-expired) prescribers
         * @returns {Promise<Array>}
         */
        async getValidPrescribers() {
            await this.init();
            const all = await new Promise((resolve, reject) => {
                const store = this._getStore('prescribers');
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });

            const now = Math.floor(Date.now() / 1000);
            return all.filter(p => !p.revoked && p.expires_at > now);
        }

        /**
         * Bulk update prescribers from CERT_UPDATE packet
         * @param {Array} certs - Array of certificates
         * @returns {Promise<number>} Count updated
         */
        async updatePrescribers(certs) {
            await this.init();
            let count = 0;
            for (const cert of certs) {
                await this.putPrescriber(cert);
                count++;
            }
            return count;
        }

        // ===== Processed Rx Methods =====

        /**
         * Check if Rx was already processed
         * @param {string} rxId - Rx ID
         * @returns {Promise<Object|null>}
         */
        async getProcessedRx(rxId) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('processed_rx');
                const request = store.get(rxId);
                request.onsuccess = () => resolve(request.result || null);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Record processed Rx
         * @param {string} rxId - Rx ID
         * @param {string} nonce - Rx nonce
         * @param {string} status - FILLED, PARTIAL, REJECTED
         * @param {string} pharmacistId - Pharmacist ID
         * @returns {Promise<string>}
         */
        async recordProcessedRx(rxId, nonce, status, pharmacistId) {
            await this.init();
            const record = {
                rx_id: rxId,
                nonce: nonce,
                status: status,
                pharmacist_id: pharmacistId,
                processed_at: new Date().toISOString()
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('processed_rx', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        // ===== Clinical Records Methods (Encrypted) =====

        /**
         * Store encrypted clinical record
         * @param {Object} encryptedEnvelope - { type, payload, ... }
         * @param {string} recordId - Record ID
         * @param {string} recordType - DISPENSE_RECORD, ADMIN_RECORD, etc.
         * @param {string} patientRef - Masked patient reference
         * @returns {Promise<string>}
         */
        async storeClinicalRecord(encryptedEnvelope, recordId, recordType, patientRef) {
            await this.init();
            const record = {
                record_id: recordId,
                type: recordType,
                patient_ref: patientRef,
                envelope: encryptedEnvelope,
                ts: Math.floor(Date.now() / 1000),
                synced: false,
                created_at: new Date().toISOString()
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('clinical', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get pending (unsynced) clinical records
         * @returns {Promise<Array>}
         */
        async getPendingClinicalRecords() {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('clinical');
                const index = store.index('synced');
                const request = index.getAll(IDBKeyRange.only(false));
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Mark clinical records as synced
         * @param {Array<string>} recordIds - Record IDs
         * @returns {Promise<number>}
         */
        async markClinicalRecordsSynced(recordIds) {
            await this.init();
            let count = 0;

            for (const id of recordIds) {
                await new Promise((resolve, reject) => {
                    const store = this._getStore('clinical', 'readwrite');
                    const request = store.get(id);
                    request.onsuccess = () => {
                        const record = request.result;
                        if (record) {
                            record.synced = true;
                            record.synced_at = new Date().toISOString();
                            store.put(record);
                            count++;
                        }
                        resolve();
                    };
                    request.onerror = () => reject(request.error);
                });
            }

            return count;
        }

        // ===== Dispense Queue Methods =====

        /**
         * Add Rx to dispense queue
         * @param {Object} rx - Rx order object
         * @returns {Promise<string>}
         */
        async addToDispenseQueue(rx) {
            await this.init();
            const record = {
                rx_id: rx.rx_id,
                prescriber_id: rx.prescriber_id,
                patient_ref: rx.patient_ref,
                items: rx.items,
                priority: rx.priority || 'ROUTINE',
                status: 'PENDING',
                received_at: new Date().toISOString(),
                original_rx: rx
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('dispense_queue', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get pending Rx queue sorted by priority
         * @returns {Promise<Array>}
         */
        async getDispenseQueue() {
            await this.init();
            const all = await new Promise((resolve, reject) => {
                const store = this._getStore('dispense_queue');
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });

            // Sort by priority (STAT > URGENT > ROUTINE), then by received_at
            const priorityOrder = { STAT: 0, URGENT: 1, ROUTINE: 2 };
            return all
                .filter(r => r.status === 'PENDING')
                .sort((a, b) => {
                    const pDiff = (priorityOrder[a.priority] || 2) - (priorityOrder[b.priority] || 2);
                    if (pDiff !== 0) return pDiff;
                    return new Date(a.received_at) - new Date(b.received_at);
                });
        }

        /**
         * Update Rx status in queue
         * @param {string} rxId - Rx ID
         * @param {string} status - PENDING, FILLING, FILLED, REJECTED
         * @returns {Promise<void>}
         */
        async updateDispenseStatus(rxId, status) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('dispense_queue', 'readwrite');
                const request = store.get(rxId);
                request.onsuccess = () => {
                    const record = request.result;
                    if (record) {
                        record.status = status;
                        record.updated_at = new Date().toISOString();
                        store.put(record);
                    }
                    resolve();
                };
                request.onerror = () => reject(request.error);
            });
        }

        // ===== Inventory Methods (with medication specifics) =====

        /**
         * Get all medications
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
         * Get controlled substances only
         * @returns {Promise<Array>}
         */
        async getControlledSubstances() {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('inventory');
                const index = store.index('is_controlled');
                const request = index.getAll(IDBKeyRange.only(true));
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Add or update medication
         * @param {Object} med - Medication object
         * @returns {Promise<string>}
         */
        async putMedication(med) {
            await this.init();
            const record = {
                ...med,
                updated_at: new Date().toISOString()
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('inventory', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Deduct medication quantity
         * @param {string} code - Medication code
         * @param {number} qty - Quantity to deduct
         * @returns {Promise<Object>} Updated medication
         */
        async deductMedication(code, qty) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('inventory', 'readwrite');
                const request = store.get(code);
                request.onsuccess = () => {
                    const med = request.result;
                    if (!med) {
                        reject(new Error(`Medication not found: ${code}`));
                        return;
                    }
                    med.quantity = Math.max(0, (med.quantity || 0) - qty);
                    med.updated_at = new Date().toISOString();
                    store.put(med);
                    resolve(med);
                };
                request.onerror = () => reject(request.error);
            });
        }

        // ===== Config Methods =====

        /**
         * Get config value
         * @param {string} key - Config key
         * @returns {Promise<any>}
         */
        async getConfig(key) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('config');
                const request = store.get(key);
                request.onsuccess = () => {
                    const result = request.result;
                    resolve(result ? result.value : null);
                };
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Set config value
         * @param {string} key - Config key
         * @param {any} value - Config value
         * @returns {Promise<void>}
         */
        async setConfig(key, value) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('config', 'readwrite');
                const request = store.put({ key, value, updated_at: new Date().toISOString() });
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });
        }

        // ===== Utility Methods =====

        /**
         * Clear all data
         * @returns {Promise<void>}
         */
        async clearAll() {
            await this.init();
            const stores = ['config', 'inventory', 'prescribers', 'processed_rx',
                           'clinical', 'dispense_queue', 'actions', 'reports'];

            for (const storeName of stores) {
                await new Promise((resolve, reject) => {
                    const store = this._getStore(storeName, 'readwrite');
                    const request = store.clear();
                    request.onsuccess = () => resolve();
                    request.onerror = () => reject(request.error);
                });
            }

            console.log('[PharmacyDB] All data cleared');
        }

        /**
         * Export all data
         * @returns {Promise<Object>}
         */
        async exportAll() {
            await this.init();
            const stores = ['config', 'inventory', 'prescribers', 'processed_rx',
                           'clinical', 'dispense_queue', 'actions', 'reports'];

            const data = {};
            for (const storeName of stores) {
                data[storeName] = await new Promise((resolve, reject) => {
                    const store = this._getStore(storeName);
                    const request = store.getAll();
                    request.onsuccess = () => resolve(request.result);
                    request.onerror = () => reject(request.error);
                });
            }

            data.exported_at = new Date().toISOString();
            return data;
        }
    }

    /**
     * ConsumptionTicketStore - For CONSUMPTION_TICKET deduplication
     * Used by both Supply Station and Pharmacy Station
     */
    class ConsumptionTicketStore {
        constructor(db) {
            this.db = db;
        }

        /**
         * Check if ticket was already processed
         * @param {string} ticketId - Ticket ID
         * @returns {Promise<boolean>}
         */
        async isProcessed(ticketId) {
            // Use localStorage for simplicity (can be upgraded to IndexedDB if needed)
            const key = `xirs_ticket_${ticketId}`;
            return localStorage.getItem(key) !== null;
        }

        /**
         * Record processed ticket
         * @param {string} ticketId - Ticket ID
         * @param {string} eventRef - Event reference
         * @returns {void}
         */
        recordProcessed(ticketId, eventRef) {
            const key = `xirs_ticket_${ticketId}`;
            localStorage.setItem(key, JSON.stringify({
                event_ref: eventRef,
                processed_at: new Date().toISOString()
            }));
        }

        /**
         * Clear old tickets (older than 7 days)
         */
        cleanupOld() {
            const now = Date.now();
            const maxAge = 7 * 24 * 60 * 60 * 1000; // 7 days

            for (let i = localStorage.length - 1; i >= 0; i--) {
                const key = localStorage.key(i);
                if (key && key.startsWith('xirs_ticket_')) {
                    try {
                        const data = JSON.parse(localStorage.getItem(key));
                        const processed = new Date(data.processed_at).getTime();
                        if (now - processed > maxAge) {
                            localStorage.removeItem(key);
                        }
                    } catch (e) {
                        // Invalid data, remove it
                        localStorage.removeItem(key);
                    }
                }
            }
        }
    }

    // Export singletons
    global.xIRS = global.xIRS || {};
    global.xIRS.StationDB = new StationDB();
    global.xIRS.PharmacyDB = new PharmacyDB();
    global.xIRS.ConsumptionTicketStore = new ConsumptionTicketStore();

    console.log('[xIRS Storage] v2.0.0 loaded');

})(typeof window !== 'undefined' ? window : global);
