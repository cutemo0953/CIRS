# xIRS Distributed Logistics Spec v1.8

**Version**: 1.8 (Hardened Protocol)
**Theme**: Robust Hybrid Logistics (Paper Down, Digital Up)
**System**: CIRS & MIRS
**Security**: End-to-End Integrity, Blind Carrier, Replay Protection
**Date**: 2025-12-21
**Status**: Phase 1-4 Implemented, Phase 5 In Progress

---

## Implementation Status

| Phase | Component | Status | Location |
|-------|-----------|--------|----------|
| 1-2 | Hub Backend API | ✅ Done | `/backend/routes/logistics.py` |
| 3 | Station PWA | ✅ Done | `/frontend/station/` |
| 4 | Runner PWA | ✅ Done | `/frontend/runner/` |
| 5A | Lite CPOE Protocol | ✅ Done | `/shared/js/xirs-rx.js`, `xirs-dispense.js` |
| 5B | Doctor PWA | ✅ Done | `/frontend/doctor/` |
| 5C | Pharmacy Extension | ⏳ Pending | - |
| 5D | Hub Rx Integration | ⏳ Pending | - |

---

## 1. Architecture Overview

### 1.1 The "Store-and-Forward" Model

Designed for environments with **zero connectivity** between nodes.

* **Hub (Server)**: The Authority. Generates signed physical manifests.
* **Station (Sub-hub)**: The Edge. Offline-first iPad. Consumes manifests, produces encrypted reports.
* **Runner (Messenger)**: The Carrier. Dumb smartphone. Carries opaque payloads (Blind Mule).

```
┌─────────────────────────────────────────────────────────────────────┐
│                         COVERAGE AREA                               │
│                                                                     │
│  ┌─────────────┐      Paper QR       ┌─────────────┐               │
│  │             │  ─────────────────► │             │               │
│  │     HUB     │                     │   STATION   │               │
│  │  (Pi + SSD) │  ◄───────────────── │   (iPad)    │               │
│  │             │    Runner + Phone   │             │               │
│  └─────────────┘                     └─────────────┘               │
│        │                                    │                       │
│        │ WiFi                               │ Local Only            │
│        ▼                                    ▼                       │
│  ┌───────────┐                       ┌───────────┐                 │
│  │ Dashboard │                       │  Offline  │                 │
│  │  (Admin)  │                       │   Cache   │                 │
│  └───────────┘                       └───────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 The "Voucher" Protocol

Data is encapsulated in **"Packets"** transported via QR Codes.

| Direction | Packet Type | Format | Security | Fallback |
|-----------|-------------|--------|----------|----------|
| **Hub → Station** | `RESTOCK_MANIFEST` | Printed Paper QR | **Signed** (Hub PrivKey) | Manual `manifest_code` |
| **Station → Hub** | `REPORT_PACKET` | Digital Screen QR | **Encrypted** (Hub PubKey) + **HMAC** | Manual `packet_id` (Claim later) |

### 1.3 Role Definitions

| Role | Device | Connectivity | Trust Level | Actions |
|------|--------|--------------|-------------|---------|
| **Hub Admin** | PC/Laptop | WiFi to Hub | Full | Create manifests, receive reports, reconcile |
| **Station Lead** | iPad | None (Offline) | High | Scan manifests, dispense, generate reports |
| **Runner** | Smartphone (PWA) | None | **Zero** (Blind Carrier) | Transport opaque payloads only |

---

## 2. Protocol Specifications (Critical Hardening)

### 2.1 QR Payload Constraints

To ensure readability on low-end devices in poor lighting:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max Payload | **800 bytes** (Base64) | L-level ECC, readable at 30cm |
| Error Correction | Level L (7%) | Balance size vs. resilience |
| QR Version | ≤ 25 | Fits most phone cameras |

**Chunking Strategy**: If payload > 800 bytes, use **Animated QR** (or Swipe Gallery).

```
Format: xIRS|{seq}/{total}|{chunk_data_base64}

