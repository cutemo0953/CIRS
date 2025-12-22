"""
QR Chunking Module for xIRS v1.8

Handles splitting large payloads into multiple QR codes and reassembling them.

Constraints:
- Max 800 bytes per QR (Base64 encoded)
- Format: xIRS|{seq}/{total}|{chunk_data}
- Header overhead: ~15 bytes

Usage:
    # Chunking (Station side)
    chunker = QRChunker(max_chunk_size=800)
    chunks = chunker.chunk(large_payload)
    # Display each chunk as QR code

    # Reassembly (Runner/Hub side)
    reassembler = QRReassembler()
    for qr_data in scanned_qrs:
        result = reassembler.add_chunk(qr_data)
        if result:
            # All chunks received, result is complete payload
            break
"""

import base64
import json
from typing import List, Optional, Tuple, Union
from dataclasses import dataclass


# Protocol constants
PROTOCOL_PREFIX = "xIRS"
CHUNK_SEPARATOR = "|"
MAX_CHUNK_SIZE = 800  # bytes, Base64 encoded
HEADER_OVERHEAD = 20  # "xIRS|99/99|" = ~11 chars, leave buffer


@dataclass
class ChunkInfo:
    """Information about a single chunk."""
    sequence: int
    total: int
    data: str
    raw: str


class QRChunker:
    """
    Splits payloads into QR-friendly chunks.
    """

    def __init__(self, max_chunk_size: int = MAX_CHUNK_SIZE):
        """
        Initialize chunker.

        Args:
            max_chunk_size: Maximum bytes per chunk (including header)
        """
        self.max_chunk_size = max_chunk_size
        # Account for header overhead
        self.max_data_size = max_chunk_size - HEADER_OVERHEAD

    def chunk(self, payload: Union[str, bytes, dict]) -> List[str]:
        """
        Split payload into chunks.

        Args:
            payload: Data to chunk (str, bytes, or dict -> JSON)

        Returns:
            List[str]: List of chunk strings ready for QR encoding
        """
        # Serialize
        if isinstance(payload, dict):
            payload = json.dumps(payload, separators=(',', ':'))
        if isinstance(payload, str):
            payload = payload.encode('utf-8')

        # Base64 encode
        payload_b64 = base64.b64encode(payload).decode('utf-8')

        # Check if chunking needed
        if len(payload_b64) <= self.max_data_size:
            # Single chunk
            return [f"{PROTOCOL_PREFIX}{CHUNK_SEPARATOR}1/1{CHUNK_SEPARATOR}{payload_b64}"]

        # Split into chunks
        chunks = []
        total = (len(payload_b64) + self.max_data_size - 1) // self.max_data_size

        for i in range(total):
            start = i * self.max_data_size
            end = start + self.max_data_size
            chunk_data = payload_b64[start:end]
            chunk_str = f"{PROTOCOL_PREFIX}{CHUNK_SEPARATOR}{i+1}/{total}{CHUNK_SEPARATOR}{chunk_data}"
            chunks.append(chunk_str)

        return chunks

    def chunk_with_info(self, payload: Union[str, bytes, dict]) -> List[Tuple[str, ChunkInfo]]:
        """
        Split payload and return chunk info.

        Returns:
            List[Tuple[str, ChunkInfo]]: List of (chunk_string, info) tuples
        """
        chunks = self.chunk(payload)
        result = []

        for chunk_str in chunks:
            info = parse_chunk(chunk_str)
            result.append((chunk_str, info))

        return result


