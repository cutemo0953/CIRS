"""
xIRS Distributed Logistics API v1.8

Hub Backend endpoints for Store-and-Forward logistics:
- Manifest generation and printing
- Encrypted packet ingestion
- Station provisioning
- Audit logging
"""

import json
import hashlib
import sys
import os
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# Add shared module path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database import get_db, write_db, dict_from_row, rows_to_list

# Import crypto modules
from shared.crypto.signing import Ed25519Signer, Ed25519Verifier, generate_keypair
from shared.crypto.encryption import SealedBox, generate_encryption_keypair
from shared.crypto.hmac import generate_station_secret, verify_hmac, compute_hmac
from shared.protocol.manifest import ManifestBuilder
from shared.protocol.chunking import QRChunker, QRReassembler
from shared.protocol.report import ReportDecryptor


router = APIRouter()


# ============================================================================
# Request/Response Models
# ============================================================================

class ManifestItem(BaseModel):
    code: str
    qty: int
    unit: str = "unit"


class CreateManifestRequest(BaseModel):
    station_id: str
    items: List[ManifestItem]
    manifest_id: Optional[str] = None


class CreateManifestResponse(BaseModel):
    manifest_id: str
    short_code: str
    station_id: str
    items: List[dict]
    signature: str
    qr_chunks: List[str]
    print_url: str


class IngestPacketRequest(BaseModel):
    envelope: dict = Field(..., description="Encrypted REPORT_PACKET envelope")


class IngestPacketResponse(BaseModel):
    success: bool
    packet_id: str
    station_id: str
    actions_count: int
    is_duplicate: bool = False
    message: str


class ProvisionStationRequest(BaseModel):
    station_id: str
    display_name: str


class ProvisionStationResponse(BaseModel):
    station_id: str
    display_name: str
    station_secret: str
    hub_public_key: str
    hub_encryption_key: str


class StationInfo(BaseModel):
    station_id: str
    display_name: str
    last_sync_at: Optional[str]
    last_seq_id: int
    is_active: bool


class AuditLogEntry(BaseModel):
    id: int
    event_type: str
    station_id: Optional[str]
    packet_id: Optional[str]
    manifest_id: Optional[str]
    details: Optional[str]
    created_at: str


# ============================================================================
# Key Management Helpers
# ============================================================================

def get_or_create_hub_keys(conn):
    """Get or create Hub signing and encryption keypairs."""
    keys = {}

    # Signing key (Ed25519)
    cursor = conn.execute("SELECT private_key, public_key FROM hub_keys WHERE key_type = 'signing'")
    row = cursor.fetchone()
    if row:
        keys['signing_private'] = row['private_key']
        keys['signing_public'] = row['public_key']
    else:
        priv, pub = generate_keypair()
        conn.execute(
            "INSERT INTO hub_keys (key_type, private_key, public_key) VALUES (?, ?, ?)",
            ('signing', priv, pub)
        )
        keys['signing_private'] = priv
        keys['signing_public'] = pub

    # Encryption key (X25519)
    cursor = conn.execute("SELECT private_key, public_key FROM hub_keys WHERE key_type = 'encryption'")
    row = cursor.fetchone()
    if row:
        keys['encryption_private'] = row['private_key']
        keys['encryption_public'] = row['public_key']
    else:
        priv, pub = generate_encryption_keypair()
        conn.execute(
            "INSERT INTO hub_keys (key_type, private_key, public_key) VALUES (?, ?, ?)",
            ('encryption', priv, pub)
        )
        keys['encryption_private'] = priv
        keys['encryption_public'] = pub

    conn.commit()
    return keys


def log_audit(conn, event_type: str, station_id: str = None,
              packet_id: str = None, manifest_id: str = None, details: str = None):
    """Log an audit event."""
    conn.execute("""
        INSERT INTO logistics_audit (event_type, station_id, packet_id, manifest_id, details)
        VALUES (?, ?, ?, ?, ?)
    """, (event_type, station_id, packet_id, manifest_id, details))


# ============================================================================
# Manifest Endpoints
# ============================================================================

