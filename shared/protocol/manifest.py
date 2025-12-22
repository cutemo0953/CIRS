"""
Manifest Builder Module for xIRS v1.8

Builds RESTOCK_MANIFEST packets for Hub → Station communication.
Manifests are signed with Ed25519 for authenticity.

Usage:
    builder = ManifestBuilder(hub_private_key)
    manifest = builder.create_manifest(
        station_id="STATION-PARK",
        items=[{"code": "WATER", "qty": 100, "unit": "bottle"}]
    )
    qr_chunks = builder.to_qr_chunks(manifest)
"""

import json
import secrets
import time
import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto.signing import Ed25519Signer
from protocol.chunking import QRChunker


@dataclass
class ManifestItem:
    """Single item in a manifest."""
    code: str
    qty: int
    unit: str = "unit"


@dataclass
class RestockManifest:
    """RESTOCK_MANIFEST packet structure."""
    type: str = "RESTOCK_MANIFEST"
    version: str = "1.8"
    manifest_id: str = ""
    short_code: str = ""
    station_id: str = ""
    items: List[Dict[str, Any]] = None
    ts: int = 0
    nonce: str = ""
    signature: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "version": self.version,
            "manifest_id": self.manifest_id,
            "short_code": self.short_code,
            "station_id": self.station_id,
            "items": self.items or [],
            "ts": self.ts,
            "nonce": self.nonce,
            "signature": self.signature
        }


