/**
 * xIRS Pairing Library v2.3
 *
 * Handles secure pairing flow for Station/Pharmacy PWAs:
 * - QR Code parsing (STATION_PAIR_INVITE)
 * - Pairing API communication
 * - Config storage and validation
 * - Offline config import
 *
 * Security: QR only contains short-term pairing code, not secrets
 */

(function(global) {
    'use strict';

    const VERSION = '2.3.0';

    /**
     * Pairing QR Code Parser
     */
    const PairingQR = {
        /**
         * Parse pairing QR code
         * @param {string} qrData - Raw QR code content
         * @returns {Object} Parsed pairing invite or error
         */
        parse: function(qrData) {
            try {
                const data = JSON.parse(qrData);

                // Validate type
                if (data.type !== 'STATION_PAIR_INVITE') {
                    return { valid: false, error: '無效的配對 QR Code 類型' };
                }

                // Validate required fields
                const required = ['hub_url', 'pairing_code', 'station_id', 'station_type'];
                for (const field of required) {
                    if (!data[field]) {
                        return { valid: false, error: `缺少必要欄位: ${field}` };
                    }
                }

                // Validate station type
                if (!['SUPPLY', 'PHARMACY'].includes(data.station_type)) {
                    return { valid: false, error: '無效的站點類型' };
                }

                return {
                    valid: true,
                    invite: {
                        hubUrl: data.hub_url,
                        pairingCode: data.pairing_code,
                        stationId: data.station_id,
                        stationType: data.station_type,
                        version: data.ver || 1
                    }
                };
            } catch (e) {
                return { valid: false, error: '無法解析 QR Code' };
            }
        },

        /**
         * Check if QR data is a pairing invite
         */
        isPairingInvite: function(qrData) {
            try {
                const data = JSON.parse(qrData);
                return data.type === 'STATION_PAIR_INVITE';
            } catch (e) {
                return false;
            }
        }
    };

    /**
     * Offline Config Parser
     */
    const OfflineConfig = {
        /**
         * Parse offline config file
         * @param {string} jsonStr - Config file content
         * @param {string} hubPublicKey - Hub's signing public key (if known)
         * @returns {Object} Parsed config or error
         */
        parse: function(jsonStr, hubPublicKey = null) {
            try {
                const data = JSON.parse(jsonStr);

                // Validate type
                if (data.type !== 'STATION_CONFIG_OFFLINE') {
                    return { valid: false, error: '無效的離線設定檔類型' };
                }

                // Check expiration
                const now = Math.floor(Date.now() / 1000);
                if (data.expires_at && data.expires_at < now) {
                    return { valid: false, error: '設定檔已過期' };
                }

                // Verify signature if hub public key is provided
                if (hubPublicKey && data.signature) {
                    const signable = {};
                    for (const key of Object.keys(data).sort()) {
                        if (key !== 'signature') {
                            signable[key] = data[key];
                        }
                    }
                    const message = JSON.stringify(signable);

                    if (global.xIRS && global.xIRS.Ed25519) {
                        const valid = global.xIRS.Ed25519.verify(message, data.signature, hubPublicKey);
                        if (!valid) {
                            return { valid: false, error: '簽章驗證失敗' };
                        }
                    }
                }

                return {
                    valid: true,
                    config: {
                        stationId: data.station_id,
                        stationType: data.station_type,
                        stationSecret: data.config.station_secret,
                        hubPublicKey: data.config.hub_public_key,
                        hubEncryptionKey: data.config.hub_encryption_key,
                        issuedAt: data.issued_at,
                        expiresAt: data.expires_at
                    }
                };
            } catch (e) {
                return { valid: false, error: '無法解析設定檔: ' + e.message };
            }
        }
    };

    /**
     * Pairing API Client
     */
    const PairingAPI = {
        /**
         * Complete pairing with Hub
         * @param {string} hubUrl - Hub base URL
         * @param {string} pairingCode - 6-character pairing code
         * @param {Object} deviceInfo - Device information
         * @returns {Promise<Object>} Config bundle or error
         */
        pair: async function(hubUrl, pairingCode, deviceInfo = {}) {
            try {
                // Normalize URL
                const baseUrl = hubUrl.replace(/\/$/, '');
                const url = `${baseUrl}/api/stations/pair`;

                const response = await fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        pairing_code: pairingCode,
                        device_info: {
                            user_agent: navigator.userAgent,
                            platform: navigator.platform,
                            ...deviceInfo
                        }
                    })
                });

                if (!response.ok) {
                    if (response.status === 401) {
                        return { success: false, error: '配對碼無效或已過期' };
                    }
                    if (response.status === 404) {
                        return { success: false, error: '找不到配對 API' };
                    }
                    return { success: false, error: `伺服器錯誤: ${response.status}` };
                }

                const data = await response.json();

                return {
                    success: true,
                    config: {
                        stationId: data.station_id,
                        stationType: data.station_type,
                        displayName: data.display_name,
                        hubUrl: baseUrl,
                        stationSecret: data.config.station_secret,
                        hubPublicKey: data.config.hub_public_key,
                        hubEncryptionKey: data.config.hub_encryption_key,
                        prescriberCerts: data.prescriber_certs || []
                    }
                };
            } catch (e) {
                if (e.name === 'TypeError' && e.message.includes('fetch')) {
                    return { success: false, error: '無法連線到 Hub (網路錯誤)' };
                }
                return { success: false, error: '配對失敗: ' + e.message };
            }
        }
    };

    /**
     * Station Config Storage
     */
    const StationConfig = {
        STORAGE_KEY: 'xirs_station_config',

        /**
         * Save config to localStorage
         * @param {Object} config - Station configuration
         */
        save: function(config) {
            localStorage.setItem(this.STORAGE_KEY, JSON.stringify({
                ...config,
                savedAt: Date.now()
            }));
        },

        /**
         * Load config from localStorage
         * @returns {Object|null} Saved config or null
         */
        load: function() {
            try {
                const data = localStorage.getItem(this.STORAGE_KEY);
                return data ? JSON.parse(data) : null;
            } catch (e) {
                return null;
            }
        },

        /**
         * Clear saved config
         */
        clear: function() {
            localStorage.removeItem(this.STORAGE_KEY);
        },

        /**
         * Check if station is paired
         * @returns {boolean}
         */
        isPaired: function() {
            const config = this.load();
            return config && config.stationId && config.stationSecret;
        },

        /**
         * Get station type
         * @returns {string|null} 'SUPPLY' or 'PHARMACY' or null
         */
        getType: function() {
            const config = this.load();
            return config ? config.stationType : null;
        }
    };

    /**
     * Pairing Flow Controller
     * Manages the complete pairing process
     */
    class PairingFlow {
        constructor(options = {}) {
            this.onStatusChange = options.onStatusChange || (() => {});
            this.onError = options.onError || (() => {});
            this.onSuccess = options.onSuccess || (() => {});
            this._status = 'idle';
        }

        get status() {
            return this._status;
        }

        _setStatus(status, message = '') {
            this._status = status;
            this.onStatusChange(status, message);
        }

        /**
         * Complete pairing from QR scan
         * @param {string} qrData - Scanned QR content
         */
        async pairFromQR(qrData) {
            this._setStatus('parsing', '解析 QR Code...');

            // Parse QR
            const parsed = PairingQR.parse(qrData);
            if (!parsed.valid) {
                this._setStatus('error', parsed.error);
                this.onError(parsed.error);
                return;
            }

            const { invite } = parsed;
            this._setStatus('connecting', `連線至 ${invite.hubUrl}...`);

            // Call pairing API
            const result = await PairingAPI.pair(invite.hubUrl, invite.pairingCode);

            if (!result.success) {
                this._setStatus('error', result.error);
                this.onError(result.error);
                return;
            }

            // Save config
            StationConfig.save(result.config);
            this._setStatus('success', '配對成功');
            this.onSuccess(result.config);
        }

        /**
         * Complete pairing from manual entry
         * @param {string} hubUrl - Hub URL
         * @param {string} pairingCode - 6-character code
         */
        async pairManually(hubUrl, pairingCode) {
            this._setStatus('connecting', `連線至 ${hubUrl}...`);

            const result = await PairingAPI.pair(hubUrl, pairingCode);

            if (!result.success) {
                this._setStatus('error', result.error);
                this.onError(result.error);
                return;
            }

            StationConfig.save(result.config);
            this._setStatus('success', '配對成功');
            this.onSuccess(result.config);
        }

        /**
         * Import offline config file
         * @param {File} file - JSON config file
         */
        async importOfflineConfig(file) {
            this._setStatus('parsing', '讀取設定檔...');

            try {
                const content = await file.text();
                const result = OfflineConfig.parse(content);

                if (!result.valid) {
                    this._setStatus('error', result.error);
                    this.onError(result.error);
                    return;
                }

                StationConfig.save(result.config);
                this._setStatus('success', '離線設定匯入成功');
                this.onSuccess(result.config);
            } catch (e) {
                this._setStatus('error', '無法讀取檔案');
                this.onError('無法讀取檔案');
            }
        }

        /**
         * Reset flow state
         */
        reset() {
            this._setStatus('idle');
        }
    }

    // Export
    global.xIRS = global.xIRS || {};
    Object.assign(global.xIRS, {
        PairingQR,
        OfflineConfig,
        PairingAPI,
        StationConfig,
        PairingFlow,
        PAIRING_VERSION: VERSION
    });

    console.log(`[xIRS Pairing] v${VERSION} loaded`);

})(typeof window !== 'undefined' ? window : global);
