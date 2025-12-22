/**
 * xIRS Crypto Library v1.8 - Browser Compatible
 *
 * Provides cryptographic primitives for Station PWA:
 * - Ed25519 signature verification (manifests from Hub)
 * - NaCl SealedBox encryption (reports to Hub)
 * - HMAC-SHA256 authentication
 * - Base64 encoding/decoding
 *
 * Dependencies: TweetNaCl.js (loaded via CDN)
 */

(function(global) {
    'use strict';

    // Ensure nacl is available
    const nacl = global.nacl;
    if (!nacl) {
        console.error('[xIRS Crypto] TweetNaCl not loaded!');
        return;
    }

    /**
     * Base64 utilities
     */
    const Base64 = {
        encode: function(uint8Array) {
            let binary = '';
            for (let i = 0; i < uint8Array.length; i++) {
                binary += String.fromCharCode(uint8Array[i]);
            }
            return btoa(binary);
        },

        decode: function(base64String) {
            const binary = atob(base64String);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i++) {
                bytes[i] = binary.charCodeAt(i);
            }
            return bytes;
        }
    };

    /**
     * Ed25519 Signature Verification
     * Used to verify manifests signed by Hub
     */
    const Ed25519 = {
        /**
         * Verify a signature
         * @param {string} message - The message that was signed
         * @param {string} signatureB64 - Base64-encoded signature
         * @param {string} publicKeyB64 - Base64-encoded public key
         * @returns {boolean} True if signature is valid
         */
        verify: function(message, signatureB64, publicKeyB64) {
            try {
                const signature = Base64.decode(signatureB64);
                const publicKey = Base64.decode(publicKeyB64);
                const messageBytes = new TextEncoder().encode(message);
                return nacl.sign.detached.verify(messageBytes, signature, publicKey);
            } catch (e) {
                console.error('[Ed25519] Verification error:', e);
                return false;
            }
        },

        /**
         * Verify a manifest object
         * @param {Object} manifest - Manifest with signature field
         * @param {string} publicKeyB64 - Hub's public key
         * @returns {boolean} True if valid
         */
        verifyManifest: function(manifest, publicKeyB64) {
            const signature = manifest.signature;
            if (!signature) return false;

            // Create signable payload (without signature)
            const signable = {};
            for (const key of Object.keys(manifest).sort()) {
                if (key !== 'signature') {
                    signable[key] = manifest[key];
                }
            }
            const message = JSON.stringify(signable);
            return this.verify(message, signature, publicKeyB64);
        }
    };

    /**
     * NaCl SealedBox Encryption
     * Used to encrypt reports for Hub (Blind Carrier pattern)
     */
    const SealedBox = {
        /**
         * Encrypt data for Hub
         * @param {string|Object} plaintext - Data to encrypt
         * @param {string} hubPublicKeyB64 - Hub's encryption public key
         * @returns {string} Base64-encoded ciphertext
         */
        encrypt: function(plaintext, hubPublicKeyB64) {
            try {
                // Serialize if object
                if (typeof plaintext === 'object') {
                    plaintext = JSON.stringify(plaintext);
                }

                const plaintextBytes = new TextEncoder().encode(plaintext);
                const hubPublicKey = Base64.decode(hubPublicKeyB64);

                // Generate ephemeral keypair
                const ephemeralKeypair = nacl.box.keyPair();

                // Compute shared secret
                const nonce = new Uint8Array(24);
                crypto.getRandomValues(nonce);

                // Encrypt using box
                const ciphertext = nacl.box(
                    plaintextBytes,
                    nonce,
                    hubPublicKey,
                    ephemeralKeypair.secretKey
                );

                // Combine: ephemeral_public_key + nonce + ciphertext
                const sealed = new Uint8Array(32 + 24 + ciphertext.length);
                sealed.set(ephemeralKeypair.publicKey, 0);
                sealed.set(nonce, 32);
                sealed.set(ciphertext, 56);

                return Base64.encode(sealed);
            } catch (e) {
                console.error('[SealedBox] Encryption error:', e);
                throw e;
            }
        },

        /**
         * Create encrypted report envelope
         * @param {Object} report - Report object to encrypt
         * @param {string} hubPublicKeyB64 - Hub's encryption public key
         * @returns {Object} Encrypted envelope
         */
        encryptReport: function(report, hubPublicKeyB64) {
            const ciphertext = this.encrypt(report, hubPublicKeyB64);
            return {
                type: 'ENCRYPTED_REPORT',
                version: '1.8',
                payload: ciphertext,
                compressed: false  // Browser version doesn't compress
            };
        }
    };

    /**
     * HMAC-SHA256 Authentication
     * Used to authenticate Station identity
     */
    const HMAC = {
        /**
         * Compute HMAC-SHA256
         * @param {string} secretB64 - Base64-encoded secret
         * @param {string|Object} data - Data to authenticate
         * @returns {Promise<string>} Base64-encoded HMAC
         */
        compute: async function(secretB64, data) {
            // Serialize if object
            if (typeof data === 'object') {
                // Sort keys for consistent ordering
                const sorted = {};
                for (const key of Object.keys(data).sort()) {
                    sorted[key] = data[key];
                }
                data = JSON.stringify(sorted);
            }

            const secret = Base64.decode(secretB64);
            const dataBytes = new TextEncoder().encode(data);

            // Import key
            const key = await crypto.subtle.importKey(
                'raw',
                secret,
                { name: 'HMAC', hash: 'SHA-256' },
                false,
                ['sign']
            );

            // Compute HMAC
            const signature = await crypto.subtle.sign('HMAC', key, dataBytes);
            return Base64.encode(new Uint8Array(signature));
        },

        /**
         * Add HMAC to a report
         * @param {string} secretB64 - Station secret
         * @param {Object} report - Report object (without hmac)
         * @returns {Promise<Object>} Report with hmac field
         */
        addToReport: async function(secretB64, report) {
            const toSign = {};
            for (const key of Object.keys(report)) {
                if (key !== 'hmac') {
                    toSign[key] = report[key];
                }
            }
            const hmac = await this.compute(secretB64, toSign);
            return { ...report, hmac };
        }
    };

    /**
     * QR Chunking for large payloads
     */
    const QRChunker = {
        PROTOCOL_PREFIX: 'xIRS',
        MAX_CHUNK_SIZE: 780,  // Leave room for header

        /**
         * Split payload into QR-friendly chunks
         * @param {string|Object} payload - Data to chunk
         * @returns {string[]} Array of chunk strings
         */
        chunk: function(payload) {
            // Serialize if object
            if (typeof payload === 'object') {
                payload = JSON.stringify(payload);
            }

            // Base64 encode
            const payloadBytes = new TextEncoder().encode(payload);
            const payloadB64 = Base64.encode(payloadBytes);

            // Check if chunking needed
            if (payloadB64.length <= this.MAX_CHUNK_SIZE) {
                return [`${this.PROTOCOL_PREFIX}|1/1|${payloadB64}`];
            }

            // Split into chunks
            const chunks = [];
            const total = Math.ceil(payloadB64.length / this.MAX_CHUNK_SIZE);

            for (let i = 0; i < total; i++) {
                const start = i * this.MAX_CHUNK_SIZE;
                const end = Math.min(start + this.MAX_CHUNK_SIZE, payloadB64.length);
                const chunkData = payloadB64.substring(start, end);
                chunks.push(`${this.PROTOCOL_PREFIX}|${i + 1}/${total}|${chunkData}`);
            }

            return chunks;
        },

        /**
         * Parse a chunk string
         * @param {string} chunkStr - Raw chunk string
         * @returns {Object|null} Parsed chunk info or null if invalid
         */
        parseChunk: function(chunkStr) {
            try {
                const parts = chunkStr.split('|', 3);
                if (parts.length !== 3 || parts[0] !== this.PROTOCOL_PREFIX) {
                    return null;
                }

                const seqParts = parts[1].split('/');
                if (seqParts.length !== 2) return null;

                const sequence = parseInt(seqParts[0], 10);
                const total = parseInt(seqParts[1], 10);

                if (isNaN(sequence) || isNaN(total) || sequence < 1 || sequence > total) {
                    return null;
                }

                return {
                    sequence,
                    total,
                    data: parts[2],
                    raw: chunkStr
                };
            } catch (e) {
                return null;
            }
        },

        /**
         * Check if string is an xIRS chunk
         * @param {string} data - String to check
         * @returns {boolean}
         */
        isChunk: function(data) {
            return data && data.startsWith(this.PROTOCOL_PREFIX + '|');
        }
    };

    /**
     * QR Reassembler for receiving multi-chunk data
     */
    class QRReassembler {
        constructor() {
            this.reset();
        }

        reset() {
            this._chunks = {};
            this._total = null;
            this._complete = false;
        }

        get isComplete() {
            return this._complete;
        }

        get progress() {
            return {
                received: Object.keys(this._chunks).length,
                total: this._total || 0
            };
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
         * Add a chunk
         * @param {string} chunkStr - Raw chunk string
         * @returns {Object|null} Complete payload if done, null otherwise
         */
        addChunk(chunkStr) {
            if (this._complete) return null;

            const info = QRChunker.parseChunk(chunkStr);
            if (!info) return null;

            // Validate consistency
            if (this._total === null) {
                this._total = info.total;
            } else if (this._total !== info.total) {
                return null;  // Different packet
            }

            // Store chunk
            this._chunks[info.sequence] = info.data;

            // Check if complete
            if (Object.keys(this._chunks).length === this._total) {
                this._complete = true;
                return this._reassemble();
            }

            return null;
        }

        _reassemble() {
            const parts = [];
            for (let i = 1; i <= this._total; i++) {
                parts.push(this._chunks[i]);
            }
            const fullB64 = parts.join('');
            const bytes = Base64.decode(fullB64);
            const text = new TextDecoder().decode(bytes);
            try {
                return JSON.parse(text);
            } catch (e) {
                return text;
            }
        }
    }

    /**
     * Utility functions
     */
    const Utils = {
        /**
         * Generate a random hex string
         * @param {number} bytes - Number of bytes
         * @returns {string} Hex string
         */
        randomHex: function(bytes) {
            const array = new Uint8Array(bytes);
            crypto.getRandomValues(array);
            return Array.from(array, b => b.toString(16).padStart(2, '0')).join('');
        },

        /**
         * Generate UUID v4
         * @returns {string} UUID
         */
        uuid: function() {
            return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
                const r = Math.random() * 16 | 0;
                const v = c === 'x' ? r : (r & 0x3 | 0x8);
                return v.toString(16);
            });
        },

        /**
         * Get current Unix timestamp
         * @returns {number}
         */
        timestamp: function() {
            return Math.floor(Date.now() / 1000);
        }
    };

    // Export to global namespace
    global.xIRS = {
        Base64,
        Ed25519,
        SealedBox,
        HMAC,
        QRChunker,
        QRReassembler,
        Utils,
        VERSION: '1.8.0'
    };

    console.log('[xIRS Crypto] v1.8.0 loaded');

})(typeof window !== 'undefined' ? window : global);
