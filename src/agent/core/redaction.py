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
]

# Patterns that indicate a value is likely a secret (heuristic)
SENSITIVE_VALUE_PATTERNS = [
    re.compile(r"ey[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"),  # JWT
    re.compile(r"gh[ps]_[a-zA-Z0-9]{36}"),  # GitHub tokens
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

def redact_dict(data: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively redact sensitive fields and values in a dictionary."""
    result = {}
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
