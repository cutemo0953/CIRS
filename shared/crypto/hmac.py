"""
HMAC-SHA256 Module for xIRS v1.8

Used for authenticating Station identity in REPORT_PACKETs.
Each Station has a unique station_secret shared with Hub.

Flow:
1. Hub provisions Station with station_secret
2. Station computes HMAC(station_secret, payload)
3. Hub verifies HMAC to confirm packet came from legitimate Station
"""

import base64
import hashlib
import hmac
import json
import secrets
from typing import Union


def generate_station_secret() -> str:
    """
    Generate a new station secret for HMAC authentication.

    Returns:
        str: Base64-encoded 32-byte secret
    """
    secret = secrets.token_bytes(32)
    return base64.b64encode(secret).decode('utf-8')


def compute_hmac(secret_b64: str, data: Union[str, bytes, dict]) -> str:
    """
    Compute HMAC-SHA256 of data.

    Args:
        secret_b64: Base64-encoded station secret
        data: Data to authenticate (str, bytes, or dict -> JSON)

    Returns:
        str: Base64-encoded HMAC (32 bytes)
    """
    # Decode secret
    secret = base64.b64decode(secret_b64)

    # Serialize data
    if isinstance(data, dict):
        data = json.dumps(data, separators=(',', ':'), sort_keys=True)
    if isinstance(data, str):
        data = data.encode('utf-8')

    # Compute HMAC
    h = hmac.new(secret, data, hashlib.sha256)

    return base64.b64encode(h.digest()).decode('utf-8')


def verify_hmac(secret_b64: str, data: Union[str, bytes, dict],
                hmac_b64: str) -> bool:
    """
    Verify HMAC-SHA256 of data.

    Args:
        secret_b64: Base64-encoded station secret
        data: Original data
        hmac_b64: Base64-encoded HMAC to verify

    Returns:
        bool: True if HMAC is valid
    """
    expected = compute_hmac(secret_b64, data)

    # Constant-time comparison
    return hmac.compare_digest(expected, hmac_b64)


def add_hmac_to_report(secret_b64: str, report: dict) -> dict:
    """
    Add HMAC to a report packet.

    Args:
        secret_b64: Station's secret
        report: Report dict (without hmac field)

    Returns:
        dict: Report with 'hmac' field added
    """
    # Create a copy without hmac field
    to_sign = {k: v for k, v in report.items() if k != 'hmac'}

    # Compute HMAC
    hmac_value = compute_hmac(secret_b64, to_sign)

    # Return report with HMAC
    result = dict(report)
    result['hmac'] = hmac_value

    return result


def verify_report_hmac(secret_b64: str, report: dict) -> bool:
    """
    Verify HMAC on a report packet.

    Args:
        secret_b64: Station's secret (Hub looks up by station_id)
        report: Report dict with 'hmac' field

    Returns:
        bool: True if HMAC is valid
    """
    if 'hmac' not in report:
        return False

    hmac_value = report['hmac']
    to_verify = {k: v for k, v in report.items() if k != 'hmac'}

    return verify_hmac(secret_b64, to_verify, hmac_value)


class StationAuthenticator:
    """
    Helper class for Station to add authentication to reports.
    """

    def __init__(self, station_secret_b64: str, station_id: str):
        """
        Initialize authenticator.

        Args:
            station_secret_b64: Secret shared with Hub
            station_id: This station's ID
        """
        self._secret = station_secret_b64
        self._station_id = station_id

    def authenticate_report(self, report: dict) -> dict:
        """Add HMAC and ensure station_id is set."""
        result = dict(report)
        result['station_id'] = self._station_id
        return add_hmac_to_report(self._secret, result)


class HubVerifier:
    """
    Helper class for Hub to verify station authentication.
    """

    def __init__(self):
        """Initialize with empty station secrets map."""
        self._secrets = {}  # station_id -> secret_b64

    def register_station(self, station_id: str, secret_b64: str):
        """Register a station's secret."""
        self._secrets[station_id] = secret_b64

    def provision_station(self, station_id: str) -> str:
        """
        Generate and register a new secret for a station.

        Returns:
            str: The generated secret (give this to Station securely)
        """
        secret = generate_station_secret()
        self._secrets[station_id] = secret
        return secret

    def verify_report(self, report: dict) -> bool:
        """
        Verify a report's HMAC.

        Args:
            report: Report with station_id and hmac fields

        Returns:
            bool: True if authenticated
        """
        station_id = report.get('station_id')
        if not station_id:
            return False

        secret = self._secrets.get(station_id)
        if not secret:
            return False

        return verify_report_hmac(secret, report)


if __name__ == '__main__':
    # Test
    print("=== HMAC-SHA256 Test ===")

    # Generate station secret
    secret = generate_station_secret()
    print(f"Station Secret: {secret[:20]}...")

    # Create a report
    report = {
        "type": "REPORT_PACKET",
        "packet_id": "PKT-TEST-001",
        "station_id": "STATION-PARK",
        "seq_id": 1,
        "actions": [
            {"type": "DISPENSE", "item": "WATER", "qty": 10}
        ]
    }

    print(f"\nOriginal Report:")
    print(json.dumps(report, indent=2))

    # Add HMAC
    authenticated = add_hmac_to_report(secret, report)
    print(f"\nAuthenticated Report:")
    print(json.dumps(authenticated, indent=2))

    # Verify
    is_valid = verify_report_hmac(secret, authenticated)
    print(f"\nHMAC Valid: {is_valid}")

    # Tamper test
    authenticated['actions'][0]['qty'] = 999
    is_valid_tampered = verify_report_hmac(secret, authenticated)
    print(f"Tampered Valid: {is_valid_tampered}")

    # Test with HubVerifier
    print("\n=== HubVerifier Test ===")
    hub = HubVerifier()
    station_secret = hub.provision_station("STATION-PARK")
    print(f"Provisioned secret for STATION-PARK")

    station = StationAuthenticator(station_secret, "STATION-PARK")
    auth_report = station.authenticate_report(report)
    print(f"Station authenticated report")

    hub_verified = hub.verify_report(auth_report)
    print(f"Hub verification: {hub_verified}")
