import re
from typing import Any, Mapping

REDACTED_MARKER = "[REDACTED]"

# Patterns that indicate a field is sensitive by its name or label
SENSITIVE_FIELD_PATTERNS = [
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"api[_]?key", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
    re.compile(r"security[_]?answer", re.IGNORECASE),
    re.compile(r"authorization", re.IGNORECASE),
    re.compile(r"private[_]?key", re.IGNORECASE),
    re.compile(r"client[_]?secret", re.IGNORECASE),
    re.compile(r"access[_]?token", re.IGNORECASE),
]

# Patterns that indicate a value is likely a secret (heuristic)
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
    re.compile(r"gh[ps]_[a-zA-Z0-9]{36}"),  # GitHub tokens
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+", re.IGNORECASE),  # Bearer tokens
    re.compile(r"Basic\s+[A-Za-z0-9+/=]+", re.IGNORECASE),  # Basic auth tokens
    re.compile(r"(?:password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS Access Key
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+ PRIVATE KEY-----"),  # Private Keys
    re.compile(r"://([^:]+):([^@]+)@"),  # URL credentials (user:pass@host)
]

def is_sensitive_field(field_name: str) -> bool:
    """Check if a field name indicates sensitive data."""
    for pattern in SENSITIVE_FIELD_PATTERNS:
        if pattern.search(field_name):
            return True
    return False

def redact_string(value: str) -> str:
    """Redact known sensitive value patterns in a string."""
    if not isinstance(value, str):
        return value
    for pattern in SENSITIVE_VALUE_PATTERNS:
        value = pattern.sub(REDACTED_MARKER, value)
    return value

def redact_html(html: str) -> str:
    """Mask password and credential input elements in HTML content."""
    if not html:
        return html
    # Mask input value attributes on password elements
    html = re.sub(
        r'(<input[^>]*type=["\']password["\'][^>]*value=["\'])([^"\']+)(["\'])',
        r'\1[REDACTED]\3',
        html,
        flags=re.IGNORECASE,
    )
    # Mask values on fields named password/secret/token
    html = re.sub(
        r'(<input[^>]*name=["\'][^"\']*(?:password|secret|token)[^"\']*["\'][^>]*value=["\'])([^"\']+)(["\'])',
        r'\1[REDACTED]\3',
        html,
        flags=re.IGNORECASE,
    )
    return redact_string(html)

def redact_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive fields and values in a dictionary."""
    result: dict[str, Any] = {}
    for k, v in data.items():
        if is_sensitive_field(k):
            result[k] = REDACTED_MARKER
        elif isinstance(v, dict):
            result[k] = redact_dict(v)
        elif isinstance(v, list):
            result[k] = [
                redact_dict(item) if isinstance(item, dict) else redact_string(str(item)) if isinstance(item, str) else item
                for item in v
            ]
        elif isinstance(v, str):
            result[k] = redact_string(v)
        else:
            result[k] = v
    return result
