# QR Code Issues - Development Specification

Version: 1.0 | Date: 2024-12-23

---

## Problem Summary

Doctor PWA has two QR code related issues:
1. **QR Code Rendering**: Generated QR codes not displaying (blank canvas)
2. **QR Code Scanning**: Camera scanner not working (especially on iOS)

---

## Issue 1: QR Code Not Rendering

### Symptoms
- After signing a prescription, the QR display screen shows an empty box
- Canvas element exists but no QR image is rendered

### Current Implementation
```javascript
// Uses qrcode library (https://github.com/soldair/node-qrcode)
QRCode.toCanvas(canvas, qrData, { width: 250, margin: 2 }, callback);
```

### Potential Causes

| Cause | Likelihood | Notes |
|-------|------------|-------|
| QRCode library not loaded | Medium | CDN may be blocked or slow |
| Canvas not ready when render called | High | Alpine.js DOM timing issue |
| qrCodes array is empty/invalid | Medium | Data generation issue |
| Canvas context issue on iOS Safari | Medium | WebKit quirks |

### Debugging Steps

1. **Check console for errors**:
   ```
   [Doctor] renderQR called, qrCodes: X, currentIndex: 0
   [Doctor] Rendering QR data (first 50 chars): XIR1|1/1|...
   [Doctor] QR rendered successfully
   ```

2. **Verify QRCode library loaded**:
   ```javascript
   typeof QRCode !== 'undefined'  // Should be true
   ```

3. **Check qrCodes data**:
   ```javascript
   console.log(this.qrCodes);  // Should be array of strings like "XIR1|1/1|base64..."
   ```

### Proposed Solutions

#### Solution A: Use Image Instead of Canvas
```javascript
// Generate QR as data URL, use <img> instead of <canvas>
QRCode.toDataURL(qrData, { width: 250 }, (err, url) => {
    document.getElementById('qr-image').src = url;
});
```
**Pros**: Better cross-browser compatibility
**Cons**: Slightly larger DOM

#### Solution B: Add Fallback with Retry
```javascript
renderQR() {
    const maxRetries = 5;
    let retries = 0;

    const attemptRender = () => {
        const canvas = document.getElementById('qr-canvas');
        if (!canvas && retries < maxRetries) {
            retries++;
            setTimeout(attemptRender, 200);
            return;
        }
        // ... render logic
    };

    attemptRender();
}
```

#### Solution C: Pre-render QR Codes
Generate QR codes immediately after Rx creation and store as data URLs:
```javascript
// In signAndCreateRx
const qrDataUrls = await Promise.all(
    qrCodes.map(code => QRCode.toDataURL(code, { width: 250 }))
);
this.qrDataUrls = qrDataUrls;
```

---

## Issue 2: QR Code Scanner Not Working

### Symptoms
- Camera doesn't start
- Error: "camera streaming not supported by the browser"
- Error: "undefined" when trying to scan

### iOS Safari Limitations

| Limitation | Impact | Workaround |
|------------|--------|------------|
| **HTTPS required** | Camera API blocked on HTTP | Use localhost or deploy with SSL |
| **getUserMedia restrictions** | Stricter permission model | Must be triggered by user gesture |
| **No background camera** | Camera stops when tab inactive | Show warning to user |
| **Aspect ratio issues** | Video may be distorted | Use `facingMode: 'environment'` |

### Current Implementation
```javascript
// Uses html5-qrcode library
const scanner = new Html5Qrcode("scanner-container");
scanner.start(
    { facingMode: "environment" },
    { fps: 10, qrbox: 250 },
    onScanSuccess
);
```

### Browser Support Matrix

| Browser | HTTPS | HTTP localhost | HTTP LAN |
|---------|-------|----------------|----------|
| Chrome Desktop | ✅ | ✅ | ❌ |
| Chrome Android | ✅ | ✅ | ❌ |
| Safari Desktop | ✅ | ✅ | ❌ |
| Safari iOS | ✅ | ✅ | ❌ |
| Firefox | ✅ | ✅ | ❌ |

### Proposed Solutions

