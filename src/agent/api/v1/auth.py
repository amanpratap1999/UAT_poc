"""Authentication and RBAC dependencies for FastAPI."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt  # type: ignore
from passlib.context import CryptContext  # type: ignore
from pydantic import BaseModel

from agent.core.config import get_settings

_settings = get_settings()

SECRET_KEY = _settings.jwt_secret_key
ALGORITHM = _settings.jwt_algorithm
ACCESS_TOKEN_EXPIRE_MINUTES = int(_settings.__dict__.get("access_token_expire_minutes", 60))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/token")


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: str | None = None
    role: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None


def verify_password(plain_password: str, hashed_password: Any) -> bool:
    return bool(pwd_context.verify(plain_password, hashed_password))


def get_password_hash(password: str) -> Any:
    return pwd_context.hash(password)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return str(encoded_jwt)


def create_sse_ticket(data: dict[str, Any], expires_seconds: int = 120) -> str:
    """Create a short-lived token ticket specifically for SSE streaming (default: 2 minutes)."""
    to_encode = data.copy()
    expire = datetime.now(UTC) + timedelta(seconds=expires_seconds)
    to_encode.update({"exp": expire, "scope": "sse_stream"})
    return str(jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM))


def validate_sse_ticket(ticket: str) -> TokenData:
    """Synchronously decode and validate a short-lived SSE ticket."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate stream ticket",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(ticket, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("scope") != "sse_stream":
            raise credentials_exception
        username: str | None = payload.get("sub")
        role: str | None = payload.get("role")
        tenant_id: str | None = payload.get("tenant_id")
        user_id: str | None = payload.get("user_id")

        if username is None or role is None or tenant_id is None:
            raise credentials_exception
        return TokenData(username=username, role=role, tenant_id=tenant_id, user_id=user_id)
    except JWTError:
        raise credentials_exception from None


def validate_token_string(token: str) -> TokenData:
    """Synchronously decode and validate a JWT token string."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str | None = payload.get("sub")
        role: str | None = payload.get("role")
        tenant_id: str | None = payload.get("tenant_id")
        user_id: str | None = payload.get("user_id")

        if username is None or role is None or tenant_id is None:
            raise credentials_exception
        return TokenData(username=username, role=role, tenant_id=tenant_id, user_id=user_id)
    except JWTError:
        raise credentials_exception from None


async def get_current_user_token(token: Annotated[str, Depends(oauth2_scheme)]) -> TokenData:
    return validate_token_string(token)


class RequireRole:
    """Dependency class to enforce RBAC."""

    def __init__(self, allowed_roles: list[str]):
        self.allowed_roles = allowed_roles

    def __call__(
        self, token_data: Annotated[TokenData, Depends(get_current_user_token)]
    ) -> TokenData:
        if token_data.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires one of roles: {self.allowed_roles}",
            )
        return token_data


# Common role dependencies
require_admin = RequireRole(["Admin"])
require_qa_manager = RequireRole(["Admin", "QA Manager"])
require_qa_engineer = RequireRole(["Admin", "QA Manager", "QA Engineer"])
require_viewer = RequireRole(["Admin", "QA Manager", "QA Engineer", "Viewer"])
