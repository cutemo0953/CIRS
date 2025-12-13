/**
 * IRS 跨系統互通 Schema 驗證模組
 * 版本: 1.0.0
 *
 * 用於 HIRS (PWA) / CIRS Frontend / CoreIRS Frontend
 */

// ============================================================================
// 常數定義
// ============================================================================

const IRS_SCHEMA_VERSION = '1.0';

const MESSAGE_TYPES = {
  DISTRIBUTION: 'DISTRIBUTION',
  DONATION_RECEIPT: 'DONATION_RECEIPT',
  TEMPLATE: 'TEMPLATE',
  INVENTORY_SYNC: 'INVENTORY_SYNC'
};

const SYSTEMS = {
  HIRS: 'HIRS',
  CIRS: 'CIRS',
  MIRS: 'MIRS',
  COREIRS: 'CoreIRS'
};

const CATEGORIES = {
  water: { name_zh: '飲用水', icon: 'droplet', color: '#3b82f6' },
  food: { name_zh: '食物', icon: 'utensils', color: '#f59e0b' },
  medical: { name_zh: '醫療', icon: 'first-aid', color: '#ef4444' },
  hygiene: { name_zh: '衛生', icon: 'soap', color: '#8b5cf6' },
  tools: { name_zh: '工具', icon: 'wrench', color: '#6b7280' },
  documents: { name_zh: '證件', icon: 'id-card', color: '#0ea5e9' },
  clothing: { name_zh: '衣物', icon: 'shirt', color: '#14b8a6' },
  power: { name_zh: '電力', icon: 'battery', color: '#eab308' },
  communication: { name_zh: '通訊', icon: 'radio', color: '#06b6d4' },
  shelter: { name_zh: '避難', icon: 'tent', color: '#84cc16' },
  baby: { name_zh: '嬰幼兒', icon: 'baby', color: '#ec4899' },
  elderly: { name_zh: '長者', icon: 'wheelchair', color: '#a855f7' },
  pet: { name_zh: '寵物', icon: 'paw', color: '#f97316' },
  other: { name_zh: '其他', icon: 'box', color: '#9ca3af' }
};

const PURCHASE_URL_ALLOWLIST = [
  'shopee.tw',
  'momoshop.com.tw',
  'pcone.com.tw',
  'pchome.com.tw',
  'amazon.com',
  'books.com.tw',
  'costco.com.tw',
  'carrefour.com.tw'
];

// ============================================================================
// 錯誤類型
// ============================================================================

const ERROR_CODES = {
  ERR_INVALID_SCHEMA: 'ERR_INVALID_SCHEMA',
  ERR_MISSING_FIELD: 'ERR_MISSING_FIELD',
  ERR_INVALID_TYPE: 'ERR_INVALID_TYPE',
  ERR_SIGNATURE_INVALID: 'ERR_SIGNATURE_INVALID',
  ERR_DUPLICATE: 'ERR_DUPLICATE',
  ERR_QR_PARSE: 'ERR_QR_PARSE'
};

class IRSValidationError extends Error {
  constructor(code, message, field = null) {
    super(message);
    this.name = 'IRSValidationError';
    this.code = code;
    this.field = field;
  }
}

// ============================================================================
// 驗證函式
// ============================================================================

/**
 * 驗證完整的 IRS 信封格式
 * @param {object} envelope - 待驗證的信封物件
 * @returns {{ valid: boolean, errors: string[], envelope: object }}
 */
function validateEnvelope(envelope) {
  const errors = [];

  // 檢查是否為物件
  if (!envelope || typeof envelope !== 'object') {
    return { valid: false, errors: ['Invalid envelope: not an object'], envelope: null };
  }

  // 必填欄位
  const requiredFields = ['schema_version', 'message_type', 'issuer', 'timestamp', 'message_id', 'payload'];
  for (const field of requiredFields) {
    if (!envelope[field]) {
      errors.push(`Missing required field: ${field}`);
    }
  }

  // schema_version
  if (envelope.schema_version && envelope.schema_version !== IRS_SCHEMA_VERSION) {
    errors.push(`Unsupported schema_version: ${envelope.schema_version}`);
  }

  // message_type
  if (envelope.message_type && !Object.values(MESSAGE_TYPES).includes(envelope.message_type)) {
    errors.push(`Invalid message_type: ${envelope.message_type}`);
  }

  // issuer
  if (envelope.issuer) {
    if (!envelope.issuer.system) {
      errors.push('Missing required field: issuer.system');
    }
    if (!envelope.issuer.site_id) {
      errors.push('Missing required field: issuer.site_id');
    }
  }

  // timestamp (ISO 8601)
  if (envelope.timestamp) {
    const date = new Date(envelope.timestamp);
    if (isNaN(date.getTime())) {
      errors.push('Invalid timestamp format');
    }
  }

  // message_id (UUID v4 格式，但不嚴格驗證)
  if (envelope.message_id && typeof envelope.message_id !== 'string') {
    errors.push('Invalid message_id format');
  }

  return {
    valid: errors.length === 0,
    errors,
    envelope: errors.length === 0 ? envelope : null
  };
}