Example (3-part packet):
  QR 1: xIRS|1/3|eyJpZCI6IlQwMDEiLC...
  QR 2: xIRS|2/3|ImFjdGlvbnMiOlt7In...
  QR 3: xIRS|3/3|fV19Cg==
```

**Reassembly Logic**:
1. Scanner collects chunks into buffer
2. Wait for `total` chunks received
3. Concatenate in order
4. Base64 decode full payload
5. Validate structure (JSON parse, signature verify)

### 2.2 Security: The "Blind Carrier"

Runners must not be able to read or tamper with Station data.

```
Station                    Runner                     Hub
   │                          │                         │
   │  ┌──────────────────┐    │                         │
   │  │ 1. Serialize     │    │                         │
   │  │ 2. Encrypt       │    │                         │
   │  │    (SealedBox)   │    │                         │
   │  │ 3. Compute HMAC  │    │                         │
   │  └────────┬─────────┘    │                         │
   │           │              │                         │
   │           ▼              │                         │
   │  ┌──────────────────┐    │                         │
   │  │ Display QR Code  │───►│ Scan & Store            │
   │  └──────────────────┘    │ (Opaque Blob)           │
   │                          │                         │
   │                          │  ┌──────────────────┐   │
   │                          │  │ Display QR Code  │──►│
   │                          │  └──────────────────┘   │
   │                          │                         │
   │                          │    ┌────────────────┐   │
   │                          │    │ 1. Decrypt     │   │
   │                          │    │ 2. Verify HMAC │   │
   │                          │    │ 3. Check Dedup │   │
   │                          │    │ 4. Apply Logs  │   │
   │                          │    └────────────────┘   │
```

**Encryption**: Use **NaCl SealedBox** (Anonymous Encryption).
- Station encrypts payload using `Hub_Public_Key`
- Runner sees only ciphertext
- Hub decrypts using `Hub_Private_Key`

**Integrity (HMAC)**:
- Hub issues a `station_secret` during initial pairing
- Station computes `HMAC-SHA256(station_secret, payload)`
- Hub verifies HMAC to authenticate the source Station

### 2.3 Idempotency & Replay Protection

**Problem**: Runners might accidentally deliver the same packet twice.

**Solution**:

```sql
-- Hub: Deduplication Table
CREATE TABLE seen_packets (
    packet_id TEXT PRIMARY KEY,
    station_id TEXT NOT NULL,
    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    payload_hash TEXT NOT NULL
);

