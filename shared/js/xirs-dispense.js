/**
 * xIRS Dispense Protocol Library v1.0
 *
 * Provides Dispense record handling for Lite CPOE:
 * - DispenseBuilder: Create dispense records (Pharmacy Station)
 * - DispenseStatus: Status codes and transitions
 * - Controlled substance handling
 *
 * Dependencies: xirs-crypto.js, xirs-rx.js
 */

(function(global) {
    'use strict';

    // Ensure xIRS is available
    const xIRS = global.xIRS;
    if (!xIRS) {
        console.error('[xIRS Dispense] xirs-crypto.js not loaded!');
        return;
    }
    if (!xIRS.Rx) {
        console.error('[xIRS Dispense] xirs-rx.js not loaded!');
        return;
    }

    /**
     * Dispense status codes
     */
    const DispenseStatus = {
        FILLED: 'FILLED',           // Fully dispensed as ordered
        PARTIAL: 'PARTIAL',         // Partial fill (qty_dispensed < qty_ordered)
        SUBSTITUTED: 'SUBSTITUTED', // Different medication substituted
        REJECTED: 'REJECTED',       // Pharmacist rejected
        CANCELLED: 'CANCELLED'      // Prescriber cancelled
    };

    /**
     * Rejection reasons
     */
    const RejectionReasons = {
        OUT_OF_STOCK: { code: 'OUT_OF_STOCK', label: '藥品缺貨' },
        ALLERGY: { code: 'ALLERGY', label: '病患過敏' },
        INTERACTION: { code: 'INTERACTION', label: '藥物交互作用' },
        DUPLICATE: { code: 'DUPLICATE', label: '重複處方' },
        DOSE_TOO_HIGH: { code: 'DOSE_TOO_HIGH', label: '劑量過高' },
        DOSE_TOO_LOW: { code: 'DOSE_TOO_LOW', label: '劑量過低' },
        PATIENT_DECLINED: { code: 'PATIENT_DECLINED', label: '病患拒絕' },
        EXPIRED_RX: { code: 'EXPIRED_RX', label: '處方過期' },
        OTHER: { code: 'OTHER', label: '其他原因' }
    };

    /**
     * Controlled substance schedules
     */
    const ControlledSchedules = {
        I: { level: 1, label: '第一級', requires_witness: true, max_days: 7 },
        II: { level: 2, label: '第二級', requires_witness: true, max_days: 30 },
        III: { level: 3, label: '第三級', requires_witness: true, max_days: 30 },
        IV: { level: 4, label: '第四級', requires_witness: false, max_days: 30 }
    };

    /**
     * DispenseBuilder - Creates dispense records
     * Used by Pharmacy Station
     */
    class DispenseBuilder {
        /**
         * @param {string} stationId - Pharmacy station ID (e.g., "PHARM-01")
         * @param {string} stationSecret - Station's HMAC secret (Base64)
         */
        constructor(stationId, stationSecret) {
            this.stationId = stationId;
            this.stationSecret = stationSecret;
            this._dispenseCounter = 0;
        }

        /**
         * Generate unique Dispense ID
         * Format: DISP-{stationId}-{YYYYMMDD}-{sequence}
         */
        _generateDispenseId() {
            const now = new Date();
            const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
            this._dispenseCounter++;
            const seq = String(this._dispenseCounter).padStart(4, '0');
            return `DISP-${this.stationId}-${dateStr}-${seq}`;
        }

        /**
         * Create a dispense record from an Rx order
         * @param {Object} options
         * @param {Object} options.rxOrder - Original RX_ORDER
         * @param {string} options.pharmacistId - Pharmacist ID
         * @param {string} options.pharmacistName - Pharmacist name
         * @param {string} options.status - DispenseStatus
         * @param {Array} options.dispensedItems - Array of dispensed items
         * @param {Array} [options.substitutions] - Any substitutions made
         * @param {string} [options.witnessId] - Witness ID (for controlled)
         * @param {string} [options.witnessName] - Witness name
         * @param {boolean} [options.counselingProvided] - Patient counseling done
         * @param {string} [options.rejectionReason] - If rejected, the reason
         * @param {string} [options.notes] - Additional notes
         * @returns {Promise<Object>} DISPENSE_RECORD with HMAC
         */
        async createDispenseRecord(options) {
            const dispenseId = this._generateDispenseId();
            const ts = xIRS.Utils.timestamp();
            const nonce = xIRS.Utils.randomHex(6);

            // Build record without HMAC
            const record = {
                type: 'DISPENSE_RECORD',
                version: '1.0',
                dispense_id: dispenseId,
                rx_id: options.rxOrder.rx_id,
                pharmacy_station_id: this.stationId,
                pharmacist_id: options.pharmacistId,
                pharmacist_name: options.pharmacistName,
                patient_id: options.rxOrder.patient?.id || null,
                status: options.status,
                dispensed_items: options.dispensedItems.map(item => this._normalizeDispensedItem(item)),
                substitutions: options.substitutions || [],
                witness_id: options.witnessId || null,
                witness_name: options.witnessName || null,
                counseling_provided: options.counselingProvided || false,
                patient_signature: false,
                rejection_reason: options.status === DispenseStatus.REJECTED ? options.rejectionReason : null,
                notes: options.notes || null,
                ts: ts,
                nonce: nonce
            };

            // Add HMAC
            const authenticatedRecord = await xIRS.HMAC.addToReport(this.stationSecret, record);

            return authenticatedRecord;
        }

        /**
         * Normalize a dispensed item
         */
        _normalizeDispensedItem(item) {
            return {
                code: item.code,
                name: item.name || null,
                qty_ordered: item.qty_ordered,
                qty_dispensed: item.qty_dispensed,
                lot_number: item.lot_number || null,
                expiry_date: item.expiry_date || null,
                is_controlled: item.is_controlled || false,
                schedule: item.schedule || null
            };
        }

        /**
         * Create a quick FILLED dispense record
         * Convenience method when everything is dispensed as ordered
         * @param {Object} rxOrder - Original RX_ORDER
         * @param {string} pharmacistId
         * @param {string} pharmacistName
         * @param {Object} [inventoryInfo] - Lot/expiry info per item code
         * @returns {Promise<Object>} DISPENSE_RECORD
         */
        async createFilledRecord(rxOrder, pharmacistId, pharmacistName, inventoryInfo = {}) {
            const dispensedItems = rxOrder.items.map(item => ({
                code: item.code,
                name: item.name,
                qty_ordered: item.qty,
                qty_dispensed: item.qty,
                lot_number: inventoryInfo[item.code]?.lot_number || null,
                expiry_date: inventoryInfo[item.code]?.expiry_date || null,
                is_controlled: item.is_controlled || false,
                schedule: item.schedule || null
            }));

            return this.createDispenseRecord({
                rxOrder,
                pharmacistId,
                pharmacistName,
                status: DispenseStatus.FILLED,
                dispensedItems,
                counselingProvided: true
            });
        }

        /**
         * Create a REJECTED dispense record
         * @param {Object} rxOrder
         * @param {string} pharmacistId
         * @param {string} pharmacistName
         * @param {string} rejectionReason - RejectionReasons code
         * @param {string} [notes]
         * @returns {Promise<Object>} DISPENSE_RECORD
         */
        async createRejectedRecord(rxOrder, pharmacistId, pharmacistName, rejectionReason, notes) {
            const dispensedItems = rxOrder.items.map(item => ({
                code: item.code,
                name: item.name,
                qty_ordered: item.qty,
                qty_dispensed: 0,
                is_controlled: item.is_controlled || false,
                schedule: item.schedule || null
            }));

            return this.createDispenseRecord({
                rxOrder,
                pharmacistId,
                pharmacistName,
                status: DispenseStatus.REJECTED,
                dispensedItems,
                rejectionReason,
                notes
            });
        }
    }

    /**
     * Controlled Substance Checker
     * Validates controlled substance requirements
     */
    const ControlledChecker = {
        /**
         * Check if Rx contains controlled substances
         * @param {Object} rxOrder
         * @returns {Object} { hasControlled, items, requiresWitness }
         */
        check: function(rxOrder) {
            const controlledItems = (rxOrder.items || []).filter(
                item => item.is_controlled === true
            );

            const requiresWitness = controlledItems.some(item => {
                const schedule = ControlledSchedules[item.schedule];
                return schedule && schedule.requires_witness;
            });

            return {
                hasControlled: controlledItems.length > 0,
                items: controlledItems,
                requiresWitness
            };
        },

        /**
         * Validate witness requirement for dispense record
         * @param {Object} dispenseRecord
         * @returns {Object} { valid, error }
         */
        validateWitness: function(dispenseRecord) {
            const controlledItems = dispenseRecord.dispensed_items.filter(
                item => item.is_controlled && item.qty_dispensed > 0
            );

            if (controlledItems.length === 0) {
                return { valid: true };
            }

            // Check if any items require witness
            const needsWitness = controlledItems.some(item => {
                const schedule = ControlledSchedules[item.schedule];
                return schedule && schedule.requires_witness;
            });

            if (needsWitness) {
                if (!dispenseRecord.witness_id || !dispenseRecord.witness_name) {
                    return {
                        valid: false,
                        error: '管制藥品需要見證人簽核'
                    };
                }
            }

            return { valid: true };
        },

        /**
         * Get schedule info
         * @param {string} schedule - Schedule code (I, II, III, IV)
         * @returns {Object|null}
         */
        getScheduleInfo: function(schedule) {
            return ControlledSchedules[schedule] || null;
        }
    };

    /**
     * Dispense Queue Manager
     * Manages pending Rx orders for dispensing
     */
    class DispenseQueue {
        constructor() {
            this._queue = [];
        }

        /**
         * Add Rx to queue
         * @param {Object} rxOrder - Verified RX_ORDER
         * @param {Object} verification - Verification result from RxVerifier
         */
        add(rxOrder, verification) {
            const entry = {
                id: rxOrder.rx_id,
                rxOrder,
                verification,
                priority: rxOrder.priority || 'ROUTINE',
                receivedAt: new Date().toISOString(),
                status: 'PENDING'
            };

            // Insert by priority
            const priorityOrder = { STAT: 0, URGENT: 1, ROUTINE: 2 };
            const insertPriority = priorityOrder[entry.priority] || 2;

            let inserted = false;
            for (let i = 0; i < this._queue.length; i++) {
                const existingPriority = priorityOrder[this._queue[i].priority] || 2;
                if (insertPriority < existingPriority) {
                    this._queue.splice(i, 0, entry);
                    inserted = true;
                    break;
                }
            }
            if (!inserted) {
                this._queue.push(entry);
            }

            return entry;
        }

        /**
         * Get next pending Rx
         * @returns {Object|null}
         */
        getNext() {
            return this._queue.find(e => e.status === 'PENDING') || null;
        }

        /**
         * Get all pending
         * @returns {Array}
         */
        getAllPending() {
            return this._queue.filter(e => e.status === 'PENDING');
        }

        /**
         * Get by Rx ID
         * @param {string} rxId
         * @returns {Object|null}
         */
        get(rxId) {
            return this._queue.find(e => e.id === rxId) || null;
        }

        /**
         * Mark as in progress
         * @param {string} rxId
         */
        markInProgress(rxId) {
            const entry = this.get(rxId);
            if (entry) entry.status = 'IN_PROGRESS';
        }

        /**
         * Mark as completed
         * @param {string} rxId
         * @param {Object} dispenseRecord
         */
        markCompleted(rxId, dispenseRecord) {
            const entry = this.get(rxId);
            if (entry) {
                entry.status = 'COMPLETED';
                entry.dispenseRecord = dispenseRecord;
                entry.completedAt = new Date().toISOString();
            }
        }

        /**
         * Remove from queue
         * @param {string} rxId
         */
        remove(rxId) {
            const index = this._queue.findIndex(e => e.id === rxId);
            if (index >= 0) {
                this._queue.splice(index, 1);
            }
        }

        /**
         * Get queue stats
         */
        getStats() {
            const stats = {
                total: this._queue.length,
                pending: 0,
                inProgress: 0,
                completed: 0,
                byPriority: { STAT: 0, URGENT: 0, ROUTINE: 0 }
            };

            for (const entry of this._queue) {
                if (entry.status === 'PENDING') stats.pending++;
                else if (entry.status === 'IN_PROGRESS') stats.inProgress++;
                else if (entry.status === 'COMPLETED') stats.completed++;

                if (stats.byPriority[entry.priority] !== undefined) {
                    stats.byPriority[entry.priority]++;
                }
            }

            return stats;
        }

        /**
         * Export queue for persistence
         */
        export() {
            return JSON.parse(JSON.stringify(this._queue));
        }

        /**
         * Import queue from persistence
         */
        import(data) {
            this._queue = data || [];
        }
    }

    /**
     * Duplicate Rx Checker
     * Prevents processing the same Rx twice
     */
    class DuplicateChecker {
        constructor() {
            this._processed = new Map(); // rx_id -> { nonce, status, processedAt }
        }

        /**
         * Check if Rx has been processed
         * @param {string} rxId
         * @param {string} nonce
         * @returns {Object} { isDuplicate, existingStatus, error }
         */
        check(rxId, nonce) {
            const existing = this._processed.get(rxId);

            if (!existing) {
                return { isDuplicate: false };
            }

            if (existing.nonce === nonce) {
                return {
                    isDuplicate: true,
                    existingStatus: existing.status,
                    processedAt: existing.processedAt
                };
            }

            // Same rx_id but different nonce - possible attack
            return {
                isDuplicate: true,
                error: 'NONCE_MISMATCH',
                message: '處方 ID 已存在但 nonce 不符，可能為重放攻擊'
            };
        }

        /**
         * Record a processed Rx
         * @param {string} rxId
         * @param {string} nonce
         * @param {string} status - DispenseStatus
         */
        record(rxId, nonce, status) {
            this._processed.set(rxId, {
                nonce,
                status,
                processedAt: new Date().toISOString()
            });
        }

        /**
         * Export for persistence
         */
        export() {
            const data = {};
            for (const [rxId, info] of this._processed) {
                data[rxId] = info;
            }
            return data;
        }

        /**
         * Import from persistence
         */
        import(data) {
            this._processed.clear();
            if (data) {
                for (const [rxId, info] of Object.entries(data)) {
                    this._processed.set(rxId, info);
                }
            }
        }

        /**
         * Get count
         */
        get count() {
            return this._processed.size;
        }

        /**
         * Clear old entries (optional cleanup)
         * @param {number} maxAgeDays
         */
        cleanup(maxAgeDays = 30) {
            const cutoff = new Date();
            cutoff.setDate(cutoff.getDate() - maxAgeDays);

            for (const [rxId, info] of this._processed) {
                if (new Date(info.processedAt) < cutoff) {
                    this._processed.delete(rxId);
                }
            }
        }
    }

    /**
     * Dispense Report Builder
     * Creates reports to sync back to Hub
     */
    const DispenseReportBuilder = {
        /**
         * Create a report containing dispense records
         * @param {string} stationId
         * @param {Array} dispenseRecords - Array of DISPENSE_RECORD
         * @param {string} stationSecret - HMAC secret
         * @returns {Promise<Object>} Report ready for encryption
         */
        createReport: async function(stationId, dispenseRecords, stationSecret) {
            const report = {
                type: 'DISPENSE_REPORT',
                version: '1.0',
                station_id: stationId,
                generated_at: new Date().toISOString(),
                record_count: dispenseRecords.length,
                records: dispenseRecords,
                ts: xIRS.Utils.timestamp(),
                nonce: xIRS.Utils.randomHex(8)
            };

            // Add HMAC
            return xIRS.HMAC.addToReport(stationSecret, report);
        },

        /**
         * Create encrypted report for Hub
         * @param {Object} report - From createReport
         * @param {string} hubPublicKey - Hub's encryption key
         * @returns {Object} Encrypted envelope
         */
        encrypt: function(report, hubPublicKey) {
            return xIRS.SealedBox.encryptReport(report, hubPublicKey);
        }
    };

    // Export to xIRS namespace
    xIRS.Dispense = {
        Status: DispenseStatus,
        RejectionReasons,
        ControlledSchedules,
        DispenseBuilder,
        ControlledChecker,
        DispenseQueue,
        DuplicateChecker,
        DispenseReportBuilder,
        VERSION: '1.0.0'
    };

    console.log('[xIRS Dispense] v1.0.0 loaded');

})(typeof window !== 'undefined' ? window : global);
