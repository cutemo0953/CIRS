/**
 * xIRS Rx Protocol Library v1.0
 *
 * Provides Rx (prescription) handling for Lite CPOE:
 * - RxBuilder: Create and sign Rx orders (Doctor PWA)
 * - RxVerifier: Verify Rx signatures (Pharmacy Station)
 * - Prescriber key management
 *
 * Dependencies: xirs-crypto.js (TweetNaCl)
 */

(function(global) {
    'use strict';

    // Ensure xIRS crypto is available
    const xIRS = global.xIRS;
    if (!xIRS) {
        console.error('[xIRS Rx] xirs-crypto.js not loaded!');
        return;
    }

    const nacl = global.nacl;
    if (!nacl) {
        console.error('[xIRS Rx] TweetNaCl not loaded!');
        return;
    }

    /**
     * Priority levels for Rx orders
     */
    const RxPriority = {
        STAT: 'STAT',       // Immediate / Emergency
        URGENT: 'URGENT',   // Within 1 hour
        ROUTINE: 'ROUTINE'  // Normal queue
    };

    /**
     * Common frequency codes
     */
    const FrequencyCodes = {
        QD: { code: 'QD', label: '每日一次', english: 'Once daily' },
        BID: { code: 'BID', label: '每日兩次', english: 'Twice daily' },
        TID: { code: 'TID', label: '每日三次', english: 'Three times daily' },
        QID: { code: 'QID', label: '每日四次', english: 'Four times daily' },
        Q4H: { code: 'Q4H', label: '每4小時', english: 'Every 4 hours' },
        Q6H: { code: 'Q6H', label: '每6小時', english: 'Every 6 hours' },
        Q8H: { code: 'Q8H', label: '每8小時', english: 'Every 8 hours' },
        PRN: { code: 'PRN', label: '需要時', english: 'As needed' },
        STAT: { code: 'STAT', label: '立即', english: 'Immediately' },
        HS: { code: 'HS', label: '睡前', english: 'At bedtime' },
        AC: { code: 'AC', label: '飯前', english: 'Before meals' },
        PC: { code: 'PC', label: '飯後', english: 'After meals' }
    };

    /**
     * Route codes
     */
    const RouteCodes = {
        PO: { code: 'PO', label: '口服', english: 'By mouth' },
        IV: { code: 'IV', label: '靜脈注射', english: 'Intravenous' },
        IM: { code: 'IM', label: '肌肉注射', english: 'Intramuscular' },
        SC: { code: 'SC', label: '皮下注射', english: 'Subcutaneous' },
        TOP: { code: 'TOP', label: '外用', english: 'Topical' },
        INH: { code: 'INH', label: '吸入', english: 'Inhalation' },
        PR: { code: 'PR', label: '肛門塞劑', english: 'Rectal' },
        SL: { code: 'SL', label: '舌下', english: 'Sublingual' },
        OD: { code: 'OD', label: '右眼', english: 'Right eye' },
        OS: { code: 'OS', label: '左眼', english: 'Left eye' },
        OU: { code: 'OU', label: '雙眼', english: 'Both eyes' }
    };

    /**
     * Prescriber Key Management
     * Handles Ed25519 keypair generation and storage
     */
    const PrescriberKeys = {
        /**
         * Generate a new Ed25519 keypair
         * @returns {Object} { publicKey, privateKey } both Base64 encoded
         */
        generate: function() {
            const keypair = nacl.sign.keyPair();
            return {
                publicKey: xIRS.Base64.encode(keypair.publicKey),
                privateKey: xIRS.Base64.encode(keypair.secretKey)
            };
        },

        /**
         * Derive public key from private key
         * @param {string} privateKeyB64 - Base64-encoded private key
         * @returns {string} Base64-encoded public key
         */
        derivePublicKey: function(privateKeyB64) {
            const privateKey = xIRS.Base64.decode(privateKeyB64);
            // Ed25519 secret key contains public key in last 32 bytes
            const publicKey = privateKey.slice(32);
            return xIRS.Base64.encode(publicKey);
        },

        /**
         * Sign a message with private key
         * @param {string} message - Message to sign
         * @param {string} privateKeyB64 - Base64-encoded private key
         * @returns {string} Base64-encoded signature
         */
        sign: function(message, privateKeyB64) {
            const privateKey = xIRS.Base64.decode(privateKeyB64);
            const messageBytes = new TextEncoder().encode(message);
            const signature = nacl.sign.detached(messageBytes, privateKey);
            return xIRS.Base64.encode(signature);
        },

        /**
         * Verify a signature
         * @param {string} message - Original message
         * @param {string} signatureB64 - Base64-encoded signature
         * @param {string} publicKeyB64 - Base64-encoded public key
         * @returns {boolean}
         */
        verify: function(message, signatureB64, publicKeyB64) {
            return xIRS.Ed25519.verify(message, signatureB64, publicKeyB64);
        }
    };

    /**
     * RxBuilder - Creates and signs Rx orders
     * Used by Doctor PWA
     */
    class RxBuilder {
        /**
         * @param {string} prescriberId - e.g., "DOC-001"
         * @param {string} prescriberName - e.g., "王大明醫師"
         * @param {string} privateKeyB64 - Prescriber's Ed25519 private key
         */
        constructor(prescriberId, prescriberName, privateKeyB64) {
            this.prescriberId = prescriberId;
            this.prescriberName = prescriberName;
            this.privateKey = privateKeyB64;
            this._rxCounter = 0;
        }

        /**
         * Generate unique Rx ID
         * Format: RX-{prescriberId}-{YYYYMMDD}-{sequence}
         */
        _generateRxId() {
            const now = new Date();
            const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
            this._rxCounter++;
            const seq = String(this._rxCounter).padStart(4, '0');
            return `RX-${this.prescriberId}-${dateStr}-${seq}`;
        }

        /**
         * Create and sign an Rx order
         * @param {Object} options
         * @param {Object} options.patient - { id, name, age_group, weight_kg }
         * @param {Array} options.items - Array of medication items
         * @param {string} [options.priority='ROUTINE'] - Priority level
         * @param {string} [options.diagnosis_text] - Diagnosis text
         * @param {string} [options.note] - Additional notes
         * @returns {Object} Signed RX_ORDER
         */
        createRx(options) {
            const rxId = this._generateRxId();
            const ts = xIRS.Utils.timestamp();
            const nonce = xIRS.Utils.randomHex(6);

            // Build order without signature
            const order = {
                type: 'RX_ORDER',
                version: '1.0',
                rx_id: rxId,
                prescriber_id: this.prescriberId,
                prescriber_name: this.prescriberName,
                patient: options.patient,
                items: options.items.map(item => this._normalizeItem(item)),
                priority: options.priority || RxPriority.ROUTINE,
                diagnosis_text: options.diagnosis_text || null,
                note: options.note || null,
                ts: ts,
                nonce: nonce
            };

            // Create canonical message for signing
            const signable = this._createSignable(order);
            const message = JSON.stringify(signable, null, 0);

            // Sign
            order.signature = PrescriberKeys.sign(message, this.privateKey);

            return order;
        }

        /**
         * Normalize a medication item
         */
        _normalizeItem(item) {
            return {
                code: item.code,
                name: item.name,
                qty: item.qty,
                unit: item.unit || 'tab',
                freq: item.freq || 'TID',
                duration_days: item.duration_days || 1,
                route: item.route || 'PO',
                instruction: item.instruction || null,
                is_controlled: item.is_controlled || false,
                schedule: item.schedule || null
            };
        }

        /**
         * Create signable object (deterministic key ordering)
         */
        _createSignable(order) {
            const keys = Object.keys(order).filter(k => k !== 'signature').sort();
            const signable = {};
            for (const key of keys) {
                signable[key] = order[key];
            }
            return signable;
        }

        /**
         * Generate QR codes for an Rx order
         * @param {Object} rxOrder - Signed RX_ORDER
         * @returns {string[]} Array of QR code strings
         */
        toQRCodes(rxOrder) {
            return xIRS.QRChunker.chunk(rxOrder);
        }
    }

    /**
     * RxVerifier - Verifies Rx signatures
     * Used by Pharmacy Station
     */
    class RxVerifier {
        constructor() {
            // Map of prescriber_id -> certificate
            this._certs = new Map();
        }

        /**
         * Load prescriber certificates
         * @param {Array} certs - Array of PRESCRIBER_CERT objects
         */
        loadCertificates(certs) {
            for (const cert of certs) {
                this._certs.set(cert.prescriber_id, cert);
            }
            console.log(`[RxVerifier] Loaded ${certs.length} prescriber certificates`);
        }

        /**
         * Add a single certificate
         * @param {Object} cert - PRESCRIBER_CERT object
         */
        addCertificate(cert) {
            this._certs.set(cert.prescriber_id, cert);
        }

        /**
         * Get certificate by prescriber ID
         * @param {string} prescriberId
         * @returns {Object|null}
         */
        getCertificate(prescriberId) {
            return this._certs.get(prescriberId) || null;
        }

        /**
         * Verify an Rx order signature
         * @param {Object} rxOrder - RX_ORDER to verify
         * @returns {Object} { valid, prescriber, error }
         */
        verify(rxOrder) {
            // Check type
            if (rxOrder.type !== 'RX_ORDER') {
                return { valid: false, error: 'Invalid packet type' };
            }

            // Find prescriber certificate
            const prescriberId = rxOrder.prescriber_id;
            const cert = this._certs.get(prescriberId);

            if (!cert) {
                return { valid: false, error: `Unknown prescriber: ${prescriberId}` };
            }

            // Check certificate validity
            const now = new Date().toISOString().slice(0, 10);
            if (cert.valid_until && cert.valid_until < now) {
                return { valid: false, error: 'Prescriber certificate expired' };
            }
            if (cert.valid_from && cert.valid_from > now) {
                return { valid: false, error: 'Prescriber certificate not yet valid' };
            }

            // Extract signature
            const signature = rxOrder.signature;
            if (!signature) {
                return { valid: false, error: 'Missing signature' };
            }

            // Create signable payload
            const keys = Object.keys(rxOrder).filter(k => k !== 'signature').sort();
            const signable = {};
            for (const key of keys) {
                signable[key] = rxOrder[key];
            }
            const message = JSON.stringify(signable, null, 0);

            // Verify signature
            const isValid = PrescriberKeys.verify(message, signature, cert.public_key);

            if (!isValid) {
                return { valid: false, error: 'Invalid signature' };
            }

            // Check for controlled substances
            const controlledItems = (rxOrder.items || []).filter(item => item.is_controlled);
            const hasControlled = controlledItems.length > 0;

            // Check permissions for controlled substances
            if (hasControlled && cert.permissions) {
                if (!cert.permissions.can_prescribe_controlled) {
                    return {
                        valid: false,
                        error: 'Prescriber not authorized for controlled substances'
                    };
                }
            }

            return {
                valid: true,
                prescriber: {
                    id: cert.prescriber_id,
                    name: cert.name,
                    title: cert.title,
                    license_no: cert.license_no
                },
                has_controlled: hasControlled,
                controlled_items: controlledItems
            };
        }

        /**
         * Verify Hub's signature on a prescriber certificate
         * @param {Object} cert - PRESCRIBER_CERT
         * @param {string} hubPublicKeyB64 - Hub's public key
         * @returns {boolean}
         */
        verifyCertificate(cert, hubPublicKeyB64) {
            const signature = cert.hub_signature;
            if (!signature) return false;

            // Create signable payload
            const keys = Object.keys(cert).filter(k => k !== 'hub_signature').sort();
            const signable = {};
            for (const key of keys) {
                signable[key] = cert[key];
            }
            const message = JSON.stringify(signable, null, 0);

            return PrescriberKeys.verify(message, signature, hubPublicKeyB64);
        }
    }

    /**
     * Rx Parser - Parse Rx from QR codes
     */
    const RxParser = {
        /**
         * Create reassembler for multi-QR Rx
         * @returns {QRReassembler}
         */
        createReassembler: function() {
            return new xIRS.QRReassembler();
        },

        /**
         * Parse single-QR Rx
         * @param {string} qrData - QR code content
         * @returns {Object|null} Parsed RX_ORDER or null
         */
        parseSingle: function(qrData) {
            if (!xIRS.QRChunker.isChunk(qrData)) {
                // Try direct JSON parse
                try {
                    const obj = JSON.parse(qrData);
                    if (obj.type === 'RX_ORDER') return obj;
                } catch (e) {}
                return null;
            }

            const info = xIRS.QRChunker.parseChunk(qrData);
            if (!info || info.total !== 1) return null;

            try {
                const bytes = xIRS.Base64.decode(info.data);
                const text = new TextDecoder().decode(bytes);
                const obj = JSON.parse(text);
                if (obj.type === 'RX_ORDER') return obj;
            } catch (e) {}

            return null;
        },

        /**
         * Check if QR data is an Rx order
         * @param {string} qrData
         * @returns {boolean}
         */
        isRxOrder: function(qrData) {
            if (xIRS.QRChunker.isChunk(qrData)) {
                return true; // Could be Rx chunk
            }
            try {
                const obj = JSON.parse(qrData);
                return obj.type === 'RX_ORDER';
            } catch (e) {
                return false;
            }
        }
    };

    /**
     * Rx ID Generator - for use outside RxBuilder
     */
    const RxIdGenerator = {
        _counters: {},

        /**
         * Generate Rx ID for a prescriber
         * @param {string} prescriberId
         * @returns {string}
         */
        generate: function(prescriberId) {
            const now = new Date();
            const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
            const key = `${prescriberId}-${dateStr}`;

            if (!this._counters[key]) {
                this._counters[key] = 0;
            }
            this._counters[key]++;

            const seq = String(this._counters[key]).padStart(4, '0');
            return `RX-${prescriberId}-${dateStr}-${seq}`;
        },

        /**
         * Parse Rx ID
         * @param {string} rxId
         * @returns {Object|null}
         */
        parse: function(rxId) {
            const match = rxId.match(/^RX-([^-]+)-(\d{8})-(\d{4})$/);
            if (!match) return null;
            return {
                prescriber_id: match[1],
                date: match[2],
                sequence: parseInt(match[3], 10)
            };
        }
    };

    // Export to xIRS namespace
    xIRS.Rx = {
        Priority: RxPriority,
        FrequencyCodes,
        RouteCodes,
        PrescriberKeys,
        RxBuilder,
        RxVerifier,
        RxParser,
        RxIdGenerator,
        VERSION: '1.0.0'
    };

    console.log('[xIRS Rx] v1.0.0 loaded');

})(typeof window !== 'undefined' ? window : global);
