"""
Report Builder Module for xIRS v1.8

Builds REPORT_PACKET for Station → Hub communication.
Reports are encrypted with SealedBox and authenticated with HMAC.

Flow:
1. Station builds report with actions (dispense, receive, register)
2. Add HMAC for authentication
3. Encrypt with Hub's public key (Blind Carrier pattern)
4. Chunk for QR transmission

Usage:
    builder = ReportBuilder(
        station_id="STATION-PARK",
        station_secret=station_secret_b64,
        hub_public_key=hub_pub_b64
    )
    report = builder.create_report(actions=[...])
    qr_chunks = builder.to_encrypted_chunks(report)
"""

import json
import secrets
import time
import uuid
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict, field

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from crypto.hmac import compute_hmac, add_hmac_to_report
from crypto.encryption import SealedBox
from protocol.chunking import QRChunker


@dataclass
class ActionRecord:
    """Single action in a report."""
    type: str  # DISPENSE, RECEIVE, REGISTER
    item_code: str = ""
    qty: int = 0
    unit: str = "unit"
    person_id: str = ""
    ts: int = 0

    def __post_init__(self):
        if self.ts == 0:
            self.ts = int(time.time())

    def to_dict(self) -> dict:
        """Convert to dictionary, omitting empty fields."""
        result = {"type": self.type, "ts": self.ts}
        if self.item_code:
            result["item_code"] = self.item_code
        if self.qty:
            result["qty"] = self.qty
            result["unit"] = self.unit
        if self.person_id:
            result["person_id"] = self.person_id
        return result


@dataclass
class ReportPacket:
    """REPORT_PACKET structure."""
    type: str = "REPORT_PACKET"
    version: str = "1.8"
    packet_id: str = ""
    station_id: str = ""
    manifest_id: str = ""
    seq_id: int = 0
    actions: List[Dict[str, Any]] = field(default_factory=list)
    ts: int = 0
    nonce: str = ""
    hmac: str = ""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "type": self.type,
            "version": self.version,
            "packet_id": self.packet_id,
            "station_id": self.station_id,
            "manifest_id": self.manifest_id,
            "seq_id": self.seq_id,
            "actions": self.actions,
            "ts": self.ts,
            "nonce": self.nonce,
            "hmac": self.hmac
        }

    def to_signable_dict(self) -> dict:
        """Convert to dictionary for HMAC computation (without hmac field)."""
        d = self.to_dict()
        del d["hmac"]
        return d