-- Station: Processed Manifests
CREATE TABLE processed_manifests (
    manifest_id TEXT PRIMARY KEY,
    processed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    items_received TEXT  -- JSON
);
```

**Hub Logic**:
1. Extract `packet_id` from decrypted payload
2. Check `seen_packets` table
3. If exists: Return `ACK` but **DO NOT** re-apply changes
4. If new: Apply changes, insert into `seen_packets`

**Station Logic**:
1. Scan manifest QR
2. Check `processed_manifests` table
3. If exists: Show "Already processed" warning
4. If new: Apply stock addition, insert record

### 2.4 Packet Structure

**RESTOCK_MANIFEST (Hub → Station)**:

```json
{
  "type": "RESTOCK_MANIFEST",
  "version": "1.8",
  "manifest_id": "M-2025-1220-001",
  "short_code": "8821",           // 4-digit fallback
  "station_id": "STATION-PARK",
  "items": [
    {"code": "WATER-500ML", "qty": 100, "unit": "bottle"},
    {"code": "RICE-1KG", "qty": 50, "unit": "bag"}
  ],
  "ts": 1734700000,
  "nonce": "a1b2c3d4e5f6",
  "signature": "Ed25519(...)"     // Sign(hub_private_key, payload)
}
```

**REPORT_PACKET (Station → Hub)**:

```json
{
  "type": "REPORT_PACKET",
  "version": "1.8",
  "packet_id": "PKT-a1b2c3d4",    // UUIDv4
  "station_id": "STATION-PARK",
  "seq_id": 42,                   // Monotonic per station
  "actions": [
    {
      "action_id": "ACT-001",
      "type": "DISPENSE",
      "item_code": "WATER-500ML",
      "qty": 5,
      "recipient": "避難者 #12",
      "ts": 1734701000
    }
  ],
  "snapshot": {
    "WATER-500ML": 95,
    "RICE-1KG": 50
  },
  "ts": 1734702000,
  "hmac": "HMAC-SHA256(...)"      // HMAC(station_secret, payload)
}
```

---

## 3. Workflow Specifications

### Scenario A: Resupply (Hub → Station) - "The Paper Stream"

**Goal**: Send 100 Water bottles to Park Station.

```
┌─────────────────────────────────────────────────────────────────┐
│ HUB                                                             │
│                                                                 │
│  1. Admin creates Transfer #T001                                │
│  2. System generates RESTOCK_MANIFEST                           │
│  3. PRINT physical manifest (Paper + QR)                        │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ╔═══════════════════════════════════════════════════╗  │   │
│  │  ║  CIRS RESUPPLY MANIFEST                           ║  │   │
│  │  ║                                                   ║  │   │
│  │  ║  TO: Park Station                                 ║  │   │
│  │  ║  DATE: 2025-12-20 14:30                           ║  │   │
│  │  ║                                                   ║  │   │
│  │  ║  ITEMS:                                           ║  │   │
│  │  ║    □ Water 500ml ............... 100 bottles     ║  │   │
│  │  ║    □ Rice 1kg ................... 50 bags        ║  │   │
│  │  ║                                                   ║  │   │
│  │  ║  ┌─────────┐                                      ║  │   │
│  │  ║  │ [QR]    │  CODE: 8821                          ║  │   │
│  │  ║  │         │  (Use if QR fails)                   ║  │   │
│  │  ║  └─────────┘                                      ║  │   │
│  │  ║                                                   ║  │   │
│  │  ║  Signature: ________________________              ║  │   │
│  │  ╚═══════════════════════════════════════════════════╝  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  4. Hand paper to Runner                                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Physical Transport (Runner)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ STATION                                                         │
│                                                                 │
│  5. Lead taps "Scan Manifest"                                   │
│                                                                 │
│  ┌─ SUCCESS PATH ──────────────────────────────────────────┐   │
│  │ • Camera scans QR                                        │   │
│  │ • Verify Ed25519 signature                               │   │
│  │ • Check manifest_id not in processed_manifests           │   │
│  │ • Add items to local inventory                           │   │
│  │ • Show confirmation: "✓ Received 100 Water, 50 Rice"     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─ FALLBACK PATH (QR Unreadable) ─────────────────────────┐   │
│  │ • Lead taps "Manual Entry"                               │   │
│  │ • Types short code: 8821                                 │   │
│  │ • System logs as "UNVERIFIED_CLAIM"                      │   │
│  │ • Items added provisionally                              │   │
│  │ • Hub reconciles on next sync                            │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│  6. Lead signs paper manifest physically                        │
│  7. Runner returns signed paper to Hub                          │
└─────────────────────────────────────────────────────────────────┘
```

### Scenario B: Reporting (Station → Hub) - "The Digital Mule"

**Goal**: Station reports "Dispensed 50 Water".

```
┌─────────────────────────────────────────────────────────────────┐
│ STATION                                                         │
│                                                                 │
│  1. Lead taps "Generate Report"                                 │
│  2. System collects all pending action logs                     │
│  3. Compress + Encrypt (SealedBox) + HMAC                       │
│  4. Generate QR Code(s)                                         │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                         │   │
│  │            ┌───────────────────┐                        │   │
│  │            │                   │                        │   │
│  │            │    [QR CODE]      │                        │   │
│  │            │                   │                        │   │
│  │            │   (1/3)           │                        │   │
│  │            └───────────────────┘                        │   │
│  │                                                         │   │
│  │            Packet #A1B2C3D4                              │   │
│  │            Actions: 12 | Size: 1.2KB                     │   │
│  │                                                         │   │
│  │            [ ← Prev ]  [ Next → ]                        │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Runner scans with phone
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ RUNNER (PWA - Blind Carrier Mode)                               │
│                                                                 │
│  5. Tap "Pickup Packet"                                         │
│  6. Scan all QR chunks                                          │
│  7. Store opaque blob to IndexedDB                              │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                         │   │
│  │   📦 PACKET RECEIVED                                    │   │
│  │                                                         │   │
│  │   ID: A1B2C3D4                                          │   │
│  │   Source: Park Station                                   │   │
│  │   Size: 1.2 KB (encrypted)                               │   │
│  │   Time: 14:35                                            │   │
│  │                                                         │   │
│  │   Status: ✓ Ready for Delivery                           │   │
│  │                                                         │   │
│  │   ⚠️ You cannot view packet contents                     │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  8. Runner physically travels to Hub                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Physical Transport
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ HUB                                                             │
│                                                                 │
│  9. Admin taps "Receive Packet"                                 │
│ 10. Scan Runner's phone (displays QR from IndexedDB)            │
│ 11. Decrypt (SealedBox) with Hub Private Key                    │
│ 12. Verify HMAC with station_secret                             │
│ 13. Check packet_id for deduplication                           │
│                                                                 │
│  ┌─ RECONCILIATION ────────────────────────────────────────┐   │
│  │ • Apply each action log to global inventory              │   │
│  │ • Compare snapshot with expected values                  │   │
│  │ • If mismatch: Log "AUDIT_ALERT" for review              │   │
│  │ • Update last_sync_time for station                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│ 14. Show confirmation: "✓ 12 actions synced from Park Station"  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Scenario C: Red Flare (Urgent Request)