/**
 * 驗證 DISTRIBUTION payload
 * @param {object} payload
 * @returns {{ valid: boolean, errors: string[] }}
 */
function validateDistributionPayload(payload) {
  const errors = [];

  if (!payload.items || !Array.isArray(payload.items)) {
    errors.push('Missing or invalid items array');
    return { valid: false, errors };
  }

  if (payload.items.length === 0) {
    errors.push('Items array cannot be empty');
  }

  payload.items.forEach((item, index) => {
    if (!item.item_code) errors.push(`Item ${index}: missing item_code`);
    if (!item.name) errors.push(`Item ${index}: missing name`);
    if (typeof item.qty !== 'number' || item.qty <= 0) errors.push(`Item ${index}: invalid qty`);
    if (!item.unit) errors.push(`Item ${index}: missing unit`);
    if (!item.category) errors.push(`Item ${index}: missing category`);
  });

  return { valid: errors.length === 0, errors };
}

/**
 * 驗證 TEMPLATE payload
 * @param {object} payload
 * @returns {{ valid: boolean, errors: string[] }}
 */
function validateTemplatePayload(payload) {
  const errors = [];

  if (!payload.template_name) {
    errors.push('Missing template_name');
  }

  if (!payload.items || !Array.isArray(payload.items)) {
    errors.push('Missing or invalid items array');
    return { valid: false, errors };
  }

  return { valid: errors.length === 0, errors };
}

// ============================================================================
// 解析函式
// ============================================================================

/**
 * 解析 QR Code 內容
 * @param {string} rawData - QR Code 原始資料
 * @returns {{ success: boolean, envelope: object|null, error: string|null }}
 */
function parseQRContent(rawData) {
  try {
    let jsonStr = rawData;

    // 檢查是否為壓縮格式 (Phase 2)
    if (rawData.startsWith('GZ:')) {
      // TODO: Phase 2 實作 gzip 解壓縮
      return { success: false, envelope: null, error: 'Compressed format not yet supported' };
    }

    // 嘗試解析 JSON
    const envelope = JSON.parse(jsonStr);

    // 驗證信封格式
    const validation = validateEnvelope(envelope);
    if (!validation.valid) {
      return {
        success: false,
        envelope: null,
        error: validation.errors.join(', ')
      };
    }

    // 驗證 payload
    let payloadValidation = { valid: true, errors: [] };
    if (envelope.message_type === MESSAGE_TYPES.DISTRIBUTION) {
      payloadValidation = validateDistributionPayload(envelope.payload);
    } else if (envelope.message_type === MESSAGE_TYPES.TEMPLATE) {
      payloadValidation = validateTemplatePayload(envelope.payload);
    } else if (envelope.message_type === MESSAGE_TYPES.DONATION_RECEIPT) {
      payloadValidation = validateDonationReceiptPayload(envelope.payload);
    }

    if (!payloadValidation.valid) {
      return {
        success: false,
        envelope: null,
        error: payloadValidation.errors.join(', ')
      };
    }

    return { success: true, envelope, error: null };

  } catch (e) {
    return { success: false, envelope: null, error: `JSON parse error: ${e.message}` };
  }
}

/**
 * 檢查是否為舊版 CIRS QR 格式（向下相容）
 * @param {object} data - 解析後的 JSON
 * @returns {boolean}
 */
function isLegacyCIRSFormat(data) {
  // 舊版格式：{ source, timestamp, items }，沒有 schema_version
  return data && data.source && data.items && !data.schema_version;
}

/**
 * 將舊版 CIRS 格式轉換為新版 Envelope
 * @param {object} legacyData
 * @returns {object} - 新版 Envelope
 */
