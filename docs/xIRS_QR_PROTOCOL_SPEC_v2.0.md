# xIRS QR Code Protocol & Security Spec v2.0

**Version**: 2.0 (Hardened)
**Date**: 2025-12-23
**Supersedes**: QR_CODE_ISSUES_SPEC.md
**Contributors**: Claude, ChatGPT, Gemini
**Mandate**: Solves iOS Camera limits, Payload Capacity, Privacy, and Replay Protection.

---

## Executive Summary

This specification defines the complete QR code protocol for xIRS clinical data exchange, addressing:

1. **Rendering Stability**: Canvas-to-Image fix for cross-browser compatibility
2. **iOS Camera Access**: HTTPS requirement and fallback strategies
3. **Payload Capacity**: Chunking protocol for large clinical data
4. **Privacy Boundary**: No Class-A PII in QR payloads
5. **Replay Protection**: Pharmacy-side duplicate scan prevention

---

## 1. The Protocol: "XIR1" Chunking Standard

### 1.1 Format Definition

All QR codes MUST follow this text format:

```
XIR1|{type}|{seq}/{total}|{payload_b64}|{checksum}
```

| Segment | Description | Example |
|---------|-------------|---------|
| **Header** | Protocol ID (fixed) | `XIR1` |
| **Type** | Packet Type | `RX`, `RPT`, `MF`, `PROC` |
| **Seq/Total** | Chunk Index (1-based) | `1/1` or `2/3` |
| **Payload** | Base64-encoded data | `eyJyeF9pZCI6...` |
| **Checksum** | CRC32 of payload (hex) | `a1b2c3d4` |

### 1.2 Packet Types

| Type | Description | Max Chunks |
|------|-------------|------------|
| `RX` | Prescription Order | 5 |
| `PROC` | Procedure Record | 3 |
| `RPT` | Clinical Report | 10 |
| `MF` | Medication Manifest | 20 |
| `REG` | Registration Info | 2 |

### 1.3 Constraints

| Constraint | Value | Rationale |
|------------|-------|-----------|
| Max Chunk Size | 800 chars | QR Version 10-15, easily scannable |
| Max Payload per Chunk | ~600 bytes | After protocol overhead |
| Error Correction | Level 'L' | Maximize data density |
| Encoding | UTF-8 → Base64 | Cross-platform compatibility |

### 1.4 Example

Single-chunk Rx:
```
XIR1|RX|1/1|eyJyeF9pZCI6IlJYLURPQzAwMS0yMDI1MTIyMy0wMDAxIiwicGF0aWVudF9yZWYiOiJQLTAwMS1BN0IzIiwiaXRlbXMiOlt7ImNvZGUiOiJNRUQtUEFSQS01MDAiLCJxdHkiOjZ9XX0=|7f3a2b1c
```

Multi-chunk (3 parts):
```
XIR1|RX|1/3|eyJyeF9pZCI6IlJYLURPQzAwMS0yMDI1MTIyMy0wMDAxIiwicGF0aWVudF9yZWYi...|a1b2c3d4
XIR1|RX|2/3|OnsiY29kZSI6Ik1FRC1QQVJBLTUwMCIsInF0eSI6Nn0seyJjb2RlIjoiTUVELU...|b2c3d4e5
XIR1|RX|3/3|FNPWi01MDAiLCJxdHkiOjl9XX0sInNpZ25hdHVyZSI6IjxlZDI1NTE5PiJ9|c3d4e5f6
```

---

## 2. Privacy Boundary: No Class-A Data in QR

### 2.1 Data Classification

| Class | Examples | In QR? |
|-------|----------|--------|
| **Class A (PII)** | patient_name, national_id, address | **NO** |
| **Class B (Reference)** | patient_ref, display_label, reg_id | YES |
| **Class C (Clinical)** | medication codes, dosages, procedures | YES |
| **Class D (Metadata)** | timestamps, signatures, checksums | YES |

### 2.2 QR Payload Schema (RX_ORDER)

```json
{
  "type": "RX_ORDER",
  "v": "2.0",
  "rx_id": "RX-DOC001-20251223-0001",
  "patient_ref": "P-001-A7B3",
  "display_label": "TRIAGE-GREEN / M~40",
  "encounter_id": "REG-20251223-001",
  "items": [
    { "code": "MED-PARA-500", "qty": 6, "freq": "TID", "days": 3 }
  ],
  "priority": "ROUTINE",
  "nonce": "abc123def456",
  "expires_at": 1735012800,
  "ts": 1734926400,
  "prescriber_id": "DOC-001",
  "signature": "<ed25519_signature>"
}
```