@router.post("/manifest", response_model=CreateManifestResponse)
async def create_manifest(request: CreateManifestRequest):
    """
    Generate a signed RESTOCK_MANIFEST for a station.

    The manifest is signed with Hub's Ed25519 private key.
    Returns the manifest data and QR chunks for printing.
    """
    with write_db() as conn:
        # Verify station exists
        cursor = conn.execute(
            "SELECT station_id FROM logistics_stations WHERE station_id = ? AND is_active = 1",
            (request.station_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=404,
                detail=f"Station '{request.station_id}' not found or inactive"
            )

        # Get Hub signing key
        keys = get_or_create_hub_keys(conn)

        # Build manifest
        builder = ManifestBuilder(keys['signing_private'])
        items = [item.model_dump() for item in request.items]
        manifest = builder.create_manifest(
            station_id=request.station_id,
            items=items,
            manifest_id=request.manifest_id
        )

        # Get QR chunks
        qr_chunks = builder.to_qr_chunks(manifest)

        # Store manifest in database
        conn.execute("""
            INSERT INTO logistics_manifests
            (manifest_id, short_code, station_id, items, signature, status)
            VALUES (?, ?, ?, ?, ?, 'PENDING')
        """, (
            manifest.manifest_id,
            manifest.short_code,
            manifest.station_id,
            json.dumps(items),
            manifest.signature
        ))

        # Log audit
        log_audit(conn, 'MANIFEST_CREATED', request.station_id,
                  manifest_id=manifest.manifest_id,
                  details=f"Items: {len(items)}")

        return CreateManifestResponse(
            manifest_id=manifest.manifest_id,
            short_code=manifest.short_code,
            station_id=manifest.station_id,
            items=items,
            signature=manifest.signature,
            qr_chunks=qr_chunks,
            print_url=f"/api/logistics/manifest/{manifest.manifest_id}/print"
        )


@router.get("/manifest/{manifest_id}")
async def get_manifest(manifest_id: str):
    """Get manifest details by ID."""
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT manifest_id, short_code, station_id, items, signature, status,
                   created_at, acknowledged_at
            FROM logistics_manifests WHERE manifest_id = ?
        """, (manifest_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Manifest not found")

        manifest = dict_from_row(row)
        manifest['items'] = json.loads(manifest['items'])
        return manifest


@router.get("/manifest/{manifest_id}/print")
async def get_manifest_printable(manifest_id: str):
    """
    Get printable HTML for a manifest.

    Returns HTML that can be printed as a physical manifest document.
    """
    from fastapi.responses import HTMLResponse

    with get_db() as conn:
        cursor = conn.execute("""
            SELECT manifest_id, short_code, station_id, items, signature, created_at
            FROM logistics_manifests WHERE manifest_id = ?
        """, (manifest_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Manifest not found")

        manifest = dict_from_row(row)
        items = json.loads(manifest['items'])

        # Get Hub signing key for QR generation
        keys = get_or_create_hub_keys(conn)
        builder = ManifestBuilder(keys['signing_private'])

        # Rebuild manifest object for HTML generation
        from shared.protocol.manifest import RestockManifest
        import time

        manifest_obj = RestockManifest(
            manifest_id=manifest['manifest_id'],
            short_code=manifest['short_code'],
            station_id=manifest['station_id'],
            items=items,
            ts=int(datetime.fromisoformat(manifest['created_at'].replace('Z', '+00:00')).timestamp()) if manifest['created_at'] else int(time.time()),
            signature=manifest['signature']
        )

        html = builder.to_printable_html(manifest_obj)
        return HTMLResponse(content=html)


@router.get("/manifests")
async def list_manifests(
    station_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(50, le=200)
):
    """List manifests with optional filters."""
    with get_db() as conn:
        query = """
            SELECT manifest_id, short_code, station_id, items, status,
                   created_at, acknowledged_at
            FROM logistics_manifests
            WHERE 1=1
        """
        params = []

        if station_id:
            query += " AND station_id = ?"
            params.append(station_id)
        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        manifests = []
        for row in rows:
            m = dict_from_row(row)
            m['items'] = json.loads(m['items'])
            m['items_count'] = len(m['items'])
            manifests.append(m)

        return {"manifests": manifests, "count": len(manifests)}


# ============================================================================
# Packet Ingestion Endpoints
# ============================================================================

@router.post("/ingest", response_model=IngestPacketResponse)
async def ingest_packet(request: IngestPacketRequest):
    """
    Receive and process an encrypted REPORT_PACKET from a Station.

    Flow:
    1. Decrypt with Hub's private key
    2. Verify HMAC with station's secret
    3. Check packet_id for deduplication
    4. Apply actions if new packet
    5. Log to audit trail
    """
    envelope = request.envelope

    if envelope.get('type') != 'ENCRYPTED_REPORT':
        raise HTTPException(
            status_code=400,
            detail="Invalid envelope type. Expected 'ENCRYPTED_REPORT'"
        )

    with write_db() as conn:
        # Get Hub decryption key
        keys = get_or_create_hub_keys(conn)
        decryptor = ReportDecryptor(keys['encryption_private'])

        # Decrypt the envelope
        try:
            payload_bytes = decryptor._sealed_box.decrypt(
                envelope['payload'],
                decompress=envelope.get('compressed', True)
            )
            report = json.loads(payload_bytes.decode('utf-8'))
        except Exception as e:
            log_audit(conn, 'INGEST_DECRYPT_FAILED', details=str(e))
            raise HTTPException(
                status_code=400,
                detail=f"Decryption failed: {str(e)}"
            )

        # Extract fields
        packet_id = report.get('packet_id')
        station_id = report.get('station_id')
        hmac_value = report.get('hmac')
        actions = report.get('actions', [])
        seq_id = report.get('seq_id', 0)

        if not packet_id or not station_id:
            raise HTTPException(
                status_code=400,
                detail="Missing required fields: packet_id or station_id"
            )

        # Get station secret for HMAC verification
        cursor = conn.execute(
            "SELECT station_secret FROM logistics_stations WHERE station_id = ? AND is_active = 1",
            (station_id,)
        )
        station_row = cursor.fetchone()

        if not station_row:
            log_audit(conn, 'INGEST_UNKNOWN_STATION', station_id, packet_id)
            raise HTTPException(
                status_code=404,
                detail=f"Unknown or inactive station: {station_id}"
            )

        station_secret = station_row['station_secret']

        # Verify HMAC
        signable = {k: v for k, v in report.items() if k != 'hmac'}
        expected_hmac = compute_hmac(station_secret, signable)

        import hmac as hmac_module
        if not hmac_module.compare_digest(expected_hmac, hmac_value):
            log_audit(conn, 'INGEST_HMAC_FAILED', station_id, packet_id)
            raise HTTPException(
                status_code=401,
                detail="HMAC verification failed"
            )

        # Check for duplicate (idempotency)
        payload_hash = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()

        cursor = conn.execute(
            "SELECT packet_id FROM seen_packets WHERE packet_id = ?",
            (packet_id,)
        )
        if cursor.fetchone():
            log_audit(conn, 'INGEST_DUPLICATE', station_id, packet_id)
            return IngestPacketResponse(
                success=True,
                packet_id=packet_id,
                station_id=station_id,
                actions_count=len(actions),
                is_duplicate=True,
                message="Duplicate packet ignored (already processed)"
            )

        # Record packet
        conn.execute("""
            INSERT INTO seen_packets (packet_id, station_id, payload_hash)
            VALUES (?, ?, ?)
        """, (packet_id, station_id, payload_hash))

        # Update station sync info
        conn.execute("""
            UPDATE logistics_stations
            SET last_sync_at = CURRENT_TIMESTAMP, last_seq_id = MAX(last_seq_id, ?)
            WHERE station_id = ?
        """, (seq_id, station_id))

        # Process actions
        for action in actions:
            action_type = action.get('type')
            item_code = action.get('item_code')
            qty = action.get('qty', 0)

            if action_type == 'RECEIVE':
                # Manifest acknowledgement
                manifest_id = action.get('manifest_id')
                if manifest_id:
                    conn.execute("""
                        UPDATE logistics_manifests
                        SET status = 'ACKNOWLEDGED', acknowledged_at = CURRENT_TIMESTAMP
                        WHERE manifest_id = ?
                    """, (manifest_id,))

                # Update inventory (add)
                cursor = conn.execute(
                    "SELECT id, quantity FROM inventory WHERE name = ?",
                    (item_code,)
                )
                inv_row = cursor.fetchone()
                if inv_row:
                    conn.execute(
                        "UPDATE inventory SET quantity = quantity + ? WHERE id = ?",
                        (qty, inv_row['id'])
                    )

            elif action_type == 'DISPENSE':
                # Update inventory (subtract)
                cursor = conn.execute(
                    "SELECT id, quantity FROM inventory WHERE name = ?",
                    (item_code,)
                )
                inv_row = cursor.fetchone()
                if inv_row:
                    new_qty = max(0, inv_row['quantity'] - qty)
                    conn.execute(
                        "UPDATE inventory SET quantity = ? WHERE id = ?",
                        (new_qty, inv_row['id'])
                    )

            elif action_type == 'REGISTER':
                # Person registration - handled separately
                person_id = action.get('person_id')
                metadata = action.get('metadata', {})
                # Could create person record here if needed

            # Log each action
            log_audit(conn, f'ACTION_{action_type}', station_id, packet_id,
                      details=json.dumps(action))

        log_audit(conn, 'INGEST_SUCCESS', station_id, packet_id,
                  details=f"Actions: {len(actions)}, seq_id: {seq_id}")

        return IngestPacketResponse(
            success=True,
            packet_id=packet_id,
            station_id=station_id,
            actions_count=len(actions),
            is_duplicate=False,
            message=f"Packet processed successfully. {len(actions)} actions applied."
        )


@router.post("/ingest/chunks")
async def ingest_chunked_packet(chunks: List[str]):
    """
    Receive a chunked packet (from multiple QR scans).

    Reassembles chunks and processes as a single packet.
    """
    reassembler = QRReassembler()

    for chunk in chunks:
        result = reassembler.add_chunk(chunk)
        if result:
            # Reassembly complete
            envelope = json.loads(result.decode('utf-8'))
            # Reuse the ingest endpoint
            return await ingest_packet(IngestPacketRequest(envelope=envelope))

    # Not all chunks received
    received, total = reassembler.progress
    missing = reassembler.missing_sequences

    raise HTTPException(
        status_code=400,
        detail=f"Incomplete packet: {received}/{total} chunks. Missing: {missing}"
    )


# ============================================================================
# Station Management Endpoints
# ============================================================================

@router.post("/station/provision", response_model=ProvisionStationResponse)
async def provision_station(request: ProvisionStationRequest):
    """
    Provision a new station with credentials.

    Generates:
    - station_secret for HMAC authentication
    - Returns Hub's public keys for encryption and signature verification
    """
    with write_db() as conn:
        # Check if already exists
        cursor = conn.execute(
            "SELECT station_id FROM logistics_stations WHERE station_id = ?",
            (request.station_id,)
        )
        if cursor.fetchone():
            raise HTTPException(
                status_code=409,
                detail=f"Station '{request.station_id}' already exists"
            )

        # Generate station secret
        station_secret = generate_station_secret()

        # Get Hub keys
        keys = get_or_create_hub_keys(conn)

        # Create station record
        conn.execute("""
            INSERT INTO logistics_stations (station_id, display_name, station_secret)
            VALUES (?, ?, ?)
        """, (request.station_id, request.display_name, station_secret))

        log_audit(conn, 'STATION_PROVISIONED', request.station_id,
                  details=f"Display name: {request.display_name}")

        return ProvisionStationResponse(
            station_id=request.station_id,
            display_name=request.display_name,
            station_secret=station_secret,
            hub_public_key=keys['signing_public'],
            hub_encryption_key=keys['encryption_public']
        )


@router.get("/station/{station_id}/secret")
async def get_station_secret(station_id: str):
    """
    Get station credentials (for re-provisioning).

    Returns the station's HMAC secret and Hub's public keys.
    """
    with get_db() as conn:
        cursor = conn.execute("""
            SELECT station_id, display_name, station_secret
            FROM logistics_stations WHERE station_id = ?
        """, (station_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="Station not found")

        keys = get_or_create_hub_keys(conn)

        return {
            "station_id": row['station_id'],
            "display_name": row['display_name'],
            "station_secret": row['station_secret'],
            "hub_public_key": keys['signing_public'],
            "hub_encryption_key": keys['encryption_public']
        }


@router.get("/stations")
async def list_stations(include_inactive: bool = False):
    """List all registered stations."""
    with get_db() as conn:
        query = """
            SELECT station_id, display_name, last_sync_at, last_seq_id, is_active, created_at
            FROM logistics_stations
        """
        if not include_inactive:
            query += " WHERE is_active = 1"
        query += " ORDER BY display_name"

        cursor = conn.execute(query)
        rows = cursor.fetchall()

        return {
            "stations": rows_to_list(rows),
            "count": len(rows)
        }


@router.patch("/station/{station_id}")
async def update_station(station_id: str, display_name: Optional[str] = None,
                         is_active: Optional[bool] = None):
    """Update station settings."""
    with write_db() as conn:
        cursor = conn.execute(
            "SELECT station_id FROM logistics_stations WHERE station_id = ?",
            (station_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Station not found")

        updates = []
        params = []

        if display_name is not None:
            updates.append("display_name = ?")
            params.append(display_name)
        if is_active is not None:
            updates.append("is_active = ?")
            params.append(1 if is_active else 0)

        if updates:
            params.append(station_id)
            conn.execute(
                f"UPDATE logistics_stations SET {', '.join(updates)} WHERE station_id = ?",
                params
            )

            log_audit(conn, 'STATION_UPDATED', station_id, details=str(updates))

        return {"success": True, "station_id": station_id}


@router.delete("/station/{station_id}")
async def delete_station(station_id: str, hard_delete: bool = False):
    """
    Delete or deactivate a station.

    By default, sets is_active = 0 (soft delete).
    Use hard_delete=true to permanently remove.
    """
    with write_db() as conn:
        cursor = conn.execute(
            "SELECT station_id FROM logistics_stations WHERE station_id = ?",
            (station_id,)
        )
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Station not found")

        if hard_delete:
            conn.execute("DELETE FROM logistics_stations WHERE station_id = ?", (station_id,))
            log_audit(conn, 'STATION_DELETED', station_id)
        else:
            conn.execute(
                "UPDATE logistics_stations SET is_active = 0 WHERE station_id = ?",
                (station_id,)
            )
            log_audit(conn, 'STATION_DEACTIVATED', station_id)

        return {"success": True, "station_id": station_id, "hard_delete": hard_delete}


# ============================================================================
# Audit Endpoints
# ============================================================================

@router.get("/audit")
async def get_audit_logs(
    event_type: Optional[str] = None,
    station_id: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0
):
    """Get audit log entries with optional filters."""
    with get_db() as conn:
        query = """
            SELECT id, event_type, station_id, packet_id, manifest_id, details, created_at
            FROM logistics_audit
            WHERE 1=1
        """
        params = []

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if station_id:
            query += " AND station_id = ?"
            params.append(station_id)

        query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        # Get total count
        count_query = "SELECT COUNT(*) as total FROM logistics_audit WHERE 1=1"
        count_params = []
        if event_type:
            count_query += " AND event_type = ?"
            count_params.append(event_type)
        if station_id:
            count_query += " AND station_id = ?"
            count_params.append(station_id)

        cursor = conn.execute(count_query, count_params)
        total = cursor.fetchone()['total']

        return {
            "logs": rows_to_list(rows),
            "count": len(rows),
            "total": total,
            "offset": offset,
            "limit": limit
        }


@router.get("/audit/summary")
async def get_audit_summary():
    """Get summary statistics from audit logs."""
    with get_db() as conn:
        # Event type counts
        cursor = conn.execute("""
            SELECT event_type, COUNT(*) as count
            FROM logistics_audit
            GROUP BY event_type
            ORDER BY count DESC
        """)
        by_type = {row['event_type']: row['count'] for row in cursor.fetchall()}

        # Recent activity by station
        cursor = conn.execute("""
            SELECT station_id, COUNT(*) as count, MAX(created_at) as last_activity
            FROM logistics_audit
            WHERE station_id IS NOT NULL
            GROUP BY station_id
            ORDER BY last_activity DESC
            LIMIT 10
        """)
        by_station = rows_to_list(cursor.fetchall())

        # Today's counts
        cursor = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN event_type = 'INGEST_SUCCESS' THEN 1 ELSE 0 END) as packets_received,
                   SUM(CASE WHEN event_type = 'MANIFEST_CREATED' THEN 1 ELSE 0 END) as manifests_created
            FROM logistics_audit
            WHERE DATE(created_at) = DATE('now')
        """)
        today = dict_from_row(cursor.fetchone())

        return {
            "by_event_type": by_type,
            "by_station": by_station,
            "today": today
        }


# ============================================================================
# Hub Info Endpoint
# ============================================================================

@router.get("/hub/keys")
async def get_hub_public_keys():
    """
    Get Hub's public keys for Station configuration.

    Returns:
    - signing_public: Ed25519 public key for manifest verification
    - encryption_public: X25519 public key for report encryption
    """
    with get_db() as conn:
        keys = get_or_create_hub_keys(conn)

        return {
            "signing_public": keys['signing_public'],
            "encryption_public": keys['encryption_public']
        }
