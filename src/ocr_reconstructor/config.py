from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ocr_reconstructor.core.exceptions import ConfigError

VALID_OCR_FORMATS = {"md", "txt"}
VALID_EXPORT_FORMATS = {"docx", "pdf"}
VALID_WATERMARK_POSITIONS = {
    "center",
    "horizontal",
    "vertical",
    "diagonal",
    "tile",
    "top-left",
    "top",
    "top-right",
    "left",
    "right",
    "bottom-left",
    "bottom",
    "bottom-right",
}
VALID_REASONING_EFFORTS = {"minimal", "low", "medium", "high", "none"}
VALID_OCR_DEVICES = {"auto", "gpu", "cpu"}
VALID_OCR_ENGINES = {"paddleocr", "openai", "openai_compatible"}


@dataclass
class WatermarkConfig:
    enabled: bool = False
    text: str = "DRAFT"
    position: str = (  # see VALID_WATERMARK_POSITIONS
        "center"
    )
    font_size: int = 48
    opacity: float = 0.15
    rotation: int = 45  # degrees, applied by the diagonal position


@dataclass
class PreprocessConfig:
    enabled: bool = False
    grayscale: bool = True
    autocontrast: bool = True
    upscale: int = 1  # 1 = disabled
    binarize: bool = False  # Otsu threshold (forces grayscale)


@dataclass
class OCRConfig:
    engine: str = "paddleocr"  # paddleocr | openai | openai_compatible
    language: str = "en"  # PaddleOCR code, or a language hint for vision engines
    output_format: str = "md"  # md | txt
    device: str = "auto"  # auto | gpu | cpu (PaddleOCR only)
    enable_mkldnn: bool = False  # oneDNN; off by default (PaddlePaddle bug)


@dataclass
class AIConfig:
    provider: str = "openai"
    model: str | None = None  # must support vision when ocr.engine != paddleocr
    skills: list[str] = field(default_factory=lambda: ["default"])  # paired skills; more than one allowed
    temperature: float = 0.1  # sampling temperature for every AI request
    reasoning_effort: str | None = None  # reasoning models only (o-series, gpt-5…)
    context_chars: int = 800  # tail of previous page passed as context
    max_tokens: int | None = None  # shared by every AI request
    base_url: str | None = None  # shared endpoint root of the hosted model
    extra_headers: dict[str, str] | None = None  # default HTTP headers for the provider
    timeout: float = 120.0  # per-request timeout (seconds)
    max_retries: int = 2  # SDK-level retries on transient errors
    api_key: str | None = None  # shared key; never logged

    @property
    def skill(self) -> str:
        return self.skills[0] if self.skills else ""


@dataclass
class ExportConfig:
    formats: list[str] = field(default_factory=lambda: ["docx"])
    watermark: WatermarkConfig = field(default_factory=WatermarkConfig)