**Forbidden fields**: `patient_name`, `patient_id`, `address`, `phone`, `national_id`

---

## 3. Rendering Implementation

### 3.1 Problem: Canvas Instability

- iOS Safari has inconsistent canvas rendering
- Alpine.js timing issues with DOM elements
- Cross-origin issues with some canvas operations

### 3.2 Solution: DataURL + Image Tag

```javascript
// Generate at sign-time, not render-time
async function generateQRDataURLs(payload) {
    const chunks = QRProtocol.generateChunks('RX', payload);
    const dataURLs = await Promise.all(
        chunks.map(chunk => QRProtocol.renderToDataURL(chunk))
    );
    return dataURLs;
}

// Render is just setting img.src
function renderQR(dataURLs, index) {
    document.getElementById('qr-image').src = dataURLs[index];
}
```

### 3.3 UI Requirements

```
┌────────────────────────────────────────┐
│              ✓ 處方已開立               │
│         RX-DOC001-20251223-0001        │
│                                        │
│         ┌──────────────────┐           │
│         │   [QR CODE IMG]  │           │
│         │                  │           │
│         │    250 x 250     │           │
│         └──────────────────┘           │
│              1 / 3                     │
│         [◀ Prev]  [Next ▶]             │
│                                        │
│    ─────────────────────────────────   │
│    RX-DOC001-20251223-0001  [📋 Copy]  │
│                                        │
│    無法掃描？請將編號告知藥局人員         │
└────────────────────────────────────────┘
```

**Mandatory Elements**:
1. QR Image (not canvas)
2. Human-readable Rx ID displayed
3. Copy button for Rx ID
4. Multi-QR navigation (if chunked)
5. Fallback text for manual handoff

---

## 4. Scanning Implementation

### 4.1 Problem: iOS Camera Access

| Context | Camera Access |
|---------|---------------|
| `https://` | ✅ Allowed |
| `http://localhost` | ✅ Allowed |
| `http://127.0.0.1` | ✅ Allowed |
| `http://192.168.x.x` (LAN) | ❌ **BLOCKED** |
| `http://10.x.x.x` (LAN) | ❌ **BLOCKED** |

### 4.2 Development Environment Solutions

| Method | Command | Use Case |
|--------|---------|----------|
| **localhost** | `python main.py` → `localhost:8090` | Single device testing |
| **ngrok** | `ngrok http 8090` | Quick HTTPS tunnel |
| **mkcert** | `mkcert -install && mkcert 192.168.1.x` | Local CA + cert |
| **Caddy** | `caddy reverse-proxy --to localhost:8090` | Auto HTTPS |

### 4.3 Scanner Error Handling

```javascript
async startScanner() {
    try {
        await scanner.start({ facingMode: 'environment' }, config, onSuccess);
    } catch (err) {
        if (err.name === 'NotAllowedError') {
            showError('請在設定中允許相機權限');
        } else if (err.name === 'NotFoundError') {
            showError('找不到相機裝置');
        } else if (!window.isSecureContext) {
            showError('相機需要 HTTPS 連線\n請使用手動輸入');
            showManualInputTab();
        } else {
            showError('相機無法啟動: ' + err.message);
        }
    }
}
```

### 4.4 Fallback UI (First-Class Citizen)

```
┌────────────────────────────────────────┐
│  [📷 掃描]  [⌨️ 手動輸入]  [📁 上傳]    │
├────────────────────────────────────────┤
│                                        │
│  Tab 1: Camera Scanner                 │
│  ┌──────────────────────────────────┐ │
│  │                                  │ │
│  │         [Camera Feed]            │ │
│  │                                  │ │
│  └──────────────────────────────────┘ │
│                                        │
│  Tab 2: Manual Input                   │
│  ┌──────────────────────────────────┐ │
│  │  請輸入或貼上處方編號:             │ │
│  │  [RX-________________]  [查詢]   │ │
│  └──────────────────────────────────┘ │
│                                        │
│  Tab 3: Upload Image                   │
│  ┌──────────────────────────────────┐ │
│  │  [📷 選擇或拍攝 QR Code 圖片]     │ │
│  └──────────────────────────────────┘ │
│                                        │
└────────────────────────────────────────┘
```

---

## 5. Security: Replay Protection

### 5.1 Problem

