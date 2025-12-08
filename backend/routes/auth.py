"""
CIRS Authentication Routes
PIN-based authentication with JWT tokens
"""
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
import os
import sys

# Add parent directory to path for imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import get_db, write_db, dict_from_row

router = APIRouter()

# Security settings
SECRET_KEY = os.getenv("CIRS_SECRET_KEY", "cirs-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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


def verify_pin(plain_pin: str, hashed_pin: str) -> bool:
    """Verify a PIN against its hash"""
    return pwd_context.verify(plain_pin, hashed_pin)


def hash_pin(pin: str) -> str:
    """Hash a PIN"""
    return pwd_context.hash(pin)


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
