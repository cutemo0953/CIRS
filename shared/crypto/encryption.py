"""
NaCl SealedBox Encryption Module for xIRS v1.8

Used for encrypting REPORT_PACKET from Station to Hub.
Implements "Blind Carrier" pattern - Runners cannot read packet contents.

SealedBox provides anonymous public-key encryption:
- Station encrypts with Hub's public key
- Only Hub can decrypt with private key
- No authentication of sender (use HMAC for that)
"""

import base64
import json
import zlib
from typing import Tuple, Union, Optional
from nacl.public import PrivateKey, PublicKey, SealedBox as NaClSealedBox
from nacl.encoding import Base64Encoder


def generate_encryption_keypair() -> Tuple[str, str]:
    """
    Generate a new X25519 keypair for encryption.

    Returns:
        Tuple[str, str]: (private_key_b64, public_key_b64)
    """
    private_key = PrivateKey.generate()
    public_key = private_key.public_key

    private_b64 = base64.b64encode(bytes(private_key)).decode('utf-8')
    public_b64 = base64.b64encode(bytes(public_key)).decode('utf-8')

    return private_b64, public_b64


class SealedBox:
    """
    NaCl SealedBox wrapper for xIRS.

    Encryption (Station side):
        - Use Hub's public key only
        - Output is anonymous - Hub doesn't know sender from ciphertext alone

    Decryption (Hub side):
        - Use Hub's private key
    """

    def __init__(self, public_key_b64: Optional[str] = None,
                 private_key_b64: Optional[str] = None):
        """
        Initialize SealedBox.

        For encryption (Station): provide public_key_b64 only
        For decryption (Hub): provide private_key_b64

        Args:
            public_key_b64: Hub's public key (for encryption)
            private_key_b64: Hub's private key (for decryption)
        """
        self._public_key = None
        self._private_key = None
        self._seal_box = None
        self._unseal_box = None

        if public_key_b64:
            public_bytes = base64.b64decode(public_key_b64)
            self._public_key = PublicKey(public_bytes)
            self._seal_box = NaClSealedBox(self._public_key)

        if private_key_b64:
            private_bytes = base64.b64decode(private_key_b64)
            self._private_key = PrivateKey(private_bytes)
            self._unseal_box = NaClSealedBox(self._private_key)
            # Also derive public key
            if not self._public_key:
                self._public_key = self._private_key.public_key
                self._seal_box = NaClSealedBox(self._public_key)

    @property
    def public_key_b64(self) -> Optional[str]:
        """Get public key as Base64."""
        if self._public_key:
            return base64.b64encode(bytes(self._public_key)).decode('utf-8')
        return None

    def encrypt(self, plaintext: Union[str, bytes, dict],
                compress: bool = True) -> str:
        """
        Encrypt data using Hub's public key.

        Args:
            plaintext: Data to encrypt (str, bytes, or dict -> JSON)
            compress: Whether to zlib compress before encryption

        Returns:
            str: Base64-encoded ciphertext
        """
        if self._seal_box is None:
            raise ValueError("No public key provided for encryption")

        # Serialize
        if isinstance(plaintext, dict):
            plaintext = json.dumps(plaintext, separators=(',', ':'))
        if isinstance(plaintext, str):
            plaintext = plaintext.encode('utf-8')

        # Compress (optional, good for JSON)
        if compress:
            plaintext = zlib.compress(plaintext, level=6)

        # Encrypt
        ciphertext = self._seal_box.encrypt(plaintext)

        # Encode
        return base64.b64encode(ciphertext).decode('utf-8')

    def decrypt(self, ciphertext_b64: str,
                decompress: bool = True) -> bytes:
        """
        Decrypt data using Hub's private key.

        Args:
            ciphertext_b64: Base64-encoded ciphertext
            decompress: Whether to zlib decompress after decryption

        Returns:
            bytes: Decrypted plaintext
        """
        if self._unseal_box is None:
            raise ValueError("No private key provided for decryption")

        # Decode
        ciphertext = base64.b64decode(ciphertext_b64)

        # Decrypt
        plaintext = self._unseal_box.decrypt(ciphertext)

        # Decompress (optional)
        if decompress:
            try:
                plaintext = zlib.decompress(plaintext)
            except zlib.error:
                # Not compressed, return as-is
                pass

        return plaintext

    def decrypt_json(self, ciphertext_b64: str) -> dict:
        """
        Decrypt and parse as JSON.

        Args:
            ciphertext_b64: Base64-encoded ciphertext

        Returns:
            dict: Parsed JSON object
        """
        plaintext = self.decrypt(ciphertext_b64)
        return json.loads(plaintext.decode('utf-8'))

    def encrypt_report(self, report: dict) -> dict:
        """
        Encrypt a REPORT_PACKET for transport.

        Args:
            report: Report dict to encrypt

        Returns:
            dict: Envelope with encrypted payload
        """
        ciphertext = self.encrypt(report, compress=True)

        return {
            "type": "ENCRYPTED_REPORT",
            "version": "1.8",
            "payload": ciphertext,
            "compressed": True
        }

    def decrypt_report(self, envelope: dict) -> dict:
        """
        Decrypt a REPORT_PACKET envelope.

        Args:
            envelope: Encrypted envelope

        Returns:
            dict: Decrypted report
        """
        if envelope.get('type') != 'ENCRYPTED_REPORT':
            raise ValueError("Invalid envelope type")

        ciphertext = envelope['payload']
        decompress = envelope.get('compressed', True)

        plaintext = self.decrypt(ciphertext, decompress=decompress)
        return json.loads(plaintext.decode('utf-8'))


# Convenience functions
def encrypt_for_hub(hub_public_key_b64: str, data: Union[str, bytes, dict]) -> str:
    """Quick encrypt for Hub without creating SealedBox object."""
    box = SealedBox(public_key_b64=hub_public_key_b64)
    return box.encrypt(data)


def decrypt_at_hub(hub_private_key_b64: str, ciphertext_b64: str) -> bytes:
    """Quick decrypt at Hub without creating SealedBox object."""
    box = SealedBox(private_key_b64=hub_private_key_b64)
    return box.decrypt(ciphertext_b64)


if __name__ == '__main__':
    # Test
    print("=== SealedBox Encryption Test ===")

    # Generate Hub keypair
    priv, pub = generate_encryption_keypair()
    print(f"Hub Private Key: {priv[:20]}...")
    print(f"Hub Public Key:  {pub[:20]}...")

    # Station encrypts a report
    station_box = SealedBox(public_key_b64=pub)

    report = {
        "type": "REPORT_PACKET",
        "packet_id": "PKT-TEST-001",
        "station_id": "STATION-PARK",
        "actions": [
            {"type": "DISPENSE", "item": "WATER", "qty": 10}
        ]
    }

    print(f"\nOriginal Report:")
    print(json.dumps(report, indent=2))

    encrypted = station_box.encrypt_report(report)
    print(f"\nEncrypted Envelope:")
    print(f"  Type: {encrypted['type']}")
    print(f"  Payload: {encrypted['payload'][:50]}...")
    print(f"  Size: {len(encrypted['payload'])} bytes")

    # Hub decrypts
    hub_box = SealedBox(private_key_b64=priv)
    decrypted = hub_box.decrypt_report(encrypted)

    print(f"\nDecrypted Report:")
    print(json.dumps(decrypted, indent=2))

    print(f"\nRoundtrip Success: {report == decrypted}")
