/**
 * xIRS Pharmacy IndexedDB Storage v1.0
 *
 * Provides offline storage for Pharmacy Station:
 * - Prescriber certificates
 * - Processed Rx records
 * - Dispense queue
 * - Medication inventory (pharmacy-specific)
 * - Dispense records pending sync
 *
 * Dependencies: None (vanilla IndexedDB)
 */

(function(global) {
    'use strict';

    const DB_NAME = 'xIRS_Pharmacy';
    const DB_VERSION = 1;

    /**
     * PharmacyDB - IndexedDB wrapper for Pharmacy Station
     */
    class PharmacyDB {
        constructor() {
            this.db = null;
            this._initPromise = null;
        }

        /**
         * Initialize the database
         * @returns {Promise<boolean>}
         */
        async init() {
            if (this.db) return true;
            if (this._initPromise) return this._initPromise;

            this._initPromise = new Promise((resolve, reject) => {
                const request = indexedDB.open(DB_NAME, DB_VERSION);

                request.onerror = () => {
                    console.error('[PharmacyDB] Failed to open:', request.error);
                    reject(request.error);
                };

                request.onsuccess = () => {
                    this.db = request.result;
                    console.log('[PharmacyDB] Opened successfully');
                    resolve(true);
                };

                request.onupgradeneeded = (event) => {
                    const db = event.target.result;
                    this._createStores(db);
                };
            });

            return this._initPromise;
        }

        /**
         * Create object stores
         */
        _createStores(db) {
            // Prescriber certificates
            if (!db.objectStoreNames.contains('prescriber_certs')) {
                const store = db.createObjectStore('prescriber_certs', { keyPath: 'prescriber_id' });
                store.createIndex('valid_until', 'valid_until', { unique: false });
            }

            // Processed Rx records (for duplicate detection)
            if (!db.objectStoreNames.contains('processed_rx')) {
                const store = db.createObjectStore('processed_rx', { keyPath: 'rx_id' });
                store.createIndex('processed_at', 'processed_at', { unique: false });
                store.createIndex('patient_id', 'patient_id', { unique: false });
            }

            // Dispense queue (pending Rx to be dispensed)
            if (!db.objectStoreNames.contains('dispense_queue')) {
                const store = db.createObjectStore('dispense_queue', { keyPath: 'rx_id' });
                store.createIndex('priority', 'priority', { unique: false });
                store.createIndex('received_at', 'received_at', { unique: false });
                store.createIndex('status', 'status', { unique: false });
            }

            // Medication inventory (pharmacy-specific)
            if (!db.objectStoreNames.contains('medication_inventory')) {
                const store = db.createObjectStore('medication_inventory', { keyPath: 'code' });
                store.createIndex('is_controlled', 'is_controlled', { unique: false });
                store.createIndex('category', 'category', { unique: false });
            }

            // Dispense records pending sync to Hub
            if (!db.objectStoreNames.contains('pending_dispense')) {
                const store = db.createObjectStore('pending_dispense', { keyPath: 'dispense_id' });
                store.createIndex('created_at', 'created_at', { unique: false });
            }

            // Dispense history (local archive)
            if (!db.objectStoreNames.contains('dispense_history')) {
                const store = db.createObjectStore('dispense_history', { keyPath: 'dispense_id' });
                store.createIndex('rx_id', 'rx_id', { unique: false });
                store.createIndex('patient_id', 'patient_id', { unique: false });
                store.createIndex('ts', 'ts', { unique: false });
            }

            // Station settings
            if (!db.objectStoreNames.contains('settings')) {
                db.createObjectStore('settings', { keyPath: 'key' });
            }

            console.log('[PharmacyDB] Stores created');
        }

        // ==================== Prescriber Certificates ====================

        /**
         * Save prescriber certificate
         * @param {Object} cert - PRESCRIBER_CERT
         */
        async saveCertificate(cert) {
            await this.init();
            return this._put('prescriber_certs', cert);
        }

        /**
         * Save multiple certificates
         * @param {Array} certs
         */
        async saveCertificates(certs) {
            await this.init();
            const tx = this.db.transaction('prescriber_certs', 'readwrite');
            const store = tx.objectStore('prescriber_certs');
            for (const cert of certs) {
                store.put(cert);
            }
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve(certs.length);
                tx.onerror = () => reject(tx.error);
            });
        }

        /**
         * Get certificate by prescriber ID
         * @param {string} prescriberId
         * @returns {Promise<Object|null>}
         */
        async getCertificate(prescriberId) {
            await this.init();
            return this._get('prescriber_certs', prescriberId);
        }

        /**
         * Get all certificates
         * @returns {Promise<Array>}
         */
        async getAllCertificates() {
            await this.init();
            return this._getAll('prescriber_certs');
        }

        /**
         * Delete certificate
         * @param {string} prescriberId
         */
        async deleteCertificate(prescriberId) {
            await this.init();
            return this._delete('prescriber_certs', prescriberId);
        }

        // ==================== Processed Rx ====================

        /**
         * Record a processed Rx
         * @param {Object} rxOrder - Original RX_ORDER
         * @param {string} status - DispenseStatus
         * @param {string} pharmacistId
         */
        async recordProcessedRx(rxOrder, status, pharmacistId) {
            await this.init();
            const record = {
                rx_id: rxOrder.rx_id,
                nonce: rxOrder.nonce,
                patient_id: rxOrder.patient?.id || null,
                patient_name: rxOrder.patient?.name || null,
                prescriber_id: rxOrder.prescriber_id,
                prescriber_name: rxOrder.prescriber_name,
                items: rxOrder.items,
                priority: rxOrder.priority,
                status: status,
                pharmacist_id: pharmacistId,
                processed_at: new Date().toISOString()
            };
            return this._put('processed_rx', record);
        }

        /**
         * Check if Rx is already processed
         * @param {string} rxId
         * @returns {Promise<Object|null>} Existing record or null
         */
        async checkProcessedRx(rxId) {
            await this.init();
            return this._get('processed_rx', rxId);
        }

        /**
         * Get processed Rx by patient
         * @param {string} patientId
         * @returns {Promise<Array>}
         */
        async getProcessedRxByPatient(patientId) {
            await this.init();
            return this._getByIndex('processed_rx', 'patient_id', patientId);
        }

        // ==================== Dispense Queue ====================

        /**
         * Add Rx to dispense queue
         * @param {Object} rxOrder
         * @param {Object} verification - RxVerifier result
         */
        async addToQueue(rxOrder, verification) {
            await this.init();
            const entry = {
                rx_id: rxOrder.rx_id,
                rx_data: rxOrder,
                verification: verification,
                priority: rxOrder.priority || 'ROUTINE',
                received_at: new Date().toISOString(),
                status: 'PENDING'
            };
            return this._put('dispense_queue', entry);
        }

        /**
         * Get queue entry
         * @param {string} rxId
         */
        async getQueueEntry(rxId) {
            await this.init();
            return this._get('dispense_queue', rxId);
        }

        /**
         * Get all pending in queue
         * @returns {Promise<Array>}
         */
        async getPendingQueue() {
            await this.init();
            const all = await this._getByIndex('dispense_queue', 'status', 'PENDING');
            // Sort by priority then by received time
            const priorityOrder = { STAT: 0, URGENT: 1, ROUTINE: 2 };
            return all.sort((a, b) => {
                const pA = priorityOrder[a.priority] || 2;
                const pB = priorityOrder[b.priority] || 2;
                if (pA !== pB) return pA - pB;
                return new Date(a.received_at) - new Date(b.received_at);
            });
        }

        /**
         * Update queue entry status
         * @param {string} rxId
         * @param {string} status
         */
        async updateQueueStatus(rxId, status) {
            await this.init();
            const entry = await this._get('dispense_queue', rxId);
            if (entry) {
                entry.status = status;
                if (status === 'COMPLETED' || status === 'REJECTED') {
                    entry.completed_at = new Date().toISOString();
                }
                return this._put('dispense_queue', entry);
            }
        }

        /**
         * Remove from queue
         * @param {string} rxId
         */
        async removeFromQueue(rxId) {
            await this.init();
            return this._delete('dispense_queue', rxId);
        }

        /**
         * Get queue stats
         */
        async getQueueStats() {
            await this.init();
            const all = await this._getAll('dispense_queue');
            const stats = {
                total: all.length,
                pending: 0,
                inProgress: 0,
                completed: 0,
                byPriority: { STAT: 0, URGENT: 0, ROUTINE: 0 }
            };
            for (const entry of all) {
                if (entry.status === 'PENDING') stats.pending++;
                else if (entry.status === 'IN_PROGRESS') stats.inProgress++;
                else if (entry.status === 'COMPLETED') stats.completed++;

                const priority = entry.priority || 'ROUTINE';
                if (stats.byPriority[priority] !== undefined) {
                    stats.byPriority[priority]++;
                }
            }
            return stats;
        }

        // ==================== Medication Inventory ====================

        /**
         * Save medication
         * @param {Object} med - { code, name, quantity, unit, is_controlled, schedule, ... }
         */
        async saveMedication(med) {
            await this.init();
            return this._put('medication_inventory', med);
        }

        /**
         * Save multiple medications
         */
        async saveMedications(meds) {
            await this.init();
            const tx = this.db.transaction('medication_inventory', 'readwrite');
            const store = tx.objectStore('medication_inventory');
            for (const med of meds) {
                store.put(med);
            }
            return new Promise((resolve, reject) => {
                tx.oncomplete = () => resolve(meds.length);
                tx.onerror = () => reject(tx.error);
            });
        }

        /**
         * Get medication by code
         * @param {string} code
         */
        async getMedication(code) {
            await this.init();
            return this._get('medication_inventory', code);
        }

        /**
         * Get all medications
         */
        async getAllMedications() {
            await this.init();
            return this._getAll('medication_inventory');
        }

        /**
         * Get controlled medications
         */
        async getControlledMedications() {
            await this.init();
            return this._getByIndex('medication_inventory', 'is_controlled', true);
        }

        /**
         * Update medication quantity
         * @param {string} code
         * @param {number} delta - Change in quantity (negative for dispensed)
         */
        async updateMedicationQuantity(code, delta) {
            await this.init();
            const med = await this._get('medication_inventory', code);
            if (med) {
                med.quantity = Math.max(0, (med.quantity || 0) + delta);
                med.updated_at = new Date().toISOString();
                return this._put('medication_inventory', med);
            }
            return null;
        }

        /**
         * Check inventory for Rx items
         * @param {Array} items - RX_ORDER items
         * @returns {Promise<Object>} { allAvailable, shortages: [] }
         */
        async checkInventoryForRx(items) {
            await this.init();
            const shortages = [];
            let allAvailable = true;

            for (const item of items) {
                const med = await this._get('medication_inventory', item.code);
                const available = med?.quantity || 0;
                const needed = item.qty;

                if (available < needed) {
                    allAvailable = false;
                    shortages.push({
                        code: item.code,
                        name: item.name,
                        needed: needed,
                        available: available,
                        shortage: needed - available
                    });
                }
            }

            return { allAvailable, shortages };
        }

        // ==================== Pending Dispense (to sync) ====================

        /**
         * Save pending dispense record
         * @param {Object} dispenseRecord - DISPENSE_RECORD
         */
        async savePendingDispense(dispenseRecord) {
            await this.init();
            const record = {
                ...dispenseRecord,
                created_at: new Date().toISOString()
            };
            return this._put('pending_dispense', record);
        }

        /**
         * Get all pending dispense records
         */
        async getPendingDispenses() {
            await this.init();
            return this._getAll('pending_dispense');
        }

        /**
         * Clear pending dispense (after sync)
         * @param {string} dispenseId
         */
        async clearPendingDispense(dispenseId) {
            await this.init();
            return this._delete('pending_dispense', dispenseId);
        }

        /**
         * Clear all pending (after full sync)
         */
        async clearAllPendingDispenses() {
            await this.init();
            return this._clear('pending_dispense');
        }

        // ==================== Dispense History ====================

        /**
         * Archive dispense record to history
         * @param {Object} dispenseRecord
         */
        async archiveDispense(dispenseRecord) {
            await this.init();
            return this._put('dispense_history', dispenseRecord);
        }

        /**
         * Get dispense history by date range
         * @param {number} fromTs - Unix timestamp
         * @param {number} toTs - Unix timestamp
         */
        async getDispenseHistory(fromTs, toTs) {
            await this.init();
            const all = await this._getAll('dispense_history');
            return all.filter(d => d.ts >= fromTs && d.ts <= toTs)
                      .sort((a, b) => b.ts - a.ts);
        }

        /**
         * Get dispense history by patient
         * @param {string} patientId
         */
        async getDispenseHistoryByPatient(patientId) {
            await this.init();
            return this._getByIndex('dispense_history', 'patient_id', patientId);
        }

        // ==================== Settings ====================

        /**
         * Save setting
         * @param {string} key
         * @param {*} value
         */
        async setSetting(key, value) {
            await this.init();
            return this._put('settings', { key, value });
        }

        /**
         * Get setting
         * @param {string} key
         * @returns {Promise<*>}
         */
        async getSetting(key) {
            await this.init();
            const record = await this._get('settings', key);
            return record?.value;
        }

        /**
         * Get all settings
         */
        async getAllSettings() {
            await this.init();
            const all = await this._getAll('settings');
            const settings = {};
            for (const { key, value } of all) {
                settings[key] = value;
            }
            return settings;
        }

        // ==================== Helpers ====================

        _put(storeName, data) {
            return new Promise((resolve, reject) => {
                const tx = this.db.transaction(storeName, 'readwrite');
                const store = tx.objectStore(storeName);
                const request = store.put(data);
                request.onsuccess = () => resolve(data);
                request.onerror = () => reject(request.error);
            });
        }

        _get(storeName, key) {
            return new Promise((resolve, reject) => {
                const tx = this.db.transaction(storeName, 'readonly');
                const store = tx.objectStore(storeName);
                const request = store.get(key);
                request.onsuccess = () => resolve(request.result || null);
                request.onerror = () => reject(request.error);
            });
        }

        _getAll(storeName) {
            return new Promise((resolve, reject) => {
                const tx = this.db.transaction(storeName, 'readonly');
                const store = tx.objectStore(storeName);
                const request = store.getAll();
                request.onsuccess = () => resolve(request.result || []);
                request.onerror = () => reject(request.error);
            });
        }

        _getByIndex(storeName, indexName, value) {
            return new Promise((resolve, reject) => {
                const tx = this.db.transaction(storeName, 'readonly');
                const store = tx.objectStore(storeName);
                const index = store.index(indexName);
                const request = index.getAll(value);
                request.onsuccess = () => resolve(request.result || []);
                request.onerror = () => reject(request.error);
            });
        }

        _delete(storeName, key) {
            return new Promise((resolve, reject) => {
                const tx = this.db.transaction(storeName, 'readwrite');
                const store = tx.objectStore(storeName);
                const request = store.delete(key);
                request.onsuccess = () => resolve(true);
                request.onerror = () => reject(request.error);
            });
        }

        _clear(storeName) {
            return new Promise((resolve, reject) => {
                const tx = this.db.transaction(storeName, 'readwrite');
                const store = tx.objectStore(storeName);
                const request = store.clear();
                request.onsuccess = () => resolve(true);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Export all data for backup
         */
        async exportAll() {
            await this.init();
            return {
                prescriber_certs: await this._getAll('prescriber_certs'),
                processed_rx: await this._getAll('processed_rx'),
                dispense_queue: await this._getAll('dispense_queue'),
                medication_inventory: await this._getAll('medication_inventory'),
                pending_dispense: await this._getAll('pending_dispense'),
                dispense_history: await this._getAll('dispense_history'),
                settings: await this._getAll('settings'),
                exported_at: new Date().toISOString()
            };
        }

        /**
         * Close database
         */
        close() {
            if (this.db) {
                this.db.close();
                this.db = null;
                this._initPromise = null;
            }
        }
    }

    // Singleton instance
    const pharmacyDB = new PharmacyDB();

    // Export
    if (global.xIRS) {
        global.xIRS.PharmacyDB = pharmacyDB;
    } else {
        global.xIRS = { PharmacyDB: pharmacyDB };
    }

    console.log('[xIRS PharmacyDB] v1.0.0 loaded');

})(typeof window !== 'undefined' ? window : global);