function convertLegacyToEnvelope(legacyData) {
  return {
    schema_version: IRS_SCHEMA_VERSION,
    message_type: MESSAGE_TYPES.DISTRIBUTION,
    issuer: {
      system: SYSTEMS.CIRS,
      site_id: 'CIRS-LEGACY',
      site_name: legacyData.source || '社區物資站'
    },
    timestamp: legacyData.timestamp || new Date().toISOString(),
    message_id: generateUUID(),
    payload: {
      distribution_id: `LEGACY-${Date.now()}`,
      items: legacyData.items.map(item => ({
        item_code: `CUSTOM-${item.name.replace(/\s/g, '-')}`,
        name: item.name,
        qty: item.qty,
        unit: item.unit || '個',
        category: item.category || 'other'
      }))
    }
  };
}

// ============================================================================
// 產生函式
// ============================================================================

/**
 * 產生 UUID v4
 * @returns {string}
 */
function generateUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    const r = Math.random() * 16 | 0;
    const v = c === 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

/**
 * 建立 DISTRIBUTION 信封
 * @param {object} params
 * @param {object} params.issuer - { system, site_id, site_name }
 * @param {object} params.recipient - { display_name, household_size }
 * @param {array} params.items - 發放品項
 * @param {string} params.notes - 備註
 * @returns {object} - 完整信封
 */
function createDistributionEnvelope({ issuer, recipient, items, notes }) {
  return {
    schema_version: IRS_SCHEMA_VERSION,
    message_type: MESSAGE_TYPES.DISTRIBUTION,
    issuer: {
      system: issuer.system || SYSTEMS.CIRS,
      site_id: issuer.site_id,
      site_name: issuer.site_name
    },
    timestamp: new Date().toISOString(),
    message_id: generateUUID(),
    payload: {
      distribution_id: `DIST-${Date.now()}`,
      recipient: recipient || {},
      items: items.map(item => ({
        item_code: item.item_code || `CUSTOM-${generateUUID().slice(0, 8)}`,
        name: item.name,
        qty: item.qty,
        unit: item.unit,
        category: item.category || 'other',
        expiry_date: item.expiry_date || null
      })),
      notes: notes || ''
    }
  };
}

/**
 * 建立 TEMPLATE 信封
 * @param {object} params
 * @returns {object} - 完整信封
 */
function createTemplateEnvelope({ issuer, template_name, description, household_size, target_days, items, tags, author }) {
  return {
    schema_version: IRS_SCHEMA_VERSION,
    message_type: MESSAGE_TYPES.TEMPLATE,
    issuer: {
      system: issuer.system || SYSTEMS.HIRS,
      site_id: issuer.site_id || `HIRS-${generateUUID().slice(0, 8)}`,
      site_name: issuer.site_name || template_name
    },
    timestamp: new Date().toISOString(),
    message_id: generateUUID(),
    payload: {
      template_id: `TPL-${Date.now()}`,
      template_name,
      description: description || '',
      household_size: household_size || 1,
      target_days: target_days || 3,
      items: items.map(item => ({
        item_code: item.item_code || `CUSTOM-${generateUUID().slice(0, 8)}`,
        name: item.name,
        qty: item.qty,
        unit: item.unit,
        category: item.category || 'other',
        is_required: item.is_required !== false,
        purchase_url: item.purchase_url || null
      })),
      tags: tags || [],
      author: author || ''
    }
  };
}

/**
 * 建立 DONATION_RECEIPT 信封
 * @param {object} params
 * @param {object} params.issuer - { system, site_id, site_name }
 * @param {string} params.donor_name - 捐贈者姓名（選填）
 * @param {array} params.items - 捐贈品項
 * @param {string} params.thank_you_note - 感謝詞
 * @param {string} params.notes - 備註
 * @returns {object} - 完整信封
 */
function createDonationReceiptEnvelope({ issuer, donor_name, items, thank_you_note, notes }) {
  const now = new Date();
  const dateStr = now.toISOString().slice(0, 10).replace(/-/g, '');
  const siteId = issuer.site_id || 'CIRS-DEFAULT';

  return {
    schema_version: IRS_SCHEMA_VERSION,
    message_type: MESSAGE_TYPES.DONATION_RECEIPT,
    issuer: {
      system: issuer.system || SYSTEMS.CIRS,
      site_id: siteId,
      site_name: issuer.site_name || 'CIRS 社區物資站'
    },
    timestamp: now.toISOString(),
    message_id: generateUUID(),
    payload: {
      receipt_id: `DON-${siteId}-${dateStr}-${generateUUID().slice(0, 4).toUpperCase()}`,
      donor_name: donor_name || '',
      items: items.map(item => ({
        item_code: item.item_code || `CUSTOM-${generateUUID().slice(0, 8)}`,
        name: item.name,
        qty: item.qty,
        unit: item.unit || '個',
        category: item.category || 'other'
      })),
      thank_you_note: thank_you_note || '感謝您的愛心捐贈！',
      notes: notes || ''
    }
  };
}