@dataclass
class AppConfig:
    workspace: Path = Path("./workspace")
    input_dir: Path = Path("./workspace/input")
    skills_dir: Path = Path("./skills")
    ocr: OCRConfig = field(default_factory=OCRConfig)
    preprocessing: PreprocessConfig = field(default_factory=PreprocessConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    export: ExportConfig = field(default_factory=ExportConfig)
    verbose: bool = False

    # Derived workspace locations
    @property
    def preprocessed_dir(self) -> Path:
        return self.workspace / "preprocessed"

    @property
    def ocr_dir(self) -> Path:
        return self.workspace / "ocr"

    @property
    def reconstructed_dir(self) -> Path:
        return self.workspace / "reconstructed"

    @property
    def output_dir(self) -> Path:
        return self.workspace / "output"

    @property
    def document_md(self) -> Path:
        return self.output_dir / "document.md"

    @property
    def manifest_path(self) -> Path:
        return self.workspace / "manifest.json"


def _defaults() -> dict:
    return {
        "workspace": "./workspace",
        "input": None,  # resolved to <workspace>/input when not set
        "skills_dir": "./skills",
        "ocr": {
            "engine": "paddleocr",
            "language": "en",
            "output_format": "md",
            "device": "auto",
            "enable_mkldnn": False,
        },
        "preprocessing": {
            "enabled": False,
            "grayscale": True,
            "autocontrast": True,
            "upscale": 1,
            "binarize": False,
        },
        "ai": {
            "provider": "openai",
            "model": None,
            "skill": "default",
            "temperature": 0.1,
            "context_chars": 800,
            "reasoning_effort": None,
            "max_tokens": None,
            "base_url": None,
            "extra_headers": None,
            "timeout": 120.0,
            "max_retries": 2,
            "api_key": None,
        },
        "export": {
            "formats": ["docx"],
            "watermark": {
                "enabled": False,
                "text": "DRAFT",
                "position": "center",
                "font_size": 48,
                "opacity": 0.15,
                "rotation": 45,
            },
        },
        "verbose": False,
    }


def _load_yaml(path: Path | None) -> dict:
    if path is None:
        for candidate in (Path("config.yml"), Path("config.yaml")):
            if candidate.is_file():
                path = candidate
                break
        else:
            return {}
    if not path.is_file():
        raise ConfigError(
            f"Config file not found: {path}",
            "Check the --config path, or remove the option to use ./config.yml "
            "or built-in defaults.",
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in config file '{path}': {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"Config file '{path}' must contain a YAML mapping.")

    export = data.get("export")
    # Legacy spelling of the export list; 'formats' is documented and always wins.
    if isinstance(export, dict) and "format" in export and "formats" not in export:
        export["formats"] = export.pop("format")
    return data


def _deep_merge(base: dict, override: dict) -> None:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _set_dotted(raw: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    node = raw
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def _apply_cli_overrides(raw: dict, overrides: dict | None) -> None:
    for dotted, value in (overrides or {}).items():
        if value is not None:
            _set_dotted(raw, dotted, value)


def _choice(dotted: str, value, allowed: set[str], hint: str) -> str:
    normalized = str(value).strip().lower()
    if normalized not in allowed:
        message = f"Invalid {dotted}: {value!r}"
        hint_part = f"Allowed values: {', '.join(sorted(allowed))}."
        if hint:
            hint_part = f"{hint_part} {hint}"
        raise ConfigError(message, hint_part)
    return normalized


def _count_at_least(dotted: str, value, minimum: int) -> int | None:
    if value is None:
        return None
    number = int(value)
    if number < minimum:
        raise ConfigError(f"{dotted} must be >= {minimum}, got {number}.")
    return number


def _skill_names(
    value,
    dotted: str,
    *,
    allow_empty: bool = False,
    hint: str | None = None,
) -> list[str]:
    if isinstance(value, str):
        entries: list = [value]
    elif isinstance(value, (list, tuple)):
        entries = list(value)
    elif value is None:
        entries = []
    else:
        raise ConfigError(
            f"{dotted} must be a skill name or a YAML list of skill names, "
            f"got {type(value).__name__}.",
            hint,
        )
    names: list[str] = []
    for entry in entries:
        name = entry.strip() if isinstance(entry, str) else ""
        if not name:
            raise ConfigError(
                f"{dotted} entries must be non-empty skill names.",
                hint
                or "Each entry is a skill directory under skills/ "
                "(e.g. default, skill1).",
            )
        if name not in names:
            names.append(name)
    if not names and not allow_empty:
        raise ConfigError(
            f"{dotted} must name at least one skill.",
            hint
            or f"Set {dotted} in config.yml to a directory under skills/, "
            "or use a YAML list to pair several skills.",
        )
    return names


def _api_key(section: dict, dotted: str) -> str | None:
    value = section.get(dotted.rsplit(".", 1)[-1])
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ConfigError(
            f"{dotted} must be a string (or empty), got {type(value).__name__}.",
            f"Set the key in config.yml under {dotted.replace('.', ': ')}.",
        )
    return value.strip()


def _build_ocr(section: dict) -> OCRConfig:
    return OCRConfig(
        engine=_choice(
            "ocr.engine",
            section["engine"],
            VALID_OCR_ENGINES,
            "'paddleocr' runs locally; 'openai' and 'openai_compatible' use "
            "vision models through an OpenAI-style API — in that case "
            "ai.model must support vision.",
        ),
        language=str(section["language"]),
        output_format=_choice(
            "ocr.output_format",
            section["output_format"],
            VALID_OCR_FORMATS,
            "",
        ),
        device=_choice(
            "ocr.device",
            section["device"],
            VALID_OCR_DEVICES,
            "'auto' uses the GPU when a CUDA-enabled PaddlePaddle build and a "
            "GPU are available, otherwise it runs on the CPU.",
        ),
        enable_mkldnn=bool(section["enable_mkldnn"]),
    )


def _build_preprocessing(section: dict) -> PreprocessConfig:
    upscale = _count_at_least("preprocessing.upscale", section["upscale"], 1)
    return PreprocessConfig(
        enabled=bool(section["enabled"]),
        grayscale=bool(section["grayscale"]),
        autocontrast=bool(section["autocontrast"]),
        upscale=upscale or 1,
        binarize=bool(section["binarize"]),
    )


# Keys removed by the unified-AI refactor. Keeping them in config.yml used
# to be silently ignored; now they fail loudly with a migration hint.
_REMOVED_AI_KEYS: dict[str, str] = {
    "ocr_skill": (
        "use ai.skill instead — one list drives every request, "
        "e.g. ai.skill: [skill1, skill2]"
    ),
    "ocr_temperature": "use ai.temperature — one sampling setting for "
    "every AI request",
    "reconstruct": (
        "the hosted engines (ocr.engine: openai / openai_compatible) now "
        "always combine transcription and skills in one request; use "
        "ocr.engine: paddleocr for the two-step route"
    ),
}


def _reject_removed_ai_keys(section: dict) -> None:
    for key, migration in _REMOVED_AI_KEYS.items():
        if section.get(key) is None:
            continue
        raise ConfigError(
            f"ai.{key} was removed (unified AI processing).",
            f"Remove the key: {migration}.",
        )


def _build_ai(section: dict) -> AIConfig:
    _reject_removed_ai_keys(section)
    reasoning_effort = section["reasoning_effort"]
    if reasoning_effort is not None:
        reasoning_effort = _choice(
            "ai.reasoning_effort",
            reasoning_effort,
            VALID_REASONING_EFFORTS,
            "Leave it unset for non-reasoning models.",
        )
    extra_headers = section["extra_headers"]
    if extra_headers is not None:
        if not isinstance(extra_headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in extra_headers.items()
        ):
            raise ConfigError(
                "ai.extra_headers must be a mapping of header names to "
                "string values, e.g. {HTTP-Referer: 'https://myapp.dev'}."
            )
        extra_headers = dict(extra_headers)
    return AIConfig(
        provider=str(section["provider"]),
        model=section["model"],
        skills=_skill_names(
            section["skill"],
            "ai.skill",
            hint=(
                "ai.skill is a skill directory under skills/ or a YAML list "
                "of them, e.g. [skill1, skill2] — every listed skill is "
                "rendered in order into one request (CLI: --skill a,b)."
            ),
        ),
        temperature=float(section["temperature"]),
        context_chars=int(section["context_chars"]),
        reasoning_effort=reasoning_effort,
        max_tokens=_count_at_least("ai.max_tokens", section["max_tokens"], 1),
        base_url=section["base_url"],
        extra_headers=extra_headers,
        timeout=float(section["timeout"]),
        max_retries=int(section["max_retries"]),
        api_key=_api_key(section, "ai.api_key"),
    )


def _build_watermark(section: dict) -> WatermarkConfig:
    opacity = float(section["opacity"])
    if not 0.0 <= opacity <= 1.0:
        raise ConfigError(
            f"Watermark opacity must be between 0 and 1, got {opacity}.",
        )
    return WatermarkConfig(
        enabled=bool(section["enabled"]),
        text=str(section["text"]),
        position=_choice(
            "export.watermark.position",
            section["position"],
            VALID_WATERMARK_POSITIONS,
            "",
        ),
        font_size=int(section["font_size"]),
        opacity=opacity,
        rotation=int(section["rotation"]),
    )


def _build_export(section: dict) -> ExportConfig:
    formats = [str(name).lower() for name in section["formats"]]
    invalid = [name for name in formats if name not in VALID_EXPORT_FORMATS]
    if invalid:
        raise ConfigError(
            f"Invalid export format(s): {', '.join(invalid)}",
            f"Allowed values: {', '.join(sorted(VALID_EXPORT_FORMATS))} "
            "(comma-separated for multiple).",
        )
    return ExportConfig(
        formats=formats or ["docx"],
        watermark=_build_watermark(section["watermark"]),
    )


def _build_app(raw: dict) -> AppConfig:
    workspace = Path(str(raw["workspace"]))
    input_value = raw.get("input")
    return AppConfig(
        workspace=workspace,
        input_dir=Path(str(input_value)) if input_value else workspace / "input",
        skills_dir=Path(str(raw["skills_dir"])),
        ocr=_build_ocr(raw["ocr"]),
        preprocessing=_build_preprocessing(raw["preprocessing"]),
        ai=_build_ai(raw["ai"]),
        export=_build_export(raw["export"]),
        verbose=bool(raw["verbose"]),
    )


def load_app_config(
    config_path: Path | None = None,
    cli_overrides: dict | None = None,
) -> AppConfig:
    raw = _defaults()
    _deep_merge(raw, _load_yaml(config_path))
    _apply_cli_overrides(raw, cli_overrides)
    return _build_app(raw)