**Goal**: Critical Oxygen shortage at Station.

```
┌─────────────────────────────────────────────────────────────────┐
│ STATION                                                         │
│                                                                 │
│  1. Lead taps "🚨 EMERGENCY REQUEST"                            │
│  2. Select resource type and urgency                            │
│  3. System generates HIGH-PRIORITY packet                       │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  🚨 EMERGENCY REQUEST                                   │   │
│  │                                                         │   │
│  │  Resource: OXYGEN                                        │   │
│  │  Urgency: CRITICAL (< 2 hours)                           │   │
│  │  Current: 2 tanks remaining                              │   │
│  │  Needed: 10 tanks                                        │   │
│  │                                                         │   │
│  │  [ GENERATE QR ]                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ Runner scans
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ RUNNER (PWA - ALERT MODE)                                       │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ██████████████████████████████████████████████████████ │   │
│  │  ██                                                  ██ │   │
│  │  ██   🚨 URGENT PACKET                               ██ │   │
│  │  ██                                                  ██ │   │
│  │  ██   Source: Park Station                           ██ │   │
│  │  ██   Priority: CRITICAL                             ██ │   │
│  │  ██                                                  ██ │   │
│  │  ██   ⚠️ RETURN TO HUB IMMEDIATELY                   ██ │   │
│  │  ██                                                  ██ │   │
│  │  ██   [ I ACKNOWLEDGE ]                              ██ │   │
│  │  ██                                                  ██ │   │
│  │  ██████████████████████████████████████████████████████ │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  BEHAVIOR:                                                      │
│  • Background: SOLID RED                                        │
│  • Haptic: Vibrate 3x every 30 seconds                          │
│  • Sound: Optional alarm tone                                   │
│  • ACK Button: Stops vibration, keeps red background            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Operational Fallbacks & Infrastructure

### 4.1 "Survival Kit" (SPOF Mitigation)

To run this architecture on a single Raspberry Pi safely:

| Component | Primary | Backup | Recovery Time |
|-----------|---------|--------|---------------|
| **Boot Media** | USB SSD (NVMe/SATA) | Cloned USB SSD | 2 min (swap) |
| **Power** | AC Adapter | Power Bank (pass-through) | 0 min (seamless) |
| **Network** | WiFi 6 Router | Travel Router (spare) | 5 min (config) |
| **Compute** | Raspberry Pi 5 | Cold Spare Pi (in box) | 2 min (swap SSD) |

**Boot Media Policy**:
- ❌ **NO SD CARDS** - Too fragile for write-heavy SQLite operations
- ✓ USB SSD (NVMe via adapter, or SATA SSD)
- ✓ Industrial-grade SD only as last resort (SLC/MLC, not TLC/QLC)

**Backup Script** (Nightly cron):

```bash
#!/bin/bash
# /opt/xirs/backup.sh