class ManifestBuilder:
    """
    Builds and signs RESTOCK_MANIFEST packets.
    """

    def __init__(self, hub_private_key_b64: str):
        """
        Initialize builder with Hub's signing key.

        Args:
            hub_private_key_b64: Base64-encoded Ed25519 private key
        """
        self._signer = Ed25519Signer(hub_private_key_b64)
        self._chunker = QRChunker()

    @property
    def public_key_b64(self) -> str:
        """Get Hub's public key for distribution to Stations."""
        return self._signer.public_key_b64

    def create_manifest(
        self,
        station_id: str,
        items: List[Dict[str, Any]],
        manifest_id: Optional[str] = None
    ) -> RestockManifest:
        """
        Create a signed manifest.

        Args:
            station_id: Target station ID
            items: List of items [{code, qty, unit}, ...]
            manifest_id: Optional custom ID (auto-generated if not provided)

        Returns:
            RestockManifest: Signed manifest ready for printing
        """
        # Generate IDs
        if manifest_id is None:
            timestamp = time.strftime("%Y%m%d")
            manifest_id = f"M-{timestamp}-{uuid.uuid4().hex[:6].upper()}"

        short_code = self._generate_short_code()
        nonce = secrets.token_hex(8)
        ts = int(time.time())

        # Build manifest (without signature)
        manifest_data = {
            "type": "RESTOCK_MANIFEST",
            "version": "1.8",
            "manifest_id": manifest_id,
            "short_code": short_code,
            "station_id": station_id,
            "items": items,
            "ts": ts,
            "nonce": nonce
        }

        # Sign
        signed = self._signer.sign_manifest(manifest_data)

        return RestockManifest(
            manifest_id=manifest_id,
            short_code=short_code,
            station_id=station_id,
            items=items,
            ts=ts,
            nonce=nonce,
            signature=signed['signature']
        )

    def _generate_short_code(self) -> str:
        """Generate a 4-digit fallback code."""
        return str(secrets.randbelow(9000) + 1000)

    def to_qr_chunks(self, manifest: RestockManifest) -> List[str]:
        """
        Convert manifest to QR code chunks.

        Args:
            manifest: Signed manifest

        Returns:
            List[str]: QR chunk strings
        """
        return self._chunker.chunk(manifest.to_dict())

    def to_json(self, manifest: RestockManifest) -> str:
        """Convert manifest to JSON string."""
        return json.dumps(manifest.to_dict(), indent=2)

    def to_printable_html(self, manifest: RestockManifest) -> str:
        """
        Generate printable HTML for the manifest.

        Args:
            manifest: Signed manifest

        Returns:
            str: HTML string for printing
        """
        items_html = ""
        for item in manifest.items:
            items_html += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #ddd;">
                    {item.get('code', 'N/A')}
                </td>
                <td style="padding: 8px; border-bottom: 1px solid #ddd; text-align: right;">
                    {item.get('qty', 0)} {item.get('unit', '')}
                </td>
            </tr>
            """

        qr_data = json.dumps(manifest.to_dict(), separators=(',', ':'))

        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>CIRS Resupply Manifest</title>
    <style>
        body {{ font-family: Arial, sans-serif; max-width: 400px; margin: 20px auto; }}
        .header {{ border: 2px solid #333; padding: 15px; text-align: center; }}
        .title {{ font-size: 18px; font-weight: bold; margin-bottom: 10px; }}
        .info {{ margin: 15px 0; }}
        .info-row {{ display: flex; justify-content: space-between; margin: 5px 0; }}
        .items {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
        .qr-section {{ text-align: center; margin: 20px 0; }}
        .short-code {{ font-size: 24px; font-weight: bold; margin: 10px 0; }}
        .signature-line {{ border-top: 1px solid #333; margin-top: 30px; padding-top: 10px; }}
    </style>
</head>
<body>
    <div class="header">
        <div class="title">CIRS RESUPPLY MANIFEST</div>
        <div>{manifest.manifest_id}</div>
    </div>

    <div class="info">
        <div class="info-row">
            <span>TO:</span>
            <span><strong>{manifest.station_id}</strong></span>
        </div>
        <div class="info-row">
            <span>DATE:</span>
            <span>{time.strftime('%Y-%m-%d %H:%M', time.localtime(manifest.ts))}</span>
        </div>
    </div>

    <table class="items">
        <thead>
            <tr>
                <th style="text-align: left; padding: 8px; border-bottom: 2px solid #333;">Item</th>
                <th style="text-align: right; padding: 8px; border-bottom: 2px solid #333;">Quantity</th>
            </tr>
        </thead>
        <tbody>
            {items_html}
        </tbody>
    </table>

    <div class="qr-section">
        <div id="qr-placeholder" style="width: 200px; height: 200px; border: 1px dashed #ccc; margin: 0 auto; display: flex; align-items: center; justify-content: center;">
            [QR Code]
        </div>
        <div class="short-code">CODE: {manifest.short_code}</div>
        <div style="font-size: 12px; color: #666;">(Use code if QR scan fails)</div>
    </div>

    <div class="signature-line">
        <div>Received by: ________________________</div>
        <div style="margin-top: 10px;">Date/Time: ________________________</div>
    </div>

    <!-- QR Data for JS generation -->
    <script>
        var qrData = {json.dumps(qr_data)};
        // Use qrcode.js or similar to generate QR from qrData
    </script>
</body>
</html>
        """


if __name__ == '__main__':
    from crypto.signing import generate_keypair

    print("=== ManifestBuilder Test ===")

    # Generate Hub keypair
    priv, pub = generate_keypair()
    print(f"Hub Public Key: {pub[:30]}...")

    # Create builder
    builder = ManifestBuilder(priv)

    # Create manifest
    manifest = builder.create_manifest(
        station_id="STATION-PARK",
        items=[
            {"code": "WATER-500ML", "qty": 100, "unit": "bottle"},
            {"code": "RICE-1KG", "qty": 50, "unit": "bag"},
            {"code": "BLANKET", "qty": 20, "unit": "piece"}
        ]
    )

    print(f"\nManifest ID: {manifest.manifest_id}")
    print(f"Short Code: {manifest.short_code}")
    print(f"Station: {manifest.station_id}")
    print(f"Items: {len(manifest.items)}")
    print(f"Signature: {manifest.signature[:30]}...")

    # Get QR chunks
    chunks = builder.to_qr_chunks(manifest)
    print(f"\nQR Chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i+1}: {len(chunk)} bytes")

    # Generate JSON
    print(f"\nJSON:\n{builder.to_json(manifest)}")
