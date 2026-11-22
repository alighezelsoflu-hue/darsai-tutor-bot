"""Text shown to students, in every interface language.

The strings live in en.py and fa.py (one dict each, same keys). Look them up with t().
"""

from typing import Optional

from . import en, fa

UI_LANGUAGES = ("en", "fa")
DEFAULT_LANGUAGE = "en"
# Each language's name written in that language, so it is recognisable in any interface language.
LANGUAGE_NAMES = {"en": "English", "fa": "فارسی"}
RTL_LANGUAGES = frozenset({"fa"})

STRINGS = {"en": en.STRINGS, "fa": fa.STRINGS}

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def detect_language(telegram_language_code: Optional[str]) -> str:
    """Pick an interface language from Telegram's language code (e.g. "fa", "fa-IR", "en-US")."""
    code = (telegram_language_code or "").lower()
    return "fa" if code.startswith("fa") else DEFAULT_LANGUAGE


def is_rtl(lang: str) -> bool:
    return lang in RTL_LANGUAGES


def t(lang: str, key: str, **params) -> str:
    """The string for key in lang, falling back to English. Raises KeyError for unknown keys."""
    text = STRINGS.get(lang, {}).get(key)
    if text is None:
        text = STRINGS[DEFAULT_LANGUAGE][key]
    return text.format(**params) if params else text


def local_digits(lang: str, value) -> str:
    """Write a number in the interface language's digits (prose only, never inside formulas)."""
    text = str(value)
    return text.translate(_PERSIAN_DIGITS) if lang == "fa" else text


def level_label(lang: str, level: str) -> str:
    try:
        return t(lang, f"level.{level}")
    except KeyError:
        return level
