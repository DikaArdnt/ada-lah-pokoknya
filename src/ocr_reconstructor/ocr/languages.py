from __future__ import annotations

from ocr_reconstructor.core.exceptions import (
    ConfigError,
    LanguageNotAvailableError,
    PaddleOcrNotAvailableError,
)

_FALLBACK_SUPPORTED_LANGUAGES: set[str] = {
    "af", "az", "bs", "ca", "ch", "chinese_cht", "cs", "cy", "da", "de",
    "en", "es", "et", "eu", "fi", "fr", "french", "ga", "german", "gl",
    "hr", "hu", "id", "is", "it", "japan", "ku", "la", "lb", "lt", "lv",
    "mi", "ms", "mt", "nl", "no", "oc", "pl", "pt", "qu", "rm", "ro",
    "rs_latin", "sk", "sl", "sq", "sv", "sw", "tl", "tr", "uz", "vi",
}


def _discover_language_codes(paddleocr) -> set[str] | None:
    modules = [getattr(paddleocr, "_common", None)]
    ppocr = getattr(paddleocr, "ppocr", None)
    if ppocr is not None:
        utility = getattr(getattr(ppocr, "utils", None), "utility", None)
        modules.append(utility)

    for mod in modules:
        if mod is None:
            continue
        for name in (
            "get_supported_language_list",
            "get_support_language_list",
            "_get_support_language_list",
        ):
            fn = getattr(mod, name, None)
            if not callable(fn):
                continue
            try:
                codes = fn()
            except Exception:
                continue
            if codes:
                return {str(code).strip().lower() for code in codes if str(code).strip()}
    return None


def supported_language_codes() -> set[str]:
    """Language codes supported by the installed PaddleOCR.

    Raises PaddleOcrNotAvailableError when paddleocr cannot be imported.
    """
    try:
        import paddleocr
    except ImportError as exc:
        raise PaddleOcrNotAvailableError() from exc

    codes = _discover_language_codes(paddleocr)
    if codes:
        return codes
    return set(_FALLBACK_SUPPORTED_LANGUAGES)


def parse_language_spec(spec: str) -> list[str]:
    """Parse a language spec into PaddleOCR codes.

    A single code is expected (e.g. ``en`` or ``id``). ``+``-joined specs
    are still parsed so a multi-language request produces a clear error from
    :func:`validate_language_spec`; PaddleOCR has no multi-language mode.
    """
    parts = [part.strip().lower() for part in spec.split("+") if part.strip()]
    if not parts:
        raise ConfigError(
            f"Invalid language spec: {spec!r}",
            "Use a single PaddleOCR language code, e.g. en or id.",
        )
    return list(dict.fromkeys(parts))


def validate_language_spec(spec: str, supported: set[str]) -> list[str]:
    """Validate *spec* against *supported* codes; raise when unavailable.

    Returns the validated PaddleOCR codes (exactly one for a valid spec).
    """
    requested = parse_language_spec(spec)
    missing = [lang for lang in requested if lang not in supported]
    if missing:
        raise LanguageNotAvailableError(
            f"Language not supported by this PaddleOCR build: "
            f"{', '.join(missing)}",
            "Run `ocrdoc languages list` for supported codes (e.g. en, id, ch).",
        )
    if len(requested) > 1:
        raise ConfigError(
            f"PaddleOCR supports one language model per run, got: "
            f"{'+'.join(requested)}",
            "Pass a single language code (e.g. --lang id). PaddleOCR has no "
            "'+'-joined multi-language mode; pick the document's primary "
            "language.",
        )
    return requested