Without replay protection, the same QR code can be scanned multiple times, causing:
- Double dispensing of medications
- Inventory discrepancies
- Audit trail corruption

### 5.2 Solution: Nonce + Processed Store

**Pharmacy IndexedDB Schema**:
```javascript
// Store: processed_packets
{
    keyPath: 'packet_id',  // rx_id or proc_id
    indexes: ['processed_at', 'nonce']
}
```

**Validation Flow**:
```javascript
async function validateAndProcess(packet) {
    const db = await openDB();

    // 1. Check if already processed
    const existing = await db.get('processed_packets', packet.rx_id);
    if (existing) {
        throw new Error(`DUPLICATE: 此處方已於 ${existing.processed_at} 處理`);
    }

    // 2. Verify signature
    const isValid = verifySignature(packet);
    if (!isValid) {
        throw new Error('INVALID_SIGNATURE: 處方簽章驗證失敗');
    }

    // 3. Check expiration
    if (packet.expires_at && Date.now() / 1000 > packet.expires_at) {
        throw new Error('EXPIRED: 處方已過期');
    }

    // 4. Process and record
    await dispensemedications(packet);
    await db.put('processed_packets', {
        packet_id: packet.rx_id,
        nonce: packet.nonce,
        processed_at: new Date().toISOString(),
        processed_by: getCurrentPharmacist()
    });

    return { success: true };
}
```

### 5.3 Nonce Generation

```javascript
// Generate at Rx creation time
function generateNonce() {
    const array = new Uint8Array(12);
    crypto.getRandomValues(array);
    return Array.from(array, b => b.toString(16).padStart(2, '0')).join('');
}
```

---

## 6. Implementation Checklist

### 6.1 Shared Library (`shared/js/xirs-qr.js`)

- [ ] `QRProtocol.generateChunks(type, payload)` - Split with CRC32
- [ ] `QRProtocol.renderToDataURL(chunkText)` - Generate image
- [ ] `QRProtocol.parsePacket(scannedText)` - Validate and extract
- [ ] `QRProtocol.validateChecksum(chunk)` - CRC32 verification
- [ ] `QRProtocol.assembleChunks(chunks[])` - Multi-QR reassembly

### 6.2 Doctor PWA Updates

- [ ] Remove Class-A data from QR payload
- [ ] Add `nonce` and `expires_at` to Rx
- [ ] Generate DataURLs at sign-time
- [ ] Replace canvas with img tag
- [ ] Add prominent Rx ID display + Copy button
- [ ] Add "Copy Rx ID" fallback link

### 6.3 Pharmacy PWA Updates

- [ ] Implement XIR1 protocol parser
- [ ] Add secure context detection
- [ ] Add Manual Input tab (first-class)
- [ ] Add Image Upload tab
- [ ] Implement replay protection with IndexedDB
- [ ] Show clear error messages for camera failures

### 6.4 Documentation Updates

- [ ] README: Add HTTPS requirement warning
- [ ] TEST_MEDICATION_FLOW.md: Update with HTTPS instructions
- [ ] Add mkcert/ngrok setup guide

---

## 7. Testing Matrix

| Test Case | Chrome Desktop | Safari iOS | Chrome Android |
|-----------|---------------|------------|----------------|
| QR renders (single) | | | |
| QR renders (multi-chunk) | | | |
| Camera scan (localhost) | | | |
| Camera scan (HTTPS) | | | |
| Camera scan (HTTP LAN) | ❌ Expected | ❌ Expected | ❌ Expected |
| Manual input fallback | | | |
| Image upload decode | | | |
| Replay rejection | | | |
| Expired Rx rejection | | | |
| Copy Rx ID works | | | |

---

## 8. Migration Notes

### From v1.x to v2.0

1. **QR Format Change**: Old format (`XIR1|1/1|payload`) → New format (`XIR1|RX|1/1|payload|crc32`)
2. **Backward Compatibility**: Parser should accept both formats during transition
3. **Database Migration**: Add `processed_packets` store to Pharmacy IndexedDB

---

## References

- [html5-qrcode library](https://github.com/mebjas/html5-qrcode)
- [qrcode library](https://github.com/soldair/node-qrcode)
- [MDN: Secure Contexts](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts)
- [WebKit Camera Policies](https://webkit.org/blog/6784/new-video-policies-for-ios/)
- [CRC32 Algorithm](https://en.wikipedia.org/wiki/Cyclic_redundancy_check)
