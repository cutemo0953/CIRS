/**
 * xIRS Protocol Library v2.0 - Browser Compatible
 *
 * Provides packet parsing and building for Station/Pharmacy PWA:
 * - Manifest parsing and verification (RESTOCK_MANIFEST)
 * - Prescription parsing and verification (RX_ORDER)
 * - Consumption ticket parsing (CONSUMPTION_TICKET)
 * - Report building with encryption and HMAC
 * - Action logging
 *
 * Dependencies: xirs-crypto.js
 *
 * v2.0 Changes:
 * - Added RxOrderParser for prescription handling
 * - Added ConsumptionTicketParser for procedure-inventory bridge
 * - Added CertUpdateParser for prescriber certificates
 * - Added clinical action types
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
     * RX_ORDER Parser - handles prescriptions from Doctor PWA
     */
    const RxOrderParser = {
        /**
         * Parse and verify an Rx order
         * @param {Object} rxOrder - Rx order object
         * @param {Object} prescriberCerts - Map of prescriber_id -> certificate
         * @returns {Object} { valid: boolean, rx: Object, prescriber?: Object, error?: string }
         */
        parse: function(rxOrder, prescriberCerts) {
            // Check type
            if (!rxOrder || rxOrder.type !== 'RX_ORDER') {
                return { valid: false, error: 'Invalid Rx type' };
            }

            // Check required fields
            const required = ['rx_id', 'prescriber_id', 'patient_ref', 'items', 'signature'];
            for (const field of required) {
                if (!rxOrder[field]) {
                    return { valid: false, error: `Missing required field: ${field}` };
                }
            }

            // Find prescriber certificate
            const prescriberId = rxOrder.prescriber_id;
            const cert = prescriberCerts[prescriberId] || prescriberCerts.get?.(prescriberId);

            if (!cert) {
                return { valid: false, error: `Unknown prescriber: ${prescriberId}` };
            }

            // Check certificate validity
            const now = Math.floor(Date.now() / 1000);
            if (cert.revoked) {
                return { valid: false, error: 'Prescriber certificate revoked' };
            }
            if (cert.expires_at && cert.expires_at < now) {
                return { valid: false, error: 'Prescriber certificate expired' };
            }

            // Verify signature
            const signatureValid = xIRS.Ed25519.verifyManifest(rxOrder, cert.public_key);
            if (!signatureValid) {
                return { valid: false, error: 'Invalid signature' };
            }

            return {
                valid: true,
                rx: {
                    rx_id: rxOrder.rx_id,
                    prescriber_id: rxOrder.prescriber_id,
                    patient_ref: rxOrder.patient_ref,
                    items: rxOrder.items,
                    priority: rxOrder.priority || 'ROUTINE',
                    diagnosis_text: rxOrder.diagnosis_text,
                    note: rxOrder.note,
                    ts: rxOrder.ts,
                    nonce: rxOrder.nonce
                },
                prescriber: {
                    id: cert.id,
                    name: cert.name
                }
            };
        },

        /**
         * Parse Rx from QR chunk(s)
         * @param {string|string[]} chunks - Single chunk or array of chunks
         * @param {Object} prescriberCerts - Map of prescriber certificates
         * @returns {Object} Parsing result
         */
        parseFromQR: function(chunks, prescriberCerts) {
            try {
                let rxOrder;

                if (Array.isArray(chunks)) {
                    const reassembler = new xIRS.QRReassembler();
                    for (const chunk of chunks) {
                        const result = reassembler.addChunk(chunk);
                        if (result) {
                            rxOrder = result;
                            break;
                        }
                    }
                    if (!rxOrder) {
                        return {
                            valid: false,
                            error: `Incomplete: ${reassembler.progress.received}/${reassembler.progress.total}`,
                            missing: reassembler.missingSequences
                        };
                    }
                } else {
                    const info = xIRS.QRChunker.parseChunk(chunks);
                    if (!info) {
                        return { valid: false, error: 'Invalid QR format' };
                    }
                    const bytes = xIRS.Base64.decode(info.data);
                    const text = new TextDecoder().decode(bytes);
                    rxOrder = JSON.parse(text);
                }

                return this.parse(rxOrder, prescriberCerts);
            } catch (e) {
                return { valid: false, error: e.message };
            }
        },

        /**
         * Check for duplicate/replay
         * @param {Object} rx - Parsed Rx
         * @param {Object} existingRx - Existing processed Rx (from DB)
         * @returns {Object} { duplicate: boolean, error?: string }
         */
        checkDuplicate: function(rx, existingRx) {
            if (!existingRx) {
                return { duplicate: false };
            }

            if (existingRx.nonce === rx.nonce) {
                return {
                    duplicate: true,
                    status: existingRx.status,
                    message: 'Rx already processed'
                };
            }

            // Same rx_id but different nonce - possible replay
            return {
                duplicate: true,
                error: 'NONCE_MISMATCH',
                message: 'Possible replay attack detected'
            };
        }
    };

    /**
     * CONSUMPTION_TICKET Parser - for procedure-inventory bridge
     */
    const ConsumptionTicketParser = {
        /**
         * Parse and verify a consumption ticket
         * @param {Object} ticket - Consumption ticket object
         * @param {string} stationSecretB64 - Station secret for HMAC verification
         * @returns {Promise<Object>} { valid: boolean, ticket: Object, error?: string }
         */
        parse: async function(ticket, stationSecretB64) {
            // Check type
            if (!ticket || ticket.type !== 'CONSUMPTION_TICKET') {
                return { valid: false, error: 'Invalid ticket type' };
            }

            // Check required fields
            const required = ['ticket_id', 'event_ref', 'items', 'hmac'];
            for (const field of required) {
                if (!ticket[field]) {
                    return { valid: false, error: `Missing required field: ${field}` };
                }
            }

            // Verify HMAC
            const hmacValid = await xIRS.HMAC.verify(stationSecretB64, ticket);
            if (!hmacValid) {
                return { valid: false, error: 'Invalid HMAC' };
            }

            return {
                valid: true,
                ticket: {
                    ticket_id: ticket.ticket_id,
                    event_ref: ticket.event_ref,
                    source: ticket.source,
                    source_station: ticket.source_station,
                    items: ticket.items,
                    executor_id: ticket.executor_id,
                    ts: ticket.ts
                }
            };
        },

        /**
         * Parse ticket from QR
         * @param {string} qrData - QR chunk string
         * @param {string} stationSecretB64 - Station secret
         * @returns {Promise<Object>} Parsing result
         */
        parseFromQR: async function(qrData, stationSecretB64) {
            try {
                const info = xIRS.QRChunker.parseChunk(qrData);
                if (!info) {
                    return { valid: false, error: 'Invalid QR format' };
                }

                const bytes = xIRS.Base64.decode(info.data);
                const text = new TextDecoder().decode(bytes);
                const ticket = JSON.parse(text);

                return this.parse(ticket, stationSecretB64);
            } catch (e) {
                return { valid: false, error: e.message };
            }
        }
    };

    /**
     * CERT_UPDATE Parser - for prescriber certificate updates
     */
    const CertUpdateParser = {
        /**
         * Parse and verify a certificate update packet
         * @param {Object} certUpdate - Certificate update object
         * @param {string} hubPublicKeyB64 - Hub's signing public key
         * @returns {Object} { valid: boolean, certs: Array, error?: string }
         */
        parse: function(certUpdate, hubPublicKeyB64) {
            // Check type
            if (!certUpdate || certUpdate.type !== 'CERT_UPDATE') {
                return { valid: false, error: 'Invalid packet type' };
            }

            // Check required fields
            if (!certUpdate.certs || !Array.isArray(certUpdate.certs)) {
                return { valid: false, error: 'Missing certs array' };
            }

            // Verify signature
            const signatureValid = xIRS.Ed25519.verifyManifest(certUpdate, hubPublicKeyB64);
            if (!signatureValid) {
                return { valid: false, error: 'Invalid signature' };
            }

            return {
                valid: true,
                certs: certUpdate.certs,
                issued_at: certUpdate.issued_at
            };
        },

        /**
         * Parse from QR
         */
        parseFromQR: function(chunks, hubPublicKeyB64) {
            try {
                let certUpdate;

                if (Array.isArray(chunks)) {
                    const reassembler = new xIRS.QRReassembler();
                    for (const chunk of chunks) {
                        const result = reassembler.addChunk(chunk);
                        if (result) {
                            certUpdate = result;
                            break;
                        }
                    }
                    if (!certUpdate) {
                        return { valid: false, error: 'Incomplete scan' };
                    }
                } else {
                    const info = xIRS.QRChunker.parseChunk(chunks);
                    if (!info) {
                        return { valid: false, error: 'Invalid QR format' };
                    }
                    const bytes = xIRS.Base64.decode(info.data);
                    const text = new TextDecoder().decode(bytes);
                    certUpdate = JSON.parse(text);
                }

                return this.parse(certUpdate, hubPublicKeyB64);
            } catch (e) {
                return { valid: false, error: e.message };
            }
        }
    };

    /**
     * Universal QR Parser - auto-detects packet type
     */
    const PacketParser = {
        /**
         * Detect packet type from QR data
         * @param {string} qrData - QR chunk string
         * @returns {string|null} Packet type or null
         */
        detectType: function(qrData) {
            try {
                if (!xIRS.QRChunker.isChunk(qrData)) {
                    return null;
                }

                const info = xIRS.QRChunker.parseChunk(qrData);
                if (!info) return null;

                // For single-chunk packets, we can detect immediately
                if (info.total === 1) {
                    const bytes = xIRS.Base64.decode(info.data);
                    const text = new TextDecoder().decode(bytes);
                    const packet = JSON.parse(text);
                    return packet.type || null;
                }

                // For multi-chunk, we need to reassemble first
                return 'MULTI_CHUNK';
            } catch (e) {
                return null;
            }
        },

        /**
         * Parse any packet type
         * @param {string|string[]} chunks - QR chunk(s)
         * @param {Object} options - { hubPublicKey, prescriberCerts, stationSecret }
         * @returns {Promise<Object>} Parsing result with type field
         */
        parse: async function(chunks, options = {}) {
            try {
                let packet;

                // Reassemble if needed
                if (Array.isArray(chunks)) {
                    const reassembler = new xIRS.QRReassembler();
                    for (const chunk of chunks) {
                        const result = reassembler.addChunk(chunk);
                        if (result) {
                            packet = result;
                            break;
                        }
                    }
                    if (!packet) {
                        return {
                            valid: false,
                            error: 'Incomplete scan',
                            progress: reassembler.progress
                        };
                    }
                } else {
                    const info = xIRS.QRChunker.parseChunk(chunks);
                    if (!info) {
                        return { valid: false, error: 'Invalid QR format' };
                    }
                    const bytes = xIRS.Base64.decode(info.data);
                    const text = new TextDecoder().decode(bytes);
                    packet = JSON.parse(text);
                }

                // Route to appropriate parser
                const type = packet.type;
                switch (type) {
                    case 'RESTOCK_MANIFEST':
                        return {
                            ...ManifestParser.parse(packet, options.hubPublicKey),
                            packetType: 'RESTOCK_MANIFEST'
                        };

                    case 'RX_ORDER':
                        return {
                            ...RxOrderParser.parse(packet, options.prescriberCerts || {}),
                            packetType: 'RX_ORDER'
                        };

                    case 'CONSUMPTION_TICKET':
                        return {
                            ...(await ConsumptionTicketParser.parse(packet, options.stationSecret)),
                            packetType: 'CONSUMPTION_TICKET'
                        };

                    case 'CERT_UPDATE':
                        return {
                            ...CertUpdateParser.parse(packet, options.hubPublicKey),
                            packetType: 'CERT_UPDATE'
                        };

                    default:
                        return {
                            valid: false,
                            error: `Unknown packet type: ${type}`,
                            raw: packet
                        };
                }
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
     * Action Types (Extended for v2.0)
     */
    const ActionTypes = {
        // Logistics actions
        DISPENSE: 'DISPENSE',
        RECEIVE: 'RECEIVE',
        REGISTER: 'REGISTER',
        STOCKTAKE: 'STOCKTAKE',

        // Clinical actions (Pharmacy)
        RX_RECEIVE: 'RX_RECEIVE',       // Received Rx from doctor
        RX_DISPENSE: 'RX_DISPENSE',     // Dispensed Rx to patient
        RX_REJECT: 'RX_REJECT',         // Rejected Rx

        // Consumption actions (Procedure-Inventory Bridge)
        CONSUMPTION: 'CONSUMPTION',      // Deducted from consumption ticket
        CONSUMPTION_RETURN: 'CONSUMPTION_RETURN'  // Returned unused items
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
    xIRS.RxOrderParser = RxOrderParser;
    xIRS.ConsumptionTicketParser = ConsumptionTicketParser;
    xIRS.CertUpdateParser = CertUpdateParser;
    xIRS.PacketParser = PacketParser;
    xIRS.ReportBuilder = ReportBuilder;
    xIRS.ActionTypes = ActionTypes;
    xIRS.ActionBuilder = ActionBuilder;
    xIRS.StationConfig = new StationConfig();

    console.log('[xIRS Protocol] v2.0.0 loaded');

})(typeof window !== 'undefined' ? window : global);