class ReportBuilder:
    """
    Builds, signs, and encrypts REPORT_PACKETs.
    """

    def __init__(self, station_id: str, station_secret_b64: str,
                 hub_public_key_b64: str):
        """
        Initialize builder with Station credentials.

        Args:
            station_id: This station's ID
            station_secret_b64: HMAC secret shared with Hub
            hub_public_key_b64: Hub's public key for encryption
        """
        self._station_id = station_id
        self._secret = station_secret_b64
        self._sealed_box = SealedBox(public_key_b64=hub_public_key_b64)
        self._chunker = QRChunker()
        self._seq_counter = 0

    def create_report(
        self,
        actions: List[Dict[str, Any]],
        manifest_id: str = "",
        packet_id: Optional[str] = None
    ) -> ReportPacket:
        """
        Create an authenticated report.

        Args:
            actions: List of action dicts [{type, item_code, qty, ...}, ...]
            manifest_id: Related manifest ID (if responding to manifest)
            packet_id: Optional custom ID (auto-generated if not provided)

        Returns:
            ReportPacket: Authenticated report ready for encryption
        """
        # Generate IDs
        if packet_id is None:
            timestamp = time.strftime("%Y%m%d%H%M%S")
            packet_id = f"RPT-{self._station_id}-{timestamp}-{uuid.uuid4().hex[:4].upper()}"

        self._seq_counter += 1
        nonce = secrets.token_hex(8)
        ts = int(time.time())

        # Build report (without HMAC)
        report = ReportPacket(
            packet_id=packet_id,
            station_id=self._station_id,
            manifest_id=manifest_id,
            seq_id=self._seq_counter,
            actions=actions,
            ts=ts,
            nonce=nonce
        )

        # Compute HMAC
        signable = report.to_signable_dict()
        hmac_value = compute_hmac(self._secret, signable)
        report.hmac = hmac_value

        return report

    def encrypt_report(self, report: ReportPacket) -> dict:
        """
        Encrypt report for transport (Blind Carrier pattern).

        Args:
            report: Authenticated report

        Returns:
            dict: Encrypted envelope
        """
        return self._sealed_box.encrypt_report(report.to_dict())

    def to_encrypted_chunks(self, report: ReportPacket) -> List[str]:
        """
        Encrypt and chunk report for QR transmission.

        Args:
            report: Authenticated report

        Returns:
            List[str]: QR chunk strings
        """
        encrypted = self.encrypt_report(report)
        return self._chunker.chunk(encrypted)

    def to_json(self, report: ReportPacket, encrypted: bool = False) -> str:
        """Convert report to JSON string."""
        if encrypted:
            return json.dumps(self.encrypt_report(report), indent=2)
        return json.dumps(report.to_dict(), indent=2)

    # Convenience methods for common action types

    def add_dispense_action(
        self,
        actions: List[Dict],
        item_code: str,
        qty: int,
        unit: str = "unit",
        person_id: str = ""
    ) -> List[Dict]:
        """Add a DISPENSE action to action list."""
        action = ActionRecord(
            type="DISPENSE",
            item_code=item_code,
            qty=qty,
            unit=unit,
            person_id=person_id
        )
        actions.append(action.to_dict())
        return actions

    def add_receive_action(
        self,
        actions: List[Dict],
        item_code: str,
        qty: int,
        unit: str = "unit",
        manifest_id: str = ""
    ) -> List[Dict]:
        """Add a RECEIVE action to action list."""
        action = ActionRecord(
            type="RECEIVE",
            item_code=item_code,
            qty=qty,
            unit=unit
        )
        d = action.to_dict()
        if manifest_id:
            d["manifest_id"] = manifest_id
        actions.append(d)
        return actions

    def add_register_action(
        self,
        actions: List[Dict],
        person_id: str,
        metadata: Optional[Dict] = None
    ) -> List[Dict]:
        """Add a REGISTER action to action list."""
        action = ActionRecord(
            type="REGISTER",
            person_id=person_id
        )
        d = action.to_dict()
        if metadata:
            d["metadata"] = metadata
        actions.append(d)
        return actions

    def create_manifest_ack(self, manifest_id: str, items_received: List[Dict]) -> ReportPacket:
        """
        Create acknowledgement report for received manifest.

        Args:
            manifest_id: ID of received manifest
            items_received: List of items actually received

        Returns:
            ReportPacket: ACK report
        """
        actions = []
        for item in items_received:
            self.add_receive_action(
                actions,
                item_code=item.get("code", ""),
                qty=item.get("qty", 0),
                unit=item.get("unit", "unit"),
                manifest_id=manifest_id
            )

        return self.create_report(
            actions=actions,
            manifest_id=manifest_id
        )


