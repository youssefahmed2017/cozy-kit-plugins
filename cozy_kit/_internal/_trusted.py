_AUTHOR_TOKEN = "yOdEV198.author(owner)363"
_AUTHOR_DISPLAY = "Youssef Ahmed (owner/author)"


def resolve_author(raw: str) -> tuple[str, bool]:
    """
    Return (display_author, is_trusted).
    If raw matches the trusted token, returns the public display name and True.
    Otherwise returns raw unchanged and False.
    """
    if raw == _AUTHOR_TOKEN:
        return _AUTHOR_DISPLAY, True
    return raw, False
