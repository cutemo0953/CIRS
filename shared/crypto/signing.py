"""
Ed25519 Digital Signature Module for xIRS v1.8

Used for signing RESTOCK_MANIFEST packets from Hub to Station.
Stations verify signatures to ensure manifests are authentic.
"""

import base64
import json
import os
from typing import Tuple, Union, Optional
from nacl.signing import SigningKey, VerifyKey
from nacl.encoding import Base64Encoder
from nacl.exceptions import BadSignatureError


def generate_keypair() -> Tuple[str, str]:
    """
    Generate a new Ed25519 keypair.

    Returns:
        Tuple[str, str]: (private_key_b64, public_key_b64)
    """
    signing_key = SigningKey.generate()
    verify_key = signing_key.verify_key

    private_b64 = base64.b64encode(bytes(signing_key)).decode('utf-8')
    public_b64 = base64.b64encode(bytes(verify_key)).decode('utf-8')

    return private_b64, public_b64


class Ed25519Signer:
    """
    Signs payloads using Ed25519.
    Used by Hub to sign manifests.
    """

    def __init__(self, private_key_b64: str):
        """
        Initialize signer with private key.

        Args:
            private_key_b64: Base64-encoded 32-byte Ed25519 private key
        """
        private_bytes = base64.b64decode(private_key_b64)
        self._signing_key = SigningKey(private_bytes)
        self._verify_key = self._signing_key.verify_key

    @property
    def public_key_b64(self) -> str:
        """Get the corresponding public key as Base64."""
        return base64.b64encode(bytes(self._verify_key)).decode('utf-8')

    def sign(self, payload: Union[str, bytes, dict]) -> str:
        """
        Sign a payload and return Base64-encoded signature.

        Args:
            payload: Data to sign (str, bytes, or dict -> JSON)

        Returns:
            str: Base64-encoded signature (64 bytes)
        """
        if isinstance(payload, dict):
            payload = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        if isinstance(payload, str):
            payload = payload.encode('utf-8')

        signed = self._signing_key.sign(payload)
        signature = signed.signature  # 64 bytes

        return base64.b64encode(signature).decode('utf-8')

    def sign_manifest(self, manifest: dict) -> dict:
        """
        Sign a manifest and embed the signature.

        Args:
            manifest: Manifest dict (without signature field)

        Returns:
            dict: Manifest with 'signature' field added
        """
        # Create a copy without signature field
        to_sign = {k: v for k, v in manifest.items() if k != 'signature'}

        # Sign the canonical JSON
        signature = self.sign(to_sign)

        # Return manifest with signature
        result = dict(manifest)
        result['signature'] = signature

        return result


class Ed25519Verifier:
    """
    Verifies Ed25519 signatures.
    Used by Station to verify manifests from Hub.
    """

    def __init__(self, public_key_b64: str):
        """
        Initialize verifier with public key.

        Args:
            public_key_b64: Base64-encoded 32-byte Ed25519 public key
        """
        public_bytes = base64.b64decode(public_key_b64)
        self._verify_key = VerifyKey(public_bytes)

    def verify(self, payload: Union[str, bytes, dict], signature_b64: str) -> bool:
        """
        Verify a signature against a payload.

        Args:
            payload: Original data (str, bytes, or dict -> JSON)
            signature_b64: Base64-encoded signature

        Returns:
            bool: True if valid, False if invalid
        """
        if isinstance(payload, dict):
            payload = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        if isinstance(payload, str):
            payload = payload.encode('utf-8')

        try:
            signature = base64.b64decode(signature_b64)
            self._verify_key.verify(payload, signature)
            return True
        except (BadSignatureError, Exception):
            return False

    def verify_manifest(self, manifest: dict) -> bool:
        """
        Verify a signed manifest.

        Args:
            manifest: Manifest dict with 'signature' field

        Returns:
            bool: True if signature is valid
        """
        if 'signature' not in manifest:
            return False

        signature = manifest['signature']
        to_verify = {k: v for k, v in manifest.items() if k != 'signature'}

        return self.verify(to_verify, signature)


# Convenience functions
def sign_data(private_key_b64: str, data: Union[str, bytes, dict]) -> str:
    """Quick sign without creating Signer object."""
    signer = Ed25519Signer(private_key_b64)
    return signer.sign(data)


def verify_data(public_key_b64: str, data: Union[str, bytes, dict], signature_b64: str) -> bool:
    """Quick verify without creating Verifier object."""
    verifier = Ed25519Verifier(public_key_b64)
    return verifier.verify(data, signature_b64)


if __name__ == '__main__':
    # Test
    print("=== Ed25519 Signing Test ===")

    # Generate keypair
    priv, pub = generate_keypair()
    print(f"Private Key: {priv[:20]}...")
    print(f"Public Key:  {pub[:20]}...")

    # Sign a manifest
    signer = Ed25519Signer(priv)
    manifest = {
        "type": "RESTOCK_MANIFEST",
        "manifest_id": "M-TEST-001",
        "items": [{"code": "WATER", "qty": 100}]
    }

    signed_manifest = signer.sign_manifest(manifest)
    print(f"\nSigned Manifest:")
    print(json.dumps(signed_manifest, indent=2))

    # Verify
    verifier = Ed25519Verifier(pub)
    is_valid = verifier.verify_manifest(signed_manifest)
    print(f"\nSignature Valid: {is_valid}")

    # Tamper test
    signed_manifest['items'][0]['qty'] = 999
    is_valid_tampered = verifier.verify_manifest(signed_manifest)
    print(f"Tampered Valid: {is_valid_tampered}")