BACKUP_MOUNT="/mnt/backup"
DB_PATH="/opt/xirs/data/xirs_hub.db"  # v2.0+
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Ensure backup drive mounted
mount /dev/sda1 $BACKUP_MOUNT 2>/dev/null

# Hot backup SQLite
sqlite3 $DB_PATH ".backup '${BACKUP_MOUNT}/xirs_hub_${TIMESTAMP}.db'"

# Keep last 7 backups
ls -t ${BACKUP_MOUNT}/xirs_hub_*.db | tail -n +8 | xargs rm -f

# Sync config files
rsync -av /opt/xirs/config/ ${BACKUP_MOUNT}/config/

# Unmount
umount $BACKUP_MOUNT
```

### 4.2 Time Drift Handling

Since nodes are offline, timestamps (`ts`) will drift.

| Strategy | Usage |
|----------|-------|
| **ts (Unix timestamp)** | Advisory display only ("約 14:30") |
| **seq_id (Monotonic)** | Ordering actions within a station |
| **packet_id (UUID)** | Global deduplication |

**Clock Sync**: When Runner returns to Hub WiFi range, phone syncs via NTP. Station iPads should sync when occasionally connected.

### 4.3 Network Topology

```
┌─────────────────────────────────────────────────────────────┐
│                    VENUE / DISASTER SITE                    │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ HUB ZONE (WiFi Coverage ~50m radius)                │   │
│  │                                                     │   │
│  │    ┌──────────┐      ┌──────────┐                  │   │
│  │    │   Pi 5   │──────│  Router  │                  │   │
│  │    │ (Server) │      │ (WiFi 6) │                  │   │
│  │    └──────────┘      └──────────┘                  │   │
│  │         │                  │                        │   │
│  │         │                  └───► Admin Laptops      │   │
│  │         │                  └───► Runner Phones      │   │
│  │         ▼                                           │   │
│  │    ┌──────────┐                                     │   │
│  │    │ Printer  │  (Manifest printing)                │   │
│  │    └──────────┘                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ════════════════════ NO CONNECTIVITY ═════════════════════│
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ STATION A (Park)                     OFFLINE        │   │
│  │                                                     │   │
│  │    ┌──────────┐                                     │   │
│  │    │  iPad    │  (Standalone, local cache only)     │   │
│  │    └──────────┘                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ STATION B (School)                   OFFLINE        │   │
│  │                                                     │   │
│  │    ┌──────────┐                                     │   │
│  │    │  iPad    │  (Standalone, local cache only)     │   │
│  │    └──────────┘                                     │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Implementation Roadmap

### Phase 1: Crypto & Protocol Library

**Deliverables**:
- `PacketBuilder` class (Python + JS)
- Ed25519 signing (manifests)
- NaCl SealedBox encryption (reports)
- HMAC-SHA256 integrity
- QR chunking logic (>800 bytes → multi-QR)

**Files**:
```
/shared/
├── crypto/
│   ├── signing.py      # Ed25519 sign/verify
│   ├── encryption.py   # SealedBox encrypt/decrypt
│   └── hmac.py         # HMAC-SHA256
├── protocol/
│   ├── manifest.py     # RESTOCK_MANIFEST builder
│   ├── report.py       # REPORT_PACKET builder
│   └── chunking.py     # QR payload chunking
└── js/
    ├── crypto.js       # Browser-compatible crypto
    └── protocol.js     # Packet handling
```

