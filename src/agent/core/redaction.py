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
    """Mask password and credential input elements in HTML content.

    Audit issue I35 (P1): the previous regex only matched password inputs
    whose ``value="..."`` attribute appeared AFTER ``type="password"`` in
    tag order. ServiceNow forms frequently render
    ``<input value="<secret>" name="user_password" type="password">``
    (value BEFORE type, or no type at all). Those slipped through and
    unmasked passwords ended up in DOM snapshots fed to the LLM.

    Fix: use a tolerant HTML-aware approach. We do TWO passes:
    1. Iterate all ``<input ...>`` tags via regex (handles both self-closing
       and non-self-closing forms, single+double quotes).
    2. For each input, parse its attributes and check whether (a) any
       attribute value is ``password``/``secret``/``token``/``api_key`` etc.
       (covers ``type=password``, ``name=user_password``, ``id=secret``),
       AND (b) the input has a ``value="..."`` attribute. If yes, replace
       the value with ``[REDACTED]``.
    3. Loop until no more matches (handles inputs where the value attribute
       is followed by another sensitive attribute, which the previous
       single-pass regex missed).
    """
    if not html:
        return html

    # Tolerant input-tag regex: matches <input ... > with any combination
    # of single/double quotes and self-closing slash.
    input_tag_re = re.compile(
        r'(<input\b[^>]*?/?>)',
        re.IGNORECASE | re.DOTALL,
    )
    # Attribute parser: name="value" or name='value' (case-insensitive name).
    attr_re = re.compile(
        r'(\w+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')',
    )
    # Sensitive attribute-value patterns (lowercase comparison).
    sensitive_value_keywords = (
        "password", "secret", "token", "api_key", "apikey",
        "credential", "private_key", "client_secret", "access_token",
    )

    def _redact_input_tag(match: re.Match[str]) -> str:
        tag = match.group(1)
        # Parse all attributes in this tag.
        attrs: list[tuple[str, str]] = []
        for am in attr_re.finditer(tag):
            name = am.group(1).lower()
            value = am.group(2) if am.group(2) is not None else am.group(3)
            attrs.append((name, value))

        # Is this input sensitive? Check whether ANY attribute's value
        # contains a sensitive keyword (covers type=password, name=user_password,
        # id=secret_field, data-test=token_input, etc.).
        is_sensitive = any(
            any(kw in value.lower() for kw in sensitive_value_keywords)
            for _, value in attrs
        )
        if not is_sensitive:
            return tag

        # Find the value attribute (if any) and replace its content.
        # We rebuild the tag attribute-by-attribute so the original quote
        # style (single or double) is preserved.
        new_attrs: list[str] = []
        consumed = 0  # bytes consumed by attr_re matches
        for am in attr_re.finditer(tag):
            name = am.group(0).split("=", 1)[0].strip()
            value = am.group(2) if am.group(2) is not None else am.group(3)
            quote = '"' if am.group(2) is not None else "'"
            # Insert any text between previous match and this one.
            new_attrs.append(tag[consumed:am.start()])
            if name.lower() == "value":
                new_attrs.append(f'{name}={quote}[REDACTED]{quote}')
            else:
                new_attrs.append(am.group(0))
            consumed = am.end()
        new_attrs.append(tag[consumed:])  # trailing text after last attr
        return "".join(new_attrs)

    # Single pass is sufficient — _redact_input_tag handles the full tag.
    redacted = input_tag_re.sub(_redact_input_tag, html)
    return redact_string(redacted)

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