#### Solution A: HTTPS Deployment
Deploy to Vercel/Netlify with automatic HTTPS.

```
https://cirs-demo.vercel.app/doctor/
```

#### Solution B: Manual QR Input Fallback
When camera fails, allow manual text input:

```html
<div x-show="cameraFailed">
    <p>無法啟動相機，請手動輸入處方編號：</p>
    <input type="text" x-model="manualRxId" placeholder="RX-DOC001-20241223-0001">
    <button @click="lookupRx(manualRxId)">查詢</button>
</div>
```

#### Solution C: Native Camera + File Upload
Use native file input as fallback:

```html
<input type="file" accept="image/*" capture="environment"
       @change="decodeQRFromImage($event)">
```

```javascript
async decodeQRFromImage(event) {
    const file = event.target.files[0];
    const imageData = await this.readFileAsDataURL(file);
    const result = await Html5Qrcode.scanFile(file, true);
    this.handleScannedData(result);
}
```

#### Solution D: Deep Link with URL Scheme
For cross-device communication without camera:

```
cirs://rx/RX-DOC001-20241223-0001
```

Pharmacy app registers URL scheme and receives Rx ID directly.

---

## Recommended Implementation Plan

### Phase 1: Quick Fixes (Immediate)
1. Switch QR rendering from canvas to image (Solution A)
2. Add manual Rx ID input fallback (Solution B)
3. Improve error messages with specific guidance

### Phase 2: Enhanced UX (Short-term)
1. Add native camera file input fallback (Solution C)
2. Pre-render QR codes as data URLs (Solution C from Issue 1)
3. Add "Copy Rx ID" button for manual sharing

### Phase 3: Production Ready (Medium-term)
1. Deploy with HTTPS
2. Implement deep links for app-to-app communication
3. Add offline QR scanning with stored certificates

---

## Code Changes Required

### File: `frontend/doctor/index.html`

```javascript
// Replace canvas-based QR with image-based
renderQR() {
    if (!this.qrCodes?.length) return;

    const qrData = this.qrCodes[this.currentQRIndex];
    const img = document.getElementById('qr-image');

    QRCode.toDataURL(qrData, {
        width: 250,
        margin: 2,
        errorCorrectionLevel: 'M'
    }, (err, url) => {
        if (err) {
            console.error('[Doctor] QR generation error:', err);
            return;
        }
        img.src = url;
    });
}
```

```html
<!-- Replace canvas with img -->
<img id="qr-image" class="mx-auto" width="250" height="250"
     alt="Prescription QR Code">
```

### File: `frontend/pharmacy/index.html`

```javascript
// Add fallback for camera failure
async startScanner() {
    try {
        await this.scanner.start({ facingMode: 'environment' }, ...);
    } catch (err) {
        console.error('[Pharmacy] Camera error:', err);
        this.cameraFailed = true;
        this.cameraError = this.getCameraErrorMessage(err);
    }
}

getCameraErrorMessage(err) {
    if (err.name === 'NotAllowedError') {
        return '請允許相機權限';
    }
    if (err.name === 'NotFoundError') {
        return '找不到相機裝置';
    }
    if (err.message?.includes('SSL') || err.message?.includes('secure')) {
        return '需要 HTTPS 連線才能使用相機';
    }
    return '無法啟動相機，請使用手動輸入';
}
```

---

## Testing Checklist

- [ ] QR renders on Chrome Desktop
- [ ] QR renders on Safari Desktop
- [ ] QR renders on Chrome Android
- [ ] QR renders on Safari iOS
- [ ] Scanner works on Chrome Desktop (localhost)
- [ ] Scanner works on Safari iOS (HTTPS)
- [ ] Manual Rx input fallback works
- [ ] File upload QR decode works
- [ ] Error messages are user-friendly

---

## References

- [html5-qrcode library](https://github.com/mebjas/html5-qrcode)
- [qrcode library](https://github.com/soldair/node-qrcode)
- [MDN: MediaDevices.getUserMedia()](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)
- [WebKit Blog: Camera Access](https://webkit.org/blog/6784/new-video-policies-for-ios/)
