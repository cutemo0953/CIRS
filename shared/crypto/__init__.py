"""
xIRS Distributed Logistics - Crypto Module v1.8

Provides cryptographic primitives for the Store-and-Forward protocol:
- Ed25519 signing (Hub → Station manifests)
- NaCl SealedBox encryption (Station → Hub reports)
- HMAC-SHA256 integrity (Station authentication)
"""

from .signing import Ed25519Signer, Ed25519Verifier, generate_keypair
from .encryption import SealedBox
from .hmac import compute_hmac, verify_hmac

__all__ = [
    'Ed25519Signer',
    'Ed25519Verifier',
    'generate_keypair',
    'SealedBox',
    'compute_hmac',
    'verify_hmac'
]

__version__ = '1.8.0'