class ReportDecryptor:
    """
    Hub-side decryption and verification of reports.
    """

    def __init__(self, hub_private_key_b64: str):
        """
        Initialize decryptor with Hub's private key.

        Args:
            hub_private_key_b64: Hub's private key for decryption
        """
        self._sealed_box = SealedBox(private_key_b64=hub_private_key_b64)
        self._station_secrets = {}  # station_id -> secret_b64

    def register_station(self, station_id: str, secret_b64: str):
        """Register a station's HMAC secret."""
        self._station_secrets[station_id] = secret_b64

    def decrypt_envelope(self, envelope: dict) -> dict:
        """
        Decrypt an encrypted report envelope.

        Args:
            envelope: Encrypted envelope from Station

        Returns:
            dict: Decrypted report (not yet verified)
        """
        return self._sealed_box.decrypt_report(envelope)

    def verify_report(self, report: dict) -> bool:
        """
        Verify report HMAC.

        Args:
            report: Decrypted report dict

        Returns:
            bool: True if HMAC is valid
        """
        station_id = report.get("station_id")
        if not station_id:
            return False

        secret = self._station_secrets.get(station_id)
        if not secret:
            return False

        # Extract HMAC
        hmac_value = report.get("hmac")
        if not hmac_value:
            return False

        # Compute expected HMAC
        signable = {k: v for k, v in report.items() if k != "hmac"}
        expected = compute_hmac(secret, signable)

        # Constant-time comparison
        import hmac as hmac_module
        return hmac_module.compare_digest(expected, hmac_value)

    def decrypt_and_verify(self, envelope: dict) -> Optional[dict]:
        """
        Decrypt and verify a report in one step.

        Args:
            envelope: Encrypted envelope

        Returns:
            dict: Verified report, or None if verification fails
        """
        report = self.decrypt_envelope(envelope)
        if self.verify_report(report):
            return report
        return None


if __name__ == '__main__':
    from crypto.signing import generate_keypair
    from crypto.encryption import generate_encryption_keypair
    from crypto.hmac import generate_station_secret

    print("=== ReportBuilder Test ===")

    # Generate keys
    enc_priv, enc_pub = generate_encryption_keypair()
    station_secret = generate_station_secret()

    print(f"Hub Encryption Public Key: {enc_pub[:30]}...")
    print(f"Station Secret: {station_secret[:30]}...")

    # Create builder
    builder = ReportBuilder(
        station_id="STATION-PARK",
        station_secret_b64=station_secret,
        hub_public_key_b64=enc_pub
    )

    # Build actions
    actions = []
    builder.add_dispense_action(actions, "WATER-500ML", 10, "bottle", "P0001")
    builder.add_dispense_action(actions, "RICE-1KG", 5, "bag", "P0001")
    builder.add_register_action(actions, "P0002", {"name_hash": "abc123"})

    # Create report
    report = builder.create_report(actions)

    print(f"\nReport ID: {report.packet_id}")
    print(f"Station: {report.station_id}")
    print(f"Seq ID: {report.seq_id}")
    print(f"Actions: {len(report.actions)}")
    print(f"HMAC: {report.hmac[:30]}...")

    # Encrypt
    encrypted = builder.encrypt_report(report)
    print(f"\nEncrypted Type: {encrypted['type']}")
    print(f"Payload Size: {len(encrypted['payload'])} bytes")

    # Get QR chunks
    chunks = builder.to_encrypted_chunks(report)
    print(f"\nQR Chunks: {len(chunks)}")
    for i, chunk in enumerate(chunks):
        print(f"  Chunk {i+1}: {len(chunk)} bytes")

    # === Hub-side decryption ===
    print("\n=== Hub Decryption Test ===")

    decryptor = ReportDecryptor(enc_priv)
    decryptor.register_station("STATION-PARK", station_secret)

    # Decrypt and verify
    decrypted = decryptor.decrypt_and_verify(encrypted)

    if decrypted:
        print("Verification: SUCCESS")
        print(f"Packet ID: {decrypted['packet_id']}")
        print(f"Station: {decrypted['station_id']}")
        print(f"Actions: {len(decrypted['actions'])}")
    else:
        print("Verification: FAILED")

    # Test manifest ACK
    print("\n=== Manifest ACK Test ===")
    ack = builder.create_manifest_ack(
        manifest_id="M-20250101-ABC123",
        items_received=[
            {"code": "WATER-500ML", "qty": 100, "unit": "bottle"},
            {"code": "RICE-1KG", "qty": 50, "unit": "bag"}
        ]
    )
    print(f"ACK Packet ID: {ack.packet_id}")
    print(f"ACK Manifest ID: {ack.manifest_id}")
    print(f"ACK Actions: {len(ack.actions)}")
