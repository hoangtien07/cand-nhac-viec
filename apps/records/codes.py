"""Normalization of user-entered reference codes (số hiệu). See CONTEXT.md §H — ASSUMPTION I01."""

import re
import unicodedata

MAX_CODE_LENGTH = 64
_ALLOWED = re.compile(r"^[\w\-/.]+( [\w\-/.]+)*$")


class InvalidCode(ValueError):
    pass


def clean_display_code(raw):
    """Return the code as it should be displayed: NFC, trimmed, inner whitespace collapsed."""
    if raw is None:
        raise InvalidCode("Vui lòng nhập số hiệu.")
    text = unicodedata.normalize("NFC", str(raw))
    if any(unicodedata.category(ch).startswith("C") and ch not in " \t" for ch in text):
        raise InvalidCode("Số hiệu chứa ký tự không hợp lệ.")
    text = " ".join(text.split())
    if not text:
        raise InvalidCode("Vui lòng nhập số hiệu.")
    if len(text) > MAX_CODE_LENGTH:
        raise InvalidCode(f"Số hiệu tối đa {MAX_CODE_LENGTH} ký tự.")
    if not _ALLOWED.match(text):
        raise InvalidCode("Số hiệu chỉ gồm chữ, số, dấu cách và các ký tự - / . _")
    return text


def normalize_code(raw):
    """Comparison key: NFKC + casefold + collapsed whitespace. 'kq-2026-001 ' == 'KQ-2026-001'."""
    display = clean_display_code(raw)
    return " ".join(unicodedata.normalize("NFKC", display).casefold().split())