class QRReassembler:
    """
    Reassembles chunks back into original payload.
    """

    def __init__(self):
        """Initialize reassembler with empty buffer."""
        self.reset()

    def reset(self):
        """Clear buffer and start fresh."""
        self._chunks = {}
        self._total = None
        self._complete = False

    @property
    def is_complete(self) -> bool:
        """Check if all chunks received."""
        return self._complete

    @property
    def progress(self) -> Tuple[int, int]:
        """Get progress as (received, total)."""
        if self._total is None:
            return (len(self._chunks), 0)
        return (len(self._chunks), self._total)

    @property
    def missing_sequences(self) -> List[int]:
        """Get list of missing chunk sequence numbers."""
        if self._total is None:
            return []
        all_seqs = set(range(1, self._total + 1))
        received = set(self._chunks.keys())
        return sorted(all_seqs - received)

    def add_chunk(self, chunk_str: str) -> Optional[bytes]:
        """
        Add a chunk to the buffer.

        Args:
            chunk_str: Raw chunk string from QR code

        Returns:
            bytes: Complete payload if all chunks received, None otherwise
        """
        if self._complete:
            return None

        # Parse chunk
        info = parse_chunk(chunk_str)
        if info is None:
            return None

        # Validate consistency
        if self._total is None:
            self._total = info.total
        elif self._total != info.total:
            # Inconsistent total, might be different packet
            return None

        # Store chunk
        self._chunks[info.sequence] = info.data

        # Check if complete
        if len(self._chunks) == self._total:
            self._complete = True
            return self._reassemble()

        return None

    def _reassemble(self) -> bytes:
        """Reassemble all chunks into original payload."""
        # Concatenate in order
        parts = []
        for i in range(1, self._total + 1):
            parts.append(self._chunks[i])

        full_b64 = ''.join(parts)

        # Decode Base64
        return base64.b64decode(full_b64)

    def get_payload(self) -> Optional[bytes]:
        """Get reassembled payload if complete."""
        if self._complete:
            return self._reassemble()
        return None

    def get_payload_json(self) -> Optional[dict]:
        """Get reassembled payload as JSON if complete."""
        payload = self.get_payload()
        if payload:
            return json.loads(payload.decode('utf-8'))
        return None


def parse_chunk(chunk_str: str) -> Optional[ChunkInfo]:
    """
    Parse a chunk string.

    Args:
        chunk_str: Raw chunk string (e.g., "xIRS|1/3|abc123...")

    Returns:
        ChunkInfo or None if invalid
    """
    try:
        parts = chunk_str.split(CHUNK_SEPARATOR, 2)

        if len(parts) != 3:
            return None

        prefix, seq_info, data = parts

        if prefix != PROTOCOL_PREFIX:
            return None

        seq_parts = seq_info.split('/')
        if len(seq_parts) != 2:
            return None

        sequence = int(seq_parts[0])
        total = int(seq_parts[1])

        if sequence < 1 or sequence > total:
            return None

        return ChunkInfo(
            sequence=sequence,
            total=total,
            data=data,
            raw=chunk_str
        )

    except (ValueError, IndexError):
        return None


def is_xirs_chunk(data: str) -> bool:
    """Check if a string looks like an xIRS chunk."""
    return data.startswith(f"{PROTOCOL_PREFIX}{CHUNK_SEPARATOR}")


if __name__ == '__main__':
    # Test
    print("=== QR Chunking Test ===")

    chunker = QRChunker(max_chunk_size=100)  # Small for testing

    # Small payload (no chunking needed)
    small = {"type": "test", "id": 1}
    small_chunks = chunker.chunk(small)
    print(f"\nSmall payload: {len(json.dumps(small))} bytes")
    print(f"Chunks: {len(small_chunks)}")
    print(f"Chunk 1: {small_chunks[0][:50]}...")

    # Large payload (needs chunking)
    large = {
        "type": "REPORT_PACKET",
        "packet_id": "PKT-TEST-001",
        "station_id": "STATION-PARK",
        "actions": [
            {"type": "DISPENSE", "item": f"ITEM-{i}", "qty": i}
            for i in range(20)
        ]
    }

    large_json = json.dumps(large)
    print(f"\nLarge payload: {len(large_json)} bytes")

    large_chunks = chunker.chunk(large)
    print(f"Chunks: {len(large_chunks)}")
    for i, chunk in enumerate(large_chunks):
        print(f"  Chunk {i+1}: {len(chunk)} bytes - {chunk[:40]}...")

    # Reassemble
    print("\n=== Reassembly Test ===")
    reassembler = QRReassembler()

    for chunk in large_chunks:
        result = reassembler.add_chunk(chunk)
        received, total = reassembler.progress
        print(f"Added chunk: {received}/{total}")

        if result:
            print(f"\nReassembled! {len(result)} bytes")
            recovered = json.loads(result.decode('utf-8'))
            print(f"Match original: {recovered == large}")

    # Out-of-order test
    print("\n=== Out-of-Order Test ===")
    reassembler.reset()
    import random
    shuffled = large_chunks.copy()
    random.shuffle(shuffled)

    for chunk in shuffled:
        info = parse_chunk(chunk)
        result = reassembler.add_chunk(chunk)
        print(f"Added chunk {info.sequence}/{info.total}, complete: {result is not None}")
