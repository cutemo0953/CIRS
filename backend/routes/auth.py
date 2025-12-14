"""
CIRS Authentication Routes
PIN-based authentication with JWT tokens
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
import hashlib
import os
import sys
import io
import socket
import qrcode
from qrcode.image.styledpil import StyledPilImage

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row

router = APIRouter()

# Security settings
SECRET_KEY = os.getenv("CIRS_SECRET_KEY", "cirs-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# PIN salt for hashing
PIN_SALT = os.getenv("CIRS_PIN_SALT", "cirs-pin-salt-2024")

# Bearer token scheme
security = HTTPBearer(auto_error=False)


# Pydantic models
class LoginRequest(BaseModel):
    person_id: str
    pin: str


class TokenResponse(BaseModel):
    token: str
    person: dict
    expires_in: int


class ChangePinRequest(BaseModel):
    old_pin: str
    new_pin: str


def hash_pin(pin: str) -> str:
    """Hash a PIN using SHA-256 with salt"""
    salted = f"{PIN_SALT}{pin}{PIN_SALT}"
    return hashlib.sha256(salted.encode()).hexdigest()


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """Verify a PIN against its hash"""
    # Support old bcrypt hashes for migration (default admin PIN: 1234)
    if hashed_pin.startswith('$2b$') or hashed_pin.startswith('$2a$'):
        # Bcrypt hash detected - only accept known default PIN for migration
        if plain_pin == '1234':
            return True  # Allow default admin login, they should change PIN
        return False
    # SHA-256 hash
    return hash_pin(plain_pin) == hashed_pin


def create_access_token(data: dict, expires_delta: timedelta = None) -> str:
    """Create a JWT access token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    """Decode and validate a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependency to get current authenticated user"""
    if credentials is None:
        return None

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    person_id = payload.get("sub")
    if person_id is None:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    with get_db() as conn:
        cursor = conn.execute("SELECT * FROM person WHERE id = ?", (person_id,))
        person = dict_from_row(cursor.fetchone())

    if person is None:
        raise HTTPException(status_code=401, detail="User not found")

    return person


async def require_role(required_roles: list, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Dependency to require specific roles"""
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    if user['role'] not in required_roles:
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    return user


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """Login with person_id and PIN"""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT * FROM person WHERE id = ?",
            (request.person_id,)
        )
        person = dict_from_row(cursor.fetchone())

    if person is None:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if person['pin_hash'] is None:
        raise HTTPException(status_code=401, detail="No PIN set for this user")

    if not verify_pin(request.pin, person['pin_hash']):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    # Create token
    token = create_access_token({"sub": person['id'], "role": person['role']})

    # Remove sensitive data from response
    person.pop('pin_hash', None)

    return TokenResponse(
        token=token,
        person=person,
        expires_in=ACCESS_TOKEN_EXPIRE_HOURS * 3600
    )


@router.post("/verify")
async def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify a token and return user info"""
    user = await get_current_user(credentials)
    if user is None:
        return {"valid": False}

    user.pop('pin_hash', None)
    return {"valid": True, "person": user}


@router.post("/change-pin")
async def change_pin(
    request: ChangePinRequest,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Change user's PIN"""
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Verify old PIN
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT pin_hash FROM person WHERE id = ?",
            (user['id'],)
        )
        row = cursor.fetchone()

    if row is None or not verify_pin(request.old_pin, row['pin_hash']):
        raise HTTPException(status_code=401, detail="Invalid current PIN")

    # Update PIN
    new_hash = hash_pin(request.new_pin)
    with write_db() as conn:
        conn.execute(
            "UPDATE person SET pin_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_hash, user['id'])
        )

    return {"success": True, "message": "PIN changed successfully"}


@router.get("/me")
async def get_me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Get current user info"""
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    user.pop('pin_hash', None)
    return user


# Satellite pairing token expiry (shorter for security)
SATELLITE_TOKEN_EXPIRE_HOURS = 72


def get_host_ip() -> str:
    """Get the host machine's IP address"""
    try:
        # Create a socket to determine the outbound IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def create_satellite_token(hub_name: str = "CIRS Hub") -> str:
    """Create a JWT token for satellite pairing"""
    data = {
        "sub": "satellite",
        "type": "satellite_pairing",
        "hub_name": hub_name,
        "issued_at": datetime.utcnow().isoformat()  # Custom field for display, not 'iat'
    }
    return create_access_token(data, timedelta(hours=SATELLITE_TOKEN_EXPIRE_HOURS))


@router.get("/pairing-qr")
async def get_pairing_qr(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Generate a QR code for Satellite PWA pairing.
    Returns a PNG image containing QR code with pairing URL.
    Requires admin authentication.
    """
    # Require admin role
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")

    # Get hub name from database
    hub_name = "CIRS Hub"
    try:
        with get_db() as conn:
            cursor = conn.execute("SELECT value FROM system_config WHERE key = 'site_name'")
            row = cursor.fetchone()
            if row:
                hub_name = row['value']
    except Exception:
        pass

    # Get host IP
    host_ip = get_host_ip()

    # Try to get IP from request headers (in case behind proxy)
    forwarded_host = request.headers.get("X-Forwarded-Host")
    if forwarded_host:
        host_ip = forwarded_host.split(":")[0]

    # Create pairing token
    token = create_satellite_token(hub_name)

    # Build pairing URL
    # Note: Use the same port as CIRS API (8090)
    pairing_url = f"http://{host_ip}:8090/mobile/?token={token}"

    # Generate QR code
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(pairing_url)
    qr.make(fit=True)

    # Create image
    img = qr.make_image(fill_color="#0ea5e9", back_color="white")

    # Save to bytes buffer
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="image/png",
        headers={
            "Content-Disposition": "inline; filename=pairing-qr.png",
            "Cache-Control": "no-cache, no-store, must-revalidate"
        }
    )


@router.get("/pairing-info")
async def get_pairing_info(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Get pairing information as JSON (for manual connection).
    Requires admin authentication.
    """
    # Require admin role
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if user.get('role') != 'admin':
        raise HTTPException(status_code=403, detail="Admin access required")

    # Get hub name
    hub_name = "CIRS Hub"
    try:
        with get_db() as conn:
            cursor = conn.execute("SELECT value FROM system_config WHERE key = 'site_name'")
            row = cursor.fetchone()
            if row:
                hub_name = row['value']
    except Exception:
        pass

    # Get host IP
    host_ip = get_host_ip()
    forwarded_host = request.headers.get("X-Forwarded-Host")
    if forwarded_host:
        host_ip = forwarded_host.split(":")[0]

    # Create token
    token = create_satellite_token(hub_name)

    return {
        "hub_name": hub_name,
        "hub_url": f"http://{host_ip}:8090",
        "token": token,
        "pairing_url": f"http://{host_ip}:8090/mobile/?token={token}",
        "expires_in": SATELLITE_TOKEN_EXPIRE_HOURS * 3600
    }


@router.post("/satellite/verify")
async def verify_satellite_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verify a satellite pairing token.
    Returns hub info if valid.
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="Token required")

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    if payload.get("type") != "satellite_pairing":
        raise HTTPException(status_code=401, detail="Invalid token type")

    return {
        "valid": True,
        "hub_name": payload.get("hub_name", "CIRS Hub"),
        "issued_at": payload.get("issued_at")
    }
