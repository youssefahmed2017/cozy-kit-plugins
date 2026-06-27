import hashlib

# SHA-256 of the trusted author token — raw token is never stored in source.
_AUTHOR_TOKEN_HASH = "7ec88a2729867c6dc9af6d776565629c2fc55f671d9b216f7899b3382636ca24"
_AUTHOR_DISPLAY = "Youssef Ahmed (owner/author)"


def resolve_author(raw: str) -> tuple[str, bool]:
    """
    Return (display_author, is_trusted).
    Hashes the input and compares to the stored hash — the raw token never
    appears in this file.
    """
    h = hashlib.sha256(raw.encode()).hexdigest()
    if h == _AUTHOR_TOKEN_HASH:
        return _AUTHOR_DISPLAY, True
    return raw, False
