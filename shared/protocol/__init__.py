"""
xIRS Distributed Logistics - Protocol Module v1.8

Provides packet building and parsing for the Store-and-Forward protocol:
- Manifest builder (Hub → Station)
- Report builder (Station → Hub)
- QR chunking for large payloads
"""

from .chunking import QRChunker, QRReassembler
from .manifest import ManifestBuilder, RestockManifest
from .report import ReportBuilder, ReportPacket, ReportDecryptor

__all__ = [
    'QRChunker',
    'QRReassembler',
    'ManifestBuilder',
    'RestockManifest',
    'ReportBuilder',
    'ReportPacket',
    'ReportDecryptor'
]

__version__ = '1.8.0'
