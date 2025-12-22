/**
 * xIRS QR Protocol Library v2.0
 *
 * Implements the XIR1 chunking standard for clinical data QR codes.
 *
 * Features:
 * - Chunking for large payloads (max 800 chars per chunk)
 * - CRC32 checksum for data integrity
 * - DataURL generation for cross-browser rendering
 * - Protocol parsing and validation
 * - Multi-chunk assembly
 *
 * Dependencies: QRCode library (qrcode.min.js)
 */

(function(global) {
    'use strict';

    // Protocol Constants
    const PROTOCOL_PREFIX = 'XIR1';
    const MAX_CHUNK_SIZE = 800;  // Total chunk string length
    const MAX_PAYLOAD_PER_CHUNK = 600;  // Base64 payload per chunk
    const ERROR_CORRECTION = 'L';  // Low for max density
    const QR_WIDTH = 250;

    // Packet Types
    const PACKET_TYPES = {
        RX: 'RX',       // Prescription
        PROC: 'PROC',   // Procedure
        RPT: 'RPT',     // Report
        MF: 'MF',       // Manifest
        REG: 'REG'      // Registration
    };

    // Max chunks per type
    const MAX_CHUNKS = {
        RX: 5,
        PROC: 3,
        RPT: 10,
        MF: 20,
        REG: 2
    };

    /**
     * CRC32 Implementation
     */
    const CRC32 = {
        table: null,

        makeTable() {
            if (this.table) return this.table;
            const table = new Uint32Array(256);
            for (let i = 0; i < 256; i++) {
                let c = i;
                for (let j = 0; j < 8; j++) {
                    c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
                }
                table[i] = c;
            }
            this.table = table;
            return table;
        },

        compute(str) {
            const table = this.makeTable();
            let crc = 0xFFFFFFFF;
            for (let i = 0; i < str.length; i++) {
                crc = table[(crc ^ str.charCodeAt(i)) & 0xFF] ^ (crc >>> 8);
            }
            return ((crc ^ 0xFFFFFFFF) >>> 0).toString(16).padStart(8, '0');
        }
    };

    /**
     * Base64 Utilities (URL-safe)
     */
    const Base64 = {
        encode(str) {
            const bytes = new TextEncoder().encode(str);
            let binary = '';
            for (let i = 0; i < bytes.length; i++) {
                binary += String.fromCharCode(bytes[i]);
            }
            return btoa(binary);
        },

        decode(b64) {
            const binary = atob(b64);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) {
                bytes[i] = binary.charCodeAt(i);
            }
            return new TextDecoder().decode(bytes);
        }
    };

    /**
     * QRProtocol - Main protocol implementation
     */
    const QRProtocol = {
        PROTOCOL_PREFIX,
        PACKET_TYPES,
        MAX_CHUNKS,

        /**
         * Generate nonce for replay protection
         * @returns {string} 24-char hex nonce
         */
        generateNonce() {
            const array = new Uint8Array(12);
            crypto.getRandomValues(array);
            return Array.from(array, b => b.toString(16).padStart(2, '0')).join('');
        },

        /**
         * Generate chunked QR code strings from payload
         * @param {string} type - Packet type (RX, PROC, etc.)
         * @param {Object|string} payload - Data to encode
         * @returns {string[]} Array of XIR1 chunk strings
         */
        generateChunks(type, payload) {
            // Validate type
            if (!PACKET_TYPES[type]) {
                console.warn(`[QRProtocol] Unknown type: ${type}, using RX`);
                type = 'RX';
            }

            // Serialize if object
            const payloadStr = typeof payload === 'object'
                ? JSON.stringify(payload)
                : String(payload);

            // Base64 encode
            const payloadB64 = Base64.encode(payloadStr);

            // Calculate overhead: XIR1|TYPE|XX/XX||CHECKSUM = ~25 chars
            const overhead = `${PROTOCOL_PREFIX}|${type}|99/99||00000000`.length;
            const maxPayloadPerChunk = MAX_CHUNK_SIZE - overhead;

            // Single chunk case
            if (payloadB64.length <= maxPayloadPerChunk) {
                const checksum = CRC32.compute(payloadB64);
                return [`${PROTOCOL_PREFIX}|${type}|1/1|${payloadB64}|${checksum}`];
            }

            // Multi-chunk case
            const chunks = [];
            const total = Math.ceil(payloadB64.length / maxPayloadPerChunk);

            // Check max chunks limit
            const maxAllowed = MAX_CHUNKS[type] || 5;
            if (total > maxAllowed) {
                console.error(`[QRProtocol] Payload too large: ${total} chunks > max ${maxAllowed}`);
                throw new Error(`PAYLOAD_TOO_LARGE: Data requires ${total} QR codes, max is ${maxAllowed}`);
            }

            for (let i = 0; i < total; i++) {
                const start = i * maxPayloadPerChunk;
                const end = Math.min(start + maxPayloadPerChunk, payloadB64.length);
                const chunkPayload = payloadB64.substring(start, end);
                const checksum = CRC32.compute(chunkPayload);
                const seq = i + 1;
                chunks.push(`${PROTOCOL_PREFIX}|${type}|${seq}/${total}|${chunkPayload}|${checksum}`);
            }

            return chunks;
        },

        /**
         * Render a chunk string to DataURL (Base64 image)
         * @param {string} chunkText - XIR1 format string
         * @returns {Promise<string>} Data URL of QR image
         */
        async renderToDataURL(chunkText) {
            return new Promise((resolve, reject) => {
                if (typeof QRCode === 'undefined') {
                    reject(new Error('QRCode library not loaded'));
                    return;
                }

                QRCode.toDataURL(chunkText, {
                    width: QR_WIDTH,
                    margin: 2,
                    errorCorrectionLevel: ERROR_CORRECTION
                }, (err, url) => {
                    if (err) {
                        reject(err);
                    } else {
                        resolve(url);
                    }
                });
            });
        },

        /**
         * Generate chunks and render all to DataURLs
         * @param {string} type - Packet type
         * @param {Object|string} payload - Data to encode
         * @returns {Promise<{chunks: string[], dataURLs: string[]}>}
         */
        async generateAndRender(type, payload) {
            const chunks = this.generateChunks(type, payload);
            const dataURLs = await Promise.all(
                chunks.map(chunk => this.renderToDataURL(chunk))
            );
            return { chunks, dataURLs };
        },

        /**
         * Parse a scanned QR string
         * @param {string} scannedText - Raw scanned text
         * @returns {Object|null} Parsed packet info or null if invalid
         */
        parsePacket(scannedText) {
            if (!scannedText || typeof scannedText !== 'string') {
                return null;
            }

            // Try XIR1 v2.0 format: XIR1|TYPE|SEQ/TOTAL|PAYLOAD|CHECKSUM
            const v2Parts = scannedText.split('|');
            if (v2Parts.length === 5 && v2Parts[0] === PROTOCOL_PREFIX) {
                const [prefix, type, seqTotal, payload, checksum] = v2Parts;
                const [seq, total] = seqTotal.split('/').map(Number);

                // Validate checksum
                const computedChecksum = CRC32.compute(payload);
                if (computedChecksum !== checksum) {
                    console.warn(`[QRProtocol] Checksum mismatch: expected ${checksum}, got ${computedChecksum}`);
                    return {
                        valid: false,
                        error: 'CHECKSUM_MISMATCH',
                        raw: scannedText
                    };
                }

                return {
                    valid: true,
                    version: '2.0',
                    type,
                    sequence: seq,
                    total,
                    payload,
                    checksum,
                    raw: scannedText
                };
            }

            // Try XIR1 v1.x format: XIR1|SEQ/TOTAL|PAYLOAD (backward compat)
            const v1Parts = scannedText.split('|');
            if (v1Parts.length === 3 && v1Parts[0] === PROTOCOL_PREFIX) {
                const [prefix, seqTotal, payload] = v1Parts;
                const [seq, total] = seqTotal.split('/').map(Number);

                return {
                    valid: true,
                    version: '1.x',
                    type: 'RX',  // Default for v1
                    sequence: seq,
                    total,
                    payload,
                    checksum: null,
                    raw: scannedText
                };
            }

            // Try direct JSON (legacy)
            try {
                const obj = JSON.parse(scannedText);
                if (obj && typeof obj === 'object') {
                    return {
                        valid: true,
                        version: 'JSON',
                        type: obj.type || 'UNKNOWN',
                        sequence: 1,
                        total: 1,
                        payload: scannedText,
                        data: obj,
                        raw: scannedText
                    };
                }
            } catch (e) {}

            return {
                valid: false,
                error: 'UNKNOWN_FORMAT',
                raw: scannedText
            };
        },

        /**
         * Validate checksum of a chunk string
         * @param {string} chunkText - XIR1 format string
         * @returns {boolean}
         */
        validateChecksum(chunkText) {
            const parsed = this.parsePacket(chunkText);
            return parsed?.valid === true && parsed?.version === '2.0';
        },

        /**
         * Assemble multiple chunks into original payload
         * @param {Object[]} parsedChunks - Array of parsed chunks (from parsePacket)
         * @returns {Object|null} Decoded payload or null if incomplete/invalid
         */
        assembleChunks(parsedChunks) {
            if (!parsedChunks || parsedChunks.length === 0) {
                return null;
            }

            // Sort by sequence
            const sorted = [...parsedChunks].sort((a, b) => a.sequence - b.sequence);

            // Validate completeness
            const total = sorted[0].total;
            if (sorted.length !== total) {
                return {
                    complete: false,
                    received: sorted.length,
                    expected: total
                };
            }

            // Check all sequences present
            for (let i = 0; i < total; i++) {
                if (sorted[i].sequence !== i + 1) {
                    return {
                        complete: false,
                        missing: i + 1
                    };
                }
            }

            // Concatenate payloads
            const fullB64 = sorted.map(c => c.payload).join('');

            try {
                const decoded = Base64.decode(fullB64);
                const data = JSON.parse(decoded);
                return {
                    complete: true,
                    type: sorted[0].type,
                    data
                };
            } catch (e) {
                console.error('[QRProtocol] Failed to decode assembled payload:', e);
                return {
                    complete: true,
                    error: 'DECODE_ERROR',
                    raw: fullB64
                };
            }
        },

        /**
         * Check if environment supports camera (secure context)
         * @returns {{supported: boolean, reason?: string}}
         */
        checkCameraSupport() {
            if (!window.isSecureContext) {
                return {
                    supported: false,
                    reason: 'NOT_SECURE_CONTEXT',
                    message: '相機需要 HTTPS 連線才能使用'
                };
            }

            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
                return {
                    supported: false,
                    reason: 'NO_MEDIA_DEVICES',
                    message: '此瀏覽器不支援相機功能'
                };
            }

            return { supported: true };
        },

        /**
         * Get human-readable error message for camera errors
         * @param {Error} err - Camera error
         * @returns {string}
         */
        getCameraErrorMessage(err) {
            if (err.name === 'NotAllowedError') {
                return '請在設定中允許相機權限';
            }
            if (err.name === 'NotFoundError') {
                return '找不到相機裝置';
            }
            if (err.name === 'NotReadableError') {
                return '相機正被其他程式使用';
            }
            if (err.name === 'OverconstrainedError') {
                return '找不到符合要求的相機';
            }
            if (!window.isSecureContext) {
                return '相機需要 HTTPS 連線\n請使用手動輸入或上傳圖片';
            }
            return '無法啟動相機: ' + (err.message || '未知錯誤');
        }
    };

    /**
     * ChunkAssembler - Stateful multi-chunk collector
     */
    class ChunkAssembler {
        constructor() {
            this.reset();
        }

        reset() {
            this._chunks = {};
            this._total = null;
            this._type = null;
        }

        /**
         * Add a scanned chunk
         * @param {string} scannedText - Raw scanned text
         * @returns {Object} Status: {complete, data?, progress?}
         */
        addChunk(scannedText) {
            const parsed = QRProtocol.parsePacket(scannedText);

            if (!parsed || !parsed.valid) {
                return { error: parsed?.error || 'INVALID_CHUNK' };
            }

            // First chunk sets expectations
            if (this._total === null) {
                this._total = parsed.total;
                this._type = parsed.type;
            } else {
                // Validate consistency
                if (parsed.total !== this._total) {
                    return { error: 'TOTAL_MISMATCH' };
                }
            }

            // Store chunk
            this._chunks[parsed.sequence] = parsed;

            // Check if complete
            const received = Object.keys(this._chunks).length;
            if (received === this._total) {
                const result = QRProtocol.assembleChunks(Object.values(this._chunks));
                this.reset();
                return result;
            }

            return {
                complete: false,
                progress: `${received}/${this._total}`,
                received,
                total: this._total
            };
        }
    }

    // Export
    global.xIRS = global.xIRS || {};
    global.xIRS.QRProtocol = QRProtocol;
    global.xIRS.ChunkAssembler = ChunkAssembler;
    global.xIRS.CRC32 = CRC32;

    console.log('[xIRS QRProtocol] v2.0.0 loaded');

})(typeof window !== 'undefined' ? window : global);