### Phase 2: Hub Backend (Logistics API)

**Endpoints**:

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/logistics/manifest` | Generate signed manifest |
| GET | `/api/logistics/manifest/{id}/print` | Printable HTML/PDF |
| POST | `/api/logistics/ingest` | Receive encrypted packet |
| GET | `/api/logistics/station/{id}/secret` | Provision station |
| GET | `/api/logistics/stations` | List all stations |
| GET | `/api/logistics/audit` | View reconciliation logs |

### Phase 3: PWA Station Mode

**Features**:
- Virtual Inventory (local SQLite/IndexedDB)
- Manifest Scanner (camera + Ed25519 verify)
- Dispense Logging (offline queue)
- Report Generator (chunked QR display)
- Manual Fallback (short code entry)

### Phase 4: PWA Runner Mode

**Features**:
- Blind Packet Storage (IndexedDB)
- Pickup Scanner (collect from Station)
- Delivery Display (show to Hub)
- Red Flare UI (vibration + visual alert)
- Multi-packet Queue (carry multiple deliveries)

---

## 6. Security Considerations

### 6.1 Threat Model

| Threat | Mitigation |
|--------|------------|
| Runner reads sensitive data | SealedBox encryption (Runner is blind) |
| Runner modifies packet | HMAC integrity check |
| Replay attack (duplicate delivery) | packet_id deduplication |
| Rogue manifest injection | Ed25519 signature verification |
| Station impersonation | station_secret HMAC |
| Physical manifest forgery | Short codes are claim-only; reconciled later |

### 6.2 Key Management

| Key | Holder | Purpose | Rotation |
|-----|--------|---------|----------|
| `hub_private_key` | Hub only | Sign manifests, decrypt reports | Yearly |
| `hub_public_key` | All stations | Verify manifests, encrypt reports | With private key |
| `station_secret` | Hub + Station | HMAC authentication | On re-pairing |

### 6.3 Audit Trail

All actions are logged with:
- `action_id` (unique)
- `station_id` (source)
- `operator_id` (who)
- `ts` (when)
- `type` (what)
- `payload` (details)

---

## 7. Appendix

### A. Comparison with Existing Satellite PWA

| Feature | Satellite PWA v1.4 | Distributed Logistics v1.8 |
|---------|-------------------|---------------------------|
| Connectivity | WiFi to Hub | Zero (Store-and-Forward) |
| Data Transport | HTTP API | QR Codes (Paper + Digital) |
| Security | JWT Token | Signatures + Encryption + HMAC |
| Coverage | Single venue | Multi-station campus |
| Offline Duration | Minutes | Days |
| Runner Role | N/A (direct connection) | Blind Carrier |

### B. Hardware Recommendations

| Component | Recommended | Budget Alternative |
|-----------|-------------|-------------------|
| Hub Server | Raspberry Pi 5 8GB | Raspberry Pi 4 4GB |
| Boot Media | Samsung T7 500GB SSD | Kingston A400 240GB SATA |
| Router | TP-Link AX1800 | GL.iNet GL-MT3000 |
| Printer | Brother HL-L2350DW | Any USB thermal printer |
| Station | iPad 10th Gen | iPad 9th Gen |
| Runner | Any Android/iPhone | - |

### C. Related Documents

- [SATELLITE_PWA_SPEC.md](./SATELLITE_PWA_SPEC.md) - Original Satellite PWA
- [IRS_SATELLITE_INTEROP.md](./IRS_SATELLITE_INTEROP.md) - CIRS/MIRS interoperability
- [xIRS_SECURE_EXCHANGE_SPEC_v2.md](./xIRS_SECURE_EXCHANGE_SPEC_v2.md) - Hub-to-Hub exchange

---

*Document Version: 1.8*
*Created: 2025-12-20*
*Status: Draft - Pending Implementation*
*Reviewed by: ChatGPT, Gemini*
