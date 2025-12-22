# xIRS Medication Flow Test Script
Version: 1.0 | Date: 2024-12-23

## Overview
This document provides a step-by-step test script for the medication inventory flow:
```
Hub (Admin) → Sub Hub (Pharmacy) → Doctor PWA / Nurse PWA
```

---

## Prerequisites

1. **Server Running**: `cd backend && python main.py` on port 8090
2. **Test Devices**:
   - Computer: Admin Console (`http://localhost:8090/admin/`)
   - Mobile 1: Doctor PWA (`http://<IP>:8090/doctor/`)
   - Mobile 2 (optional): Pharmacy PWA (`http://<IP>:8090/pharmacy/`)

---

## Phase 1: Hub Inventory Setup (Admin Console)

### Step 1.1: Access Admin Console
```
URL: http://localhost:8090/admin/
Login: admin001 / 1234
```

### Step 1.2: Import Medications from MIRS

> **Important**: CIRS does NOT create medications locally.
> Medications are IMPORTED from MIRS (Medical Inventory Resilience System).

#### Option A: Online Sync (if MIRS available)
1. Navigate to **物資管理** → **藥品**
2. Click **從 MIRS 同步**
3. System will fetch current medication list and stock status

#### Option B: Import from File (offline mode)
1. Obtain `mirs_export.json` from MIRS administrator
2. Navigate to **物資管理** → **藥品** → **匯入**
3. Select the export file
4. Review imported medications and confirm

#### Demo Mode: Seeded Data
In demo mode (Vercel), the following medications are pre-seeded:

| Name | Category | Quantity | Unit | Min Qty | Status |
|------|----------|----------|------|---------|--------|
| Acetaminophen 500mg | medication | 500 | TAB | 100 | OK |
| Ibuprofen 400mg | medication | 200 | TAB | 50 | OK |
| Amoxicillin 500mg | medication | 80 | CAP | 100 | LOW |
| Omeprazole 20mg | medication | 0 | CAP | 50 | OUT |
| Salbutamol Inhaler | medication | 20 | INH | 30 | LOW |

> Note: Omeprazole with 0 qty shows as "OUT" (缺貨)
> Amoxicillin and Salbutamol below min_qty show as "LOW" (低庫存)

---

## Phase 2: Sub Hub Distribution (Pharmacy)

> **Architecture Note**: Pharmacy Sub Hub receives its medication list from CIRS Hub,
> which itself imports from MIRS. The data flow is:
> `MIRS (master) → CIRS Hub (cache) → Pharmacy Sub Hub (allocated stock)`

### Step 2.1: Create Sub Hub Station
1. In Admin Console, go to **衛星站管理** or **Satellite**
2. Create a Pharmacy station:
   - Name: `藥局-01`
   - Type: `pharmacy`
   - Generate pairing code

### Step 2.2: Allocate Medications to Sub Hub
1. Go to **物資分配** or use the Logistics module
2. Select medications to distribute to `藥局-01`:
   - Acetaminophen: 100 TAB
   - Ibuprofen: 50 TAB
   - Amoxicillin: 30 CAP (LOW status)

### Step 2.3: Sync to Pharmacy PWA
1. Open Pharmacy PWA on mobile device
2. Pair with Hub using pairing code
3. Verify medications appear in stock list

---

## Phase 3: Doctor PWA Stock Status Sync

### Step 3.1: Configure Doctor PWA
1. Open Doctor PWA: `http://<IP>:8090/doctor/`
2. Click **設定** (gear icon in header)
3. Set prescriber credentials:
   - ID: `DOC-001`
   - Name: `測試醫師`
   - Generate or enter private key

### Step 3.2: Verify Stock Status
1. Click **藥品** tab in bottom navigation
2. View stock status grouped by:
   - **缺貨** (OUT): Red - Omeprazole
   - **低庫存** (LOW): Yellow - Amoxicillin, Salbutamol
   - **庫存充足** (OK): Green - Others

### Step 3.3: Refresh Stock Status
1. Click **更新** button
2. Check "更新時間" shows current time
3. If >30 min old, status shows "⚠ 資訊已過期"

---

## Phase 4: Prescription Flow Test

### Step 4.1: Register Patient (Admin Console)
1. Go to **人員管理** → **新增人員**
2. Create test patient:
   - Name: `測試病患`
   - Role: `public`
   - Triage: `GREEN`
3. Click **掛號** to create registration
4. Note the registration ID (e.g., `REG-20241223-001`)

### Step 4.2: Sync Waiting Room (Doctor PWA)
1. Go to **等候室** tab
2. Click **同步掛號**
3. Verify patient appears in waiting list

### Step 4.3: Claim & Prescribe
1. Click **看診** on the patient card
2. Patient moves to "我的病患" section
3. Click patient to enter prescription screen
4. Add medications:
   - Acetaminophen 500mg - 3 tab TID x 3 days
   - Ibuprofen 400mg - 1 tab PRN
5. Click **簽章並開立處方**
6. QR code should display

### Step 4.4: Verify Completed Patient
1. Go to **病患** tab
2. Check "今日看診完成" section
3. Click the completed patient
4. QR code should display again

---

## Phase 5: Dispense Flow Test (Pharmacy PWA)

### Step 5.1: Scan Prescription QR
1. Open Pharmacy PWA
2. Scan the prescription QR code from Doctor PWA
3. Prescription details should display

### Step 5.2: Dispense Medications
1. Verify medication list matches prescription
2. Click **配藥完成**
3. Inventory should decrement

### Step 5.3: Verify Stock Update
1. Return to Doctor PWA
2. Go to **藥品** tab
3. Click **更新**
4. Stock quantities should reflect dispensed amounts

---

## Expected Results

| Test Case | Expected Result |
|-----------|-----------------|
| Hub adds medication | Shows in inventory list |
| Stock status sync | Doctor PWA shows OK/LOW/OUT correctly |
| Stale stock warning | Shows after 30 min without refresh |
| Patient registration | Appears in Doctor PWA waiting room |
| Claim patient | Moves from waiting to "我的病患" |
| Sign prescription | QR code displays |
| Completed patient | Shows in 病患 tab, QR clickable |
| Dispense medication | Stock decrements |

---

## Troubleshooting

### QR Code Not Showing
- Check browser console for errors
- Ensure QRCode library is loaded
- Try hard refresh (Cmd+Shift+R)

### Camera Not Working
- Check browser permissions
- Use HTTPS or localhost
- Some browsers don't support camera over HTTP

### Stock Status Not Updating
- Check `/api/medications/status` endpoint
- Verify ttl_seconds hasn't expired
- Check network connectivity

---

## Demo Mode Notes

When running on Vercel (demo mode):
- Database resets on each deployment
- Use `/api/demo/reset` to reset demo data
- Stock data is simulated, not synced from real pharmacy

---

## API Endpoints Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/medications/status` | GET | Get stock status (OK/LOW/OUT) |
| `/api/medications/list` | GET | Get full medication list |
| `/api/registrations/waiting/list` | GET | Get waiting room patients |
| `/api/registrations/{id}/claim` | POST | Claim patient for doctor |

