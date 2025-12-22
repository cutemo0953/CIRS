/**
 * xIRS Runner Library v1.8 - Blind Carrier Storage
 *
 * Provides packet storage for Runner PWA:
 * - Opaque packet storage (cannot decrypt)
 * - Multi-packet queue
 * - Delivery status tracking
 * - Priority/urgency detection
 *
 * Runner can only transport packets, never read their contents.
 */

(function(global) {
    'use strict';

    const DB_NAME = 'xIRS_Runner';
    const DB_VERSION = 1;

    /**
     * Packet priority levels
     */
    const Priority = {
        NORMAL: 'NORMAL',
        HIGH: 'HIGH',
        CRITICAL: 'CRITICAL'
    };

    /**
     * IndexedDB wrapper for Runner
     */
    class RunnerDB {
        constructor() {
            this.db = null;
            this._initPromise = null;
        }

        /**
         * Initialize database
         */
        async init() {
            if (this.db) return this.db;
            if (this._initPromise) return this._initPromise;

            this._initPromise = new Promise((resolve, reject) => {
                const request = indexedDB.open(DB_NAME, DB_VERSION);

                request.onerror = () => {
                    console.error('[RunnerDB] Failed to open:', request.error);
                    reject(request.error);
                };

                request.onsuccess = () => {
                    this.db = request.result;
                    console.log('[RunnerDB] Opened successfully');
                    resolve(this.db);
                };

                request.onupgradeneeded = (event) => {
                    const db = event.target.result;
                    console.log('[RunnerDB] Upgrading schema...');

                    // Packets store (opaque blobs)
                    if (!db.objectStoreNames.contains('packets')) {
                        const store = db.createObjectStore('packets', { keyPath: 'id' });
                        store.createIndex('source', 'source', { unique: false });
                        store.createIndex('priority', 'priority', { unique: false });
                        store.createIndex('picked_at', 'picked_at', { unique: false });
                        store.createIndex('delivered', 'delivered', { unique: false });
                    }

                    // Delivery history
                    if (!db.objectStoreNames.contains('history')) {
                        const store = db.createObjectStore('history', { keyPath: 'id', autoIncrement: true });
                        store.createIndex('delivered_at', 'delivered_at', { unique: false });
                    }

                    console.log('[RunnerDB] Schema created');
                };
            });

            return this._initPromise;
        }

        _getStore(storeName, mode = 'readonly') {
            const tx = this.db.transaction(storeName, mode);
            return tx.objectStore(storeName);
        }

        // ===== Packet Methods =====

        /**
         * Store a picked up packet
         * @param {Object} packet - { id, chunks, source, priority, ... }
         */
        async storePacket(packet) {
            await this.init();

            const record = {
                id: packet.id || this._generateId(),
                chunks: packet.chunks,  // Array of QR chunk strings
                source: packet.source || 'Unknown Station',
                priority: packet.priority || Priority.NORMAL,
                size: this._calculateSize(packet.chunks),
                picked_at: new Date().toISOString(),
                delivered: false,
                delivered_at: null
            };

            return new Promise((resolve, reject) => {
                const store = this._getStore('packets', 'readwrite');
                const request = store.put(record);
                request.onsuccess = () => resolve(record);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get all pending (undelivered) packets
         */
        async getPendingPackets() {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('packets');
                const index = store.index('delivered');
                const request = index.getAll(IDBKeyRange.only(false));
                request.onsuccess = () => {
                    // Sort by priority, then by pickup time
                    const packets = request.result.sort((a, b) => {
                        const priorityOrder = { CRITICAL: 0, HIGH: 1, NORMAL: 2 };
                        const pDiff = priorityOrder[a.priority] - priorityOrder[b.priority];
                        if (pDiff !== 0) return pDiff;
                        return new Date(a.picked_at) - new Date(b.picked_at);
                    });
                    resolve(packets);
                };
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get packet by ID
         */
        async getPacket(id) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('packets');
                const request = store.get(id);
                request.onsuccess = () => resolve(request.result || null);
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Mark packet as delivered
         */
        async markDelivered(id) {
            await this.init();

            const packet = await this.getPacket(id);
            if (!packet) throw new Error('Packet not found');

            packet.delivered = true;
            packet.delivered_at = new Date().toISOString();

            // Update packet
            await new Promise((resolve, reject) => {
                const store = this._getStore('packets', 'readwrite');
                const request = store.put(packet);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });

            // Add to history
            await new Promise((resolve, reject) => {
                const store = this._getStore('history', 'readwrite');
                const request = store.add({
                    packet_id: packet.id,
                    source: packet.source,
                    priority: packet.priority,
                    size: packet.size,
                    picked_at: packet.picked_at,
                    delivered_at: packet.delivered_at
                });
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });

            return packet;
        }

        /**
         * Delete a packet
         */
        async deletePacket(id) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('packets', 'readwrite');
                const request = store.delete(id);
                request.onsuccess = () => resolve();
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get delivery history
         */
        async getHistory(limit = 50) {
            await this.init();
            return new Promise((resolve, reject) => {
                const store = this._getStore('history');
                const request = store.getAll();
                request.onsuccess = () => {
                    const sorted = request.result
                        .sort((a, b) => new Date(b.delivered_at) - new Date(a.delivered_at))
                        .slice(0, limit);
                    resolve(sorted);
                };
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Get statistics
         */
        async getStats() {
            await this.init();

            const pending = await this.getPendingPackets();
            const history = await this.getHistory(100);

            const criticalCount = pending.filter(p => p.priority === Priority.CRITICAL).length;
            const highCount = pending.filter(p => p.priority === Priority.HIGH).length;

            return {
                pending: pending.length,
                critical: criticalCount,
                high: highCount,
                delivered_today: history.filter(h => {
                    const today = new Date().toDateString();
                    return new Date(h.delivered_at).toDateString() === today;
                }).length,
                total_delivered: history.length
            };
        }

        /**
         * Check if any critical packets exist
         */
        async hasCriticalPackets() {
            const pending = await this.getPendingPackets();
            return pending.some(p => p.priority === Priority.CRITICAL);
        }

        /**
         * Clear all delivered packets
         */
        async clearDelivered() {
            await this.init();

            const store = this._getStore('packets', 'readwrite');
            const index = store.index('delivered');
            const request = index.openCursor(IDBKeyRange.only(true));

            return new Promise((resolve, reject) => {
                let count = 0;
                request.onsuccess = (event) => {
                    const cursor = event.target.result;
                    if (cursor) {
                        cursor.delete();
                        count++;
                        cursor.continue();
                    } else {
                        resolve(count);
                    }
                };
                request.onerror = () => reject(request.error);
            });
        }

        /**
         * Clear all data
         */
        async clearAll() {
            await this.init();

            for (const storeName of ['packets', 'history']) {
                await new Promise((resolve, reject) => {
                    const store = this._getStore(storeName, 'readwrite');
                    const request = store.clear();
                    request.onsuccess = () => resolve();
                    request.onerror = () => reject(request.error);
                });
            }

            console.log('[RunnerDB] All data cleared');
        }

        // ===== Helpers =====

        _generateId() {
            const ts = Date.now().toString(36);
            const rand = Math.random().toString(36).substring(2, 6);
            return `PKT-${ts}-${rand}`.toUpperCase();
        }

        _calculateSize(chunks) {
            if (!chunks || !Array.isArray(chunks)) return 0;
            return chunks.reduce((sum, c) => sum + (c?.length || 0), 0);
        }
    }

    /**
     * QR Chunk Collector for multi-part packets
     */
    class ChunkCollector {
        constructor() {
            this.reset();
        }

        reset() {
            this._chunks = {};
            this._total = null;
            this._source = null;
        }

        get progress() {
            return {
                received: Object.keys(this._chunks).length,
                total: this._total || 0
            };
        }

        get isComplete() {
            return this._total && Object.keys(this._chunks).length === this._total;
        }

        get missingSequences() {
            if (!this._total) return [];
            const missing = [];
            for (let i = 1; i <= this._total; i++) {
                if (!this._chunks[i]) missing.push(i);
            }
            return missing;
        }

        /**
         * Add a scanned chunk
         * @param {string} chunkStr - Raw QR data
         * @returns {Object|null} Complete packet if done
         */
        addChunk(chunkStr) {
            // Parse xIRS chunk format
            const parts = chunkStr.split('|', 3);
            if (parts.length !== 3 || parts[0] !== 'xIRS') {
                return null;
            }

            const seqParts = parts[1].split('/');
            if (seqParts.length !== 2) return null;

            const sequence = parseInt(seqParts[0], 10);
            const total = parseInt(seqParts[1], 10);

            if (isNaN(sequence) || isNaN(total)) return null;

            // Validate consistency
            if (this._total === null) {
                this._total = total;
            } else if (this._total !== total) {
                // Different packet, reset
                this.reset();
                this._total = total;
            }

            // Store chunk
            this._chunks[sequence] = chunkStr;

            // Check if complete
            if (this.isComplete) {
                const allChunks = [];
                for (let i = 1; i <= this._total; i++) {
                    allChunks.push(this._chunks[i]);
                }
                return {
                    chunks: allChunks,
                    total: this._total
                };
            }

            return null;
        }
    }

    /**
     * Priority detector from packet metadata
     */
    const PriorityDetector = {
        /**
         * Detect priority from chunk content
         * Note: Runner cannot decrypt, but can detect emergency prefix
         */
        detect: function(chunks) {
            if (!chunks || !Array.isArray(chunks)) return Priority.NORMAL;

            // Check first chunk for emergency markers
            const firstChunk = chunks[0] || '';

            // Emergency packets may have special prefix (unencrypted part)
            if (firstChunk.includes('EMERGENCY') || firstChunk.includes('CRITICAL')) {
                return Priority.CRITICAL;
            }
            if (firstChunk.includes('URGENT') || firstChunk.includes('HIGH')) {
                return Priority.HIGH;
            }

            return Priority.NORMAL;
        }
    };

    /**
     * Alert manager for urgent packets
     */
    const AlertManager = {
        _intervalId: null,
        _isAcknowledged: false,

        /**
         * Start alert for critical packet
         */
        startAlert: function() {
            if (this._intervalId) return;

            this._isAcknowledged = false;

            // Vibrate pattern (if supported)
            if ('vibrate' in navigator) {
                this._intervalId = setInterval(() => {
                    if (!this._isAcknowledged) {
                        navigator.vibrate([200, 100, 200, 100, 200]);
                    }
                }, 30000);  // Every 30 seconds

                // Initial vibration
                navigator.vibrate([200, 100, 200, 100, 200]);
            }

            console.log('[AlertManager] Critical alert started');
        },

        /**
         * Acknowledge alert (stops vibration but keeps visual)
         */
        acknowledge: function() {
            this._isAcknowledged = true;
            if ('vibrate' in navigator) {
                navigator.vibrate(0);  // Stop vibration
            }
            console.log('[AlertManager] Alert acknowledged');
        },

        /**
         * Stop alert completely
         */
        stopAlert: function() {
            if (this._intervalId) {
                clearInterval(this._intervalId);
                this._intervalId = null;
            }
            this._isAcknowledged = false;
            if ('vibrate' in navigator) {
                navigator.vibrate(0);
            }
            console.log('[AlertManager] Alert stopped');
        }
    };

    // Export
    global.xIRS = global.xIRS || {};
    global.xIRS.RunnerDB = new RunnerDB();
    global.xIRS.ChunkCollector = ChunkCollector;
    global.xIRS.Priority = Priority;
    global.xIRS.PriorityDetector = PriorityDetector;
    global.xIRS.AlertManager = AlertManager;

    console.log('[xIRS Runner] v1.8.0 loaded');

})(typeof window !== 'undefined' ? window : global);
