/**
 * xIRS Protocol Library v1.8 - Browser Compatible
 *
 * Provides packet building for Station PWA:
 * - Manifest parsing and verification
 * - Report building with encryption and HMAC
 * - Action logging
 *
 * Dependencies: xirs-crypto.js
 */

(function(global) {
    'use strict';

    const xIRS = global.xIRS;
    if (!xIRS) {
        console.error('[xIRS Protocol] xIRS Crypto not loaded!');
        return;
    }

    /**
     * Manifest Parser - handles RESTOCK_MANIFEST from Hub
     */
    const ManifestParser = {
        /**
         * Parse and verify a manifest
         * @param {Object} manifest - Manifest object
         * @param {string} hubPublicKeyB64 - Hub's signing public key
         * @returns {Object} { valid: boolean, manifest: Object, error?: string }
         */
        parse: function(manifest, hubPublicKeyB64) {
            // Check required fields
            if (!manifest || manifest.type !== 'RESTOCK_MANIFEST') {
                return { valid: false, error: 'Invalid manifest type' };
            }

            if (!manifest.manifest_id || !manifest.station_id || !manifest.items) {
                return { valid: false, error: 'Missing required fields' };
            }

            // Verify signature
            const signatureValid = xIRS.Ed25519.verifyManifest(manifest, hubPublicKeyB64);
            if (!signatureValid) {
                return { valid: false, error: 'Invalid signature' };
            }

            return {
                valid: true,
                manifest: {
                    manifest_id: manifest.manifest_id,
                    short_code: manifest.short_code,
                    station_id: manifest.station_id,
                    items: manifest.items,
                    ts: manifest.ts,
                    version: manifest.version
                }
            };
        },

        /**
         * Parse manifest from QR chunk(s)
         * @param {string|string[]} chunks - Single chunk or array of chunks
         * @param {string} hubPublicKeyB64 - Hub's signing public key
         * @returns {Object} Parsing result
         */
        parseFromQR: function(chunks, hubPublicKeyB64) {
            try {
                let manifest;

                if (Array.isArray(chunks)) {
                    // Multi-chunk - reassemble
                    const reassembler = new xIRS.QRReassembler();
                    for (const chunk of chunks) {
                        const result = reassembler.addChunk(chunk);
                        if (result) {
                            manifest = result;
                            break;
                        }
                    }
                    if (!manifest) {
                        return {
                            valid: false,
                            error: `Incomplete: ${reassembler.progress.received}/${reassembler.progress.total}`,
                            missing: reassembler.missingSequences
                        };
                    }
                } else {
                    // Single chunk
                    const info = xIRS.QRChunker.parseChunk(chunks);
                    if (!info) {
                        return { valid: false, error: 'Invalid QR format' };
                    }
                    const bytes = xIRS.Base64.decode(info.data);
                    const text = new TextDecoder().decode(bytes);
                    manifest = JSON.parse(text);
                }

                return this.parse(manifest, hubPublicKeyB64);
            } catch (e) {
                return { valid: false, error: e.message };
            }
        }
    };

    /**
     * Report Builder - creates REPORT_PACKET for Hub
     */
    class ReportBuilder {
        /**
         * @param {string} stationId - This station's ID
         * @param {string} stationSecretB64 - HMAC secret
         * @param {string} hubEncryptionKeyB64 - Hub's encryption public key
         */
        constructor(stationId, stationSecretB64, hubEncryptionKeyB64) {
            this.stationId = stationId;
            this.stationSecret = stationSecretB64;
            this.hubEncryptionKey = hubEncryptionKeyB64;
            this.seqCounter = 0;
        }

        /**
         * Create a report packet
         * @param {Array} actions - Array of action objects
         * @param {string} manifestId - Related manifest ID (optional)
         * @returns {Promise<Object>} Report object with HMAC
         */
        async createReport(actions, manifestId = '') {
            this.seqCounter++;

            const packetId = this._generatePacketId();
            const nonce = xIRS.Utils.randomHex(8);
            const ts = xIRS.Utils.timestamp();

            const report = {
                type: 'REPORT_PACKET',
                version: '1.8',
                packet_id: packetId,
                station_id: this.stationId,
                manifest_id: manifestId,
                seq_id: this.seqCounter,
                actions: actions,
                ts: ts,
                nonce: nonce
            };

            // Add HMAC
            const authenticated = await xIRS.HMAC.addToReport(this.stationSecret, report);
            return authenticated;
        }

        /**
         * Encrypt a report for transport
         * @param {Object} report - Authenticated report
         * @returns {Object} Encrypted envelope
         */
        encryptReport(report) {
            return xIRS.SealedBox.encryptReport(report, this.hubEncryptionKey);
        }

        /**
         * Create encrypted QR chunks for a report
         * @param {Object} report - Authenticated report
         * @returns {string[]} Array of QR chunk strings
         */
        toEncryptedChunks(report) {
            const encrypted = this.encryptReport(report);
            return xIRS.QRChunker.chunk(encrypted);
        }

        /**
         * Create manifest acknowledgement report
         * @param {string} manifestId - Manifest being acknowledged
         * @param {Array} itemsReceived - Items actually received
         * @returns {Promise<Object>} ACK report
         */
        async createManifestAck(manifestId, itemsReceived) {
            const actions = itemsReceived.map(item => ({
                type: 'RECEIVE',
                item_code: item.code,
                qty: item.qty,
                unit: item.unit || 'unit',
                manifest_id: manifestId,
                ts: xIRS.Utils.timestamp()
            }));

            return this.createReport(actions, manifestId);
        }

        _generatePacketId() {
            const date = new Date();
            const dateStr = date.toISOString().slice(0, 10).replace(/-/g, '');
            const timeStr = date.toISOString().slice(11, 19).replace(/:/g, '');
            const rand = xIRS.Utils.randomHex(2).toUpperCase();
            return `RPT-${this.stationId}-${dateStr}${timeStr}-${rand}`;
        }
    }

    /**
     * Action Types
     */
    const ActionTypes = {
        DISPENSE: 'DISPENSE',
        RECEIVE: 'RECEIVE',
        REGISTER: 'REGISTER',
        STOCKTAKE: 'STOCKTAKE'
    };

    /**
     * Action Builder Helpers
     */
    const ActionBuilder = {
        /**
         * Create DISPENSE action
         * @param {string} itemCode - Item being dispensed
         * @param {number} qty - Quantity
         * @param {string} unit - Unit of measure
         * @param {string} personId - Recipient ID (optional)
         * @returns {Object} Action object
         */
        dispense: function(itemCode, qty, unit = 'unit', personId = '') {
            return {
                type: ActionTypes.DISPENSE,
                item_code: itemCode,
                qty: qty,
                unit: unit,
                person_id: personId,
                ts: xIRS.Utils.timestamp()
            };
        },

        /**
         * Create RECEIVE action
         * @param {string} itemCode - Item received
         * @param {number} qty - Quantity
         * @param {string} unit - Unit of measure
         * @param {string} manifestId - Source manifest (optional)
         * @returns {Object} Action object
         */
        receive: function(itemCode, qty, unit = 'unit', manifestId = '') {
            const action = {
                type: ActionTypes.RECEIVE,
                item_code: itemCode,
                qty: qty,
                unit: unit,
                ts: xIRS.Utils.timestamp()
            };
            if (manifestId) action.manifest_id = manifestId;
            return action;
        },

        /**
         * Create REGISTER action
         * @param {string} personId - Person ID
         * @param {Object} metadata - Additional info (optional)
         * @returns {Object} Action object
         */
        register: function(personId, metadata = null) {
            const action = {
                type: ActionTypes.REGISTER,
                person_id: personId,
                ts: xIRS.Utils.timestamp()
            };
            if (metadata) action.metadata = metadata;
            return action;
        },

        /**
         * Create STOCKTAKE action
         * @param {string} itemCode - Item code
         * @param {number} actualQty - Actual count
         * @param {number} expectedQty - Expected count
         * @returns {Object} Action object
         */
        stocktake: function(itemCode, actualQty, expectedQty) {
            return {
                type: ActionTypes.STOCKTAKE,
                item_code: itemCode,
                actual_qty: actualQty,
                expected_qty: expectedQty,
                variance: actualQty - expectedQty,
                ts: xIRS.Utils.timestamp()
            };
        }
    };

    /**
     * Station Configuration
     */
    class StationConfig {
        constructor() {
            this._storageKey = 'xirs_station_config';
        }

        /**
         * Save station configuration
         * @param {Object} config - { stationId, stationSecret, hubPublicKey, hubEncryptionKey }
         */
        save(config) {
            localStorage.setItem(this._storageKey, JSON.stringify(config));
        }

        /**
         * Load station configuration
         * @returns {Object|null} Configuration or null if not set
         */
        load() {
            const data = localStorage.getItem(this._storageKey);
            return data ? JSON.parse(data) : null;
        }

        /**
         * Clear configuration
         */
        clear() {
            localStorage.removeItem(this._storageKey);
        }

        /**
         * Check if configured
         * @returns {boolean}
         */
        isConfigured() {
            const config = this.load();
            return config && config.stationId && config.stationSecret;
        }
    }

    // Extend xIRS namespace
    xIRS.ManifestParser = ManifestParser;
    xIRS.ReportBuilder = ReportBuilder;
    xIRS.ActionTypes = ActionTypes;
    xIRS.ActionBuilder = ActionBuilder;
    xIRS.StationConfig = new StationConfig();

    console.log('[xIRS Protocol] v1.8.0 loaded');

})(typeof window !== 'undefined' ? window : global);