/**
 * 驗證 DONATION_RECEIPT payload
 * @param {object} payload
 * @returns {{ valid: boolean, errors: string[] }}
 */
function validateDonationReceiptPayload(payload) {
  const errors = [];

  if (!payload.receipt_id) {
    errors.push('Missing receipt_id');
  }

  if (!payload.items || !Array.isArray(payload.items)) {
    errors.push('Missing or invalid items array');
    return { valid: false, errors };
  }

  if (payload.items.length === 0) {
    errors.push('Items array cannot be empty');
  }

  payload.items.forEach((item, index) => {
    if (!item.name) errors.push(`Item ${index}: missing name`);
    if (typeof item.qty !== 'number' || item.qty <= 0) errors.push(`Item ${index}: invalid qty`);
  });

  return { valid: errors.length === 0, errors };
}

// ============================================================================
// 工具函式
// ============================================================================

/**
 * 取得分類資訊
 * @param {string} categoryCode
 * @returns {object}
 */
function getCategoryInfo(categoryCode) {
  return CATEGORIES[categoryCode] || CATEGORIES.other;
}

/**
 * 檢查購買連結是否在白名單
 * @param {string} url
 * @returns {boolean}
 */
function isPurchaseUrlAllowed(url) {
  if (!url) return true;
  try {
    const hostname = new URL(url).hostname;
    return PURCHASE_URL_ALLOWLIST.some(domain => hostname.endsWith(domain));
  } catch {
    return false;
  }
}

/**
 * 正規化品項（合併相同 item_code）
 * @param {array} existingItems - 現有庫存
 * @param {array} newItems - 新匯入品項
 * @returns {array} - 合併後的品項
 */
function mergeItems(existingItems, newItems) {
  const itemMap = new Map();

  // 先加入現有品項
  existingItems.forEach(item => {
    itemMap.set(item.item_code, { ...item });
  });

  // 合併新品項
  newItems.forEach(newItem => {
    if (itemMap.has(newItem.item_code)) {
      const existing = itemMap.get(newItem.item_code);
      // 單位相同才合併數量
      if (existing.unit === newItem.unit) {
        existing.qty += newItem.qty;
      } else {
        // 單位不同，使用新的 item_code
        const newCode = `${newItem.item_code}-${generateUUID().slice(0, 4)}`;
        itemMap.set(newCode, { ...newItem, item_code: newCode });
      }
    } else {
      itemMap.set(newItem.item_code, { ...newItem });
    }
  });

  return Array.from(itemMap.values());
}

// ============================================================================
// 匯出
// ============================================================================

// 如果在 Node.js 環境
if (typeof module !== 'undefined' && module.exports) {
  module.exports = {
    IRS_SCHEMA_VERSION,
    MESSAGE_TYPES,
    SYSTEMS,
    CATEGORIES,
    PURCHASE_URL_ALLOWLIST,
    ERROR_CODES,
    IRSValidationError,
    validateEnvelope,
    validateDistributionPayload,
    validateTemplatePayload,
    validateDonationReceiptPayload,
    parseQRContent,
    isLegacyCIRSFormat,
    convertLegacyToEnvelope,
    generateUUID,
    createDistributionEnvelope,
    createTemplateEnvelope,
    createDonationReceiptEnvelope,
    getCategoryInfo,
    isPurchaseUrlAllowed,
    mergeItems
  };
}

// 如果在瀏覽器環境
if (typeof window !== 'undefined') {
  window.IRSSchema = {
    IRS_SCHEMA_VERSION,
    MESSAGE_TYPES,
    SYSTEMS,
    CATEGORIES,
    PURCHASE_URL_ALLOWLIST,
    ERROR_CODES,
    IRSValidationError,
    validateEnvelope,
    validateDistributionPayload,
    validateTemplatePayload,
    validateDonationReceiptPayload,
    parseQRContent,
    isLegacyCIRSFormat,
    convertLegacyToEnvelope,
    generateUUID,
    createDistributionEnvelope,
    createTemplateEnvelope,
    createDonationReceiptEnvelope,
    getCategoryInfo,
    isPurchaseUrlAllowed,
    mergeItems
  };
}
