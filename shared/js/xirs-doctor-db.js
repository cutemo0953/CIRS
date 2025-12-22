/**
 * xIRS Doctor IndexedDB Storage v1.0
 *
 * Provides offline storage for Doctor PWA:
 * - Prescriber credentials (encrypted private key)
 * - Recent patients
 * - Issued Rx history
 * - Medication catalog
 *
 * Dependencies: None (vanilla IndexedDB)
 */

(function(global) {
    'use strict';

    const DB_NAME = 'xIRS_Doctor';
    const DB_VERSION = 1;

    /**
     * DoctorDB - IndexedDB wrapper for Doctor PWA
     */
    class DoctorDB {
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
                    console.error('[DoctorDB] Failed to open:', request.error);
                    reject(request.error);
                };

                request.onsuccess = () => {
                    this.db = request.result;
                    console.log('[DoctorDB] Opened successfully');
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
            // Prescriber credentials (encrypted)
            if (!db.objectStoreNames.contains('credentials')) {
                db.createObjectStore('credentials', { keyPath: 'id' });
            }

            // Recent patients
            if (!db.objectStoreNames.contains('patients')) {
                const store = db.createObjectStore('patients', { keyPath: 'patient_id' });
                store.createIndex('last_seen', 'last_seen', { unique: false });
                store.createIndex('name', 'name', { unique: false });
            }

            // Issued Rx history
            if (!db.objectStoreNames.contains('issued_rx')) {
                const store = db.createObjectStore('issued_rx', { keyPath: 'rx_id' });
                store.createIndex('patient_id', 'patient_id', { unique: false });
                store.createIndex('issued_at', 'issued_at', { unique: false });
            }

            // Medication catalog
            if (!db.objectStoreNames.contains('medication_catalog')) {
                const store = db.createObjectStore('medication_catalog', { keyPath: 'code' });
                store.createIndex('category', 'category', { unique: false });
                store.createIndex('name', 'name', { unique: false });
            }

            // Settings
            if (!db.objectStoreNames.contains('settings')) {
                db.createObjectStore('settings', { keyPath: 'key' });
            }

            // Favorites (frequently prescribed medications)
            if (!db.objectStoreNames.contains('favorites')) {
                const store = db.createObjectStore('favorites', { keyPath: 'code' });
                store.createIndex('use_count', 'use_count', { unique: false });
            }

            // Prescription templates
            if (!db.objectStoreNames.contains('templates')) {
                const store = db.createObjectStore('templates', { keyPath: 'id' });
                store.createIndex('name', 'name', { unique: false });
            }

            console.log('[DoctorDB] Stores created');
        }

        // ==================== Credentials ====================

        /**
         * Save prescriber credentials
         * @param {Object} cred - { prescriber_id, name, private_key, public_key, certificate }
         * @param {string} [pin] - Optional PIN to encrypt private key
         */
        async saveCredentials(cred, pin) {
            await this.init();

            const record = {
                id: 'primary', // Only one credential per device
                prescriber_id: cred.prescriber_id,
                name: cred.name,
                title: cred.title || '醫師',
                license_no: cred.license_no || null,
                public_key: cred.public_key,
                certificate: cred.certificate || null,
                created_at: new Date().toISOString()
            };

            // In a real implementation, we'd encrypt the private key with the PIN
            // For now, we store it directly (in production, use WebCrypto)
            if (pin) {
                record.private_key_encrypted = await this._encryptWithPin(cred.private_key, pin);
                record.has_pin = true;
            } else {
                record.private_key = cred.private_key;
                record.has_pin = false;
            }

            return this._put('credentials', record);
        }

        /**
         * Get prescriber credentials
         * @param {string} [pin] - PIN to decrypt private key
         * @returns {Promise<Object|null>}
         */
        async getCredentials(pin) {
            await this.init();
            const record = await this._get('credentials', 'primary');

            if (!record) return null;

            const result = {
                prescriber_id: record.prescriber_id,
                name: record.name,
                title: record.title,
                license_no: record.license_no,
                public_key: record.public_key,
                certificate: record.certificate,
                has_pin: record.has_pin
            };

            if (record.has_pin && pin) {
                try {
                    result.private_key = await this._decryptWithPin(record.private_key_encrypted, pin);
                } catch (e) {
                    console.error('[DoctorDB] Failed to decrypt private key');
                    return null;
                }
            } else if (!record.has_pin) {
                result.private_key = record.private_key;
            }

            return result;
        }

        /**
         * Check if credentials exist
         * @returns {Promise<boolean>}
         */
        async hasCredentials() {
            await this.init();
            const record = await this._get('credentials', 'primary');
            return !!record;
        }

        /**
         * Clear credentials (logout)
         */
        async clearCredentials() {
            await this.init();
            return this._delete('credentials', 'primary');
        }

        /**
         * Simple PIN-based encryption (for demo - use proper crypto in production)
         */
        async _encryptWithPin(data, pin) {
            // In production, use WebCrypto PBKDF2 + AES-GCM
            // This is a placeholder that provides basic obfuscation
            const encoder = new TextEncoder();
            const pinBytes = encoder.encode(pin);
            const dataBytes = encoder.encode(data);

            // XOR with repeated PIN (NOT secure - demo only)
            const encrypted = new Uint8Array(dataBytes.length);
            for (let i = 0; i < dataBytes.length; i++) {
                encrypted[i] = dataBytes[i] ^ pinBytes[i % pinBytes.length];
            }

            return btoa(String.fromCharCode(...encrypted));
        }

        async _decryptWithPin(encrypted, pin) {
            const encoder = new TextEncoder();
            const pinBytes = encoder.encode(pin);
            const encryptedBytes = Uint8Array.from(atob(encrypted), c => c.charCodeAt(0));

            const decrypted = new Uint8Array(encryptedBytes.length);
            for (let i = 0; i < encryptedBytes.length; i++) {
                decrypted[i] = encryptedBytes[i] ^ pinBytes[i % pinBytes.length];
            }

            return new TextDecoder().decode(decrypted);
        }

        // ==================== Patients ====================

        /**
         * Save/update patient
         * @param {Object} patient - { patient_id, name, age_group, weight_kg, notes }
         */
        async savePatient(patient) {
            await this.init();
            const record = {
                ...patient,
                last_seen: new Date().toISOString()
            };
            return this._put('patients', record);
        }

        /**
         * Get patient by ID
         * @param {string} patientId
         */
        async getPatient(patientId) {
            await this.init();
            return this._get('patients', patientId);
        }

        /**
         * Get recent patients
         * @param {number} limit
         */
        async getRecentPatients(limit = 10) {
            await this.init();
            const all = await this._getAll('patients');
            return all
                .sort((a, b) => new Date(b.last_seen) - new Date(a.last_seen))
                .slice(0, limit);
        }

        /**
         * Search patients by name
         * @param {string} query
         */
        async searchPatients(query) {
            await this.init();
            const all = await this._getAll('patients');
            const lowerQuery = query.toLowerCase();
            return all.filter(p =>
                p.name?.toLowerCase().includes(lowerQuery) ||
                p.patient_id?.toLowerCase().includes(lowerQuery)
            );
        }

        /**
         * Get all patients
         */
        async getAllPatients() {
            await this.init();
            return this._getAll('patients');
        }

        /**
         * Delete patient
         * @param {string} patientId
         */
        async deletePatient(patientId) {
            await this.init();
            return this._delete('patients', patientId);
        }

        // ==================== Issued Rx ====================

        /**
         * Record issued Rx
         * @param {Object} rxOrder - The RX_ORDER that was issued
         */
        async recordIssuedRx(rxOrder) {
            await this.init();
            const record = {
                rx_id: rxOrder.rx_id,
                patient_id: rxOrder.patient?.id,
                patient_name: rxOrder.patient?.name,
                items: rxOrder.items,
                priority: rxOrder.priority,
                diagnosis_text: rxOrder.diagnosis_text,
                note: rxOrder.note,
                issued_at: new Date().toISOString(),
                qr_displayed: true
            };
            return this._put('issued_rx', record);
        }

        /**
         * Get Rx by ID
         * @param {string} rxId
         */
        async getIssuedRx(rxId) {
            await this.init();
            return this._get('issued_rx', rxId);
        }

        /**
         * Get Rx by patient
         * @param {string} patientId
         */
        async getIssuedRxByPatient(patientId) {
            await this.init();
            return this._getByIndex('issued_rx', 'patient_id', patientId);
        }

        /**
         * Get recent issued Rx
         * @param {number} limit
         */
        async getRecentIssuedRx(limit = 20) {
            await this.init();
            const all = await this._getAll('issued_rx');
            return all
                .sort((a, b) => new Date(b.issued_at) - new Date(a.issued_at))
                .slice(0, limit);
        }

        /**
         * Get today's Rx count
         */
        async getTodayRxCount() {
            await this.init();
            const today = new Date().toISOString().slice(0, 10);
            const all = await this._getAll('issued_rx');
            return all.filter(rx => rx.issued_at?.startsWith(today)).length;
        }

        // ==================== Medication Catalog ====================

        /**
         * Save medication
         * @param {Object} med - { code, name, category, default_dose, default_freq, ... }
         */
        async saveMedication(med) {
            await this.init();
            return this._put('medication_catalog', med);
        }

        /**
         * Save multiple medications (bulk import)
         */
        async saveMedications(meds) {
            await this.init();
            const tx = this.db.transaction('medication_catalog', 'readwrite');
            const store = tx.objectStore('medication_catalog');
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
            return this._get('medication_catalog', code);
        }

        /**
         * Get all medications
         */
        async getAllMedications() {
            await this.init();
            return this._getAll('medication_catalog');
        }

        /**
         * Get medications by category
         * @param {string} category
         */
        async getMedicationsByCategory(category) {
            await this.init();
            return this._getByIndex('medication_catalog', 'category', category);
        }

        /**
         * Search medications
         * @param {string} query
         */
        async searchMedications(query) {
            await this.init();
            const all = await this._getAll('medication_catalog');
            const lowerQuery = query.toLowerCase();
            return all.filter(m =>
                m.name?.toLowerCase().includes(lowerQuery) ||
                m.code?.toLowerCase().includes(lowerQuery)
            );
        }

        // ==================== Favorites ====================

        /**
         * Add to favorites / increment use count
         * @param {string} code - Medication code
         */
        async addFavorite(code) {
            await this.init();
            let fav = await this._get('favorites', code);
            if (fav) {
                fav.use_count = (fav.use_count || 0) + 1;
                fav.last_used = new Date().toISOString();
            } else {
                fav = {
                    code,
                    use_count: 1,
                    last_used: new Date().toISOString()
                };
            }
            return this._put('favorites', fav);
        }

        /**
         * Get top favorites
         * @param {number} limit
         */
        async getTopFavorites(limit = 10) {
            await this.init();
            const all = await this._getAll('favorites');
            const sorted = all.sort((a, b) => b.use_count - a.use_count);
            const codes = sorted.slice(0, limit).map(f => f.code);

            // Get full medication info
            const meds = [];
            for (const code of codes) {
                const med = await this._get('medication_catalog', code);
                if (med) {
                    const fav = await this._get('favorites', code);
                    meds.push({ ...med, use_count: fav?.use_count || 0 });
                }
            }
            return meds;
        }

        // ==================== Templates ====================

        /**
         * Save prescription template
         * @param {Object} template - { name, diagnosis, items: [...] }
         */
        async saveTemplate(template) {
            await this.init();
            const record = {
                id: template.id || `TPL-${Date.now()}`,
                name: template.name,
                diagnosis: template.diagnosis || null,
                items: template.items,
                created_at: template.created_at || new Date().toISOString(),
                updated_at: new Date().toISOString()
            };
            return this._put('templates', record);
        }

        /**
         * Get template by ID
         * @param {string} id
         */
        async getTemplate(id) {
            await this.init();
            return this._get('templates', id);
        }

        /**
         * Get all templates
         */
        async getAllTemplates() {
            await this.init();
            return this._getAll('templates');
        }

        /**
         * Delete template
         * @param {string} id
         */
        async deleteTemplate(id) {
            await this.init();
            return this._delete('templates', id);
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

        /**
         * Export all data for backup
         */
        async exportAll() {
            await this.init();
            return {
                patients: await this._getAll('patients'),
                issued_rx: await this._getAll('issued_rx'),
                medication_catalog: await this._getAll('medication_catalog'),
                favorites: await this._getAll('favorites'),
                templates: await this._getAll('templates'),
                settings: await this._getAll('settings'),
                // Note: credentials are NOT exported for security
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
    const doctorDB = new DoctorDB();

    // Export
    if (global.xIRS) {
        global.xIRS.DoctorDB = doctorDB;
    } else {
        global.xIRS = { DoctorDB: doctorDB };
    }

    console.log('[xIRS DoctorDB] v1.0.0 loaded');

})(typeof window !== 'undefined' ? window : global);
