from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Optional

import typer

from ocr_reconstructor import __version__
from ocr_reconstructor.config import AppConfig, VALID_EXPORT_FORMATS, load_app_config
from ocr_reconstructor.core.exceptions import ConfigError, OcrDocError
from ocr_reconstructor.pipeline import Pipeline, StageSummary
from ocr_reconstructor.utils import logging as log


def _configure_stdout_utf8() -> None:
    for stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
        if stream is None or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            # Stream not reconfigurable (e.g. redirected to a file opened
            # with a fixed encoding); leave it unchanged.
            pass

app = typer.Typer(
    name="ocrdoc",
    help=(
        "OCR-first pipeline: images → OCR → AI reconstruction → "
        "Markdown → DOCX/PDF."
    ),
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

languages_app = typer.Typer(
    help="Inspect PaddleOCR language support.",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(languages_app, name="languages")

ConfigOpt = Annotated[
    Optional[Path],
    typer.Option(
        "--config",
        help="Path to a YAML config file (default: ./config.yml if present).",
    ),
]
WorkspaceOpt = Annotated[
    Optional[Path],
    typer.Option("--workspace", help="Workspace directory (default: ./workspace)."),
]
InputOpt = Annotated[
    Optional[Path],
    typer.Option("--input", help="Input directory with images (default: <workspace>/input)."),
]
VerboseOpt = Annotated[
    Optional[bool],
    typer.Option("--verbose/--quiet", help="Enable debug logging."),
]
LangOpt = Annotated[
    Optional[str],
    typer.Option(
        "--lang",
        help="OCR language: a PaddleOCR code (en, id, ch, ...) or a language "
        "hint for vision engines.",
    ),
]
DeviceOpt = Annotated[
    Optional[str],
    typer.Option(
        "--device",
        help="OCR compute device: auto (GPU when CUDA is available), gpu, or cpu (PaddleOCR only).",
    ),
]
EngineOpt = Annotated[
    Optional[str],
    typer.Option(
        "--engine",
        help=(
            "OCR engine: paddleocr (local, default), openai (vision), or "
            "openai_compatible (vision). NOTE: anything other than "
            "paddleocr transcribes images with the ai.model, so that model "
            "MUST support vision."
        ),
    ),
]
ProviderOpt = Annotated[
    Optional[str],
    typer.Option("--provider", help="AI provider name (openai, openai_compatible, passthrough)."),
]
ModelOpt = Annotated[
    Optional[str],
    typer.Option(
        "--model",
        help=(
            "Model override for both vision OCR and reconstruction "
            "(provider default when omitted). Must support vision when an "
            "OCR engine other than paddleocr is used."
        ),
    ),
]
SkillOpt = Annotated[
    Optional[str],
    typer.Option(
        "--skill",
        help="Skill name(s) applied to every AI request, comma-separated to "
        "pair more than one (default: 'default'), e.g. --skill skill1,default.",
    ),
]
EffortOpt = Annotated[
    Optional[str],
    typer.Option(
        "--effort",
        "--reasoning-effort",
        help="Reasoning effort for reasoning models: minimal|low|medium|high|none.",
    ),
]
MaxTokensOpt = Annotated[
    Optional[int],
    typer.Option("--max-tokens", help="Maximum completion tokens per page request."),
]
FormatOpt = Annotated[
    Optional[str],
    typer.Option("--format", help="Export format(s), comma-separated: docx,pdf."),
]
PreprocessOpt = Annotated[
    Optional[bool],
    typer.Option("--preprocess/--no-preprocess", help="Preprocess images before OCR."),
]
ForceOpt = Annotated[
    bool,
    typer.Option("--force", help="Re-run stages even when cached results exist."),
]
WatermarkOpt = Annotated[
    Optional[str],
    typer.Option("--watermark", help='Watermark text, e.g. "DRAFT" (enables watermark).'),
]


def _fail(stage: str, exc: OcrDocError) -> None:
    log.error(stage, str(exc))
    raise typer.Exit(code=1)


def _load_config(
    config: Optional[Path], overrides: dict
) -> AppConfig:
    try:
        cfg = load_app_config(config_path=config, cli_overrides=overrides)
    except OcrDocError as exc:
        _fail("CONFIG", exc)
    log.configure(cfg.verbose)
    return cfg


def _path_or_none(value: Optional[Path]) -> Optional[str]:
    return str(value) if value is not None else None


def _parse_formats(value: Optional[str]) -> Optional[list[str]]:
    if value is None:
        return None
    formats = [part.strip().lower() for part in value.split(",") if part.strip()]
    invalid = [f for f in formats if f not in VALID_EXPORT_FORMATS]
    if invalid or not formats:
        _fail(
            "CONFIG",
            ConfigError(
                f"Invalid export format(s): {', '.join(invalid or ['(empty)'])}",
                f"Allowed: {', '.join(sorted(VALID_EXPORT_FORMATS))} "
                "(comma-separated for multiple).",
            ),
        )
    return formats


def _parse_skill_list(
    value: Optional[str], option: str = "--skill"
) -> Optional[list[str]]:
    if value is None:
        return None
    names: list[str] = []
    for part in value.split(","):
        name = part.strip()
        if name and name not in names:
            names.append(name)
    if not names:
        _fail(
            "CONFIG",
            ConfigError(
                f"{option} needs at least one skill name.",
                f"Example: {option} skill1,skill2 "
                "(comma-separated, more than one allowed).",
            ),
        )
    return names


def _exit_if_failed(stage: str, summary: StageSummary) -> None:
    if summary.failed:
        log.error(
            stage,
            f"{summary.failed} page(s) failed — see errors above and "
            "workspace/manifest.json for details.",
        )
        raise typer.Exit(code=1)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", help="Show the version and exit.")
    ] = False,
) -> None:
    if version:
        typer.echo(f"ocrdoc {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())
        raise typer.Exit()


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

@app.command()
def scan(
    input: InputOpt = None,
    workspace: WorkspaceOpt = None,
    config: ConfigOpt = None,
    verbose: VerboseOpt = None,
) -> None:
    cfg = _load_config(
        config,
        {"input": _path_or_none(input), "workspace": _path_or_none(workspace), "verbose": verbose},
    )
    from ocr_reconstructor.imaging.scanner import scan_images

    try:
        result = scan_images(cfg.input_dir)
    except OcrDocError as exc:
        _fail("SCAN", exc)
    log.info("SCAN", f"input={cfg.input_dir} — {len(result.assets)} image(s) found")
    for asset in result.assets:
        typer.echo(
            f"  {asset.sequence:>4}  {asset.relative_path}  "
            f"({asset.size_bytes} bytes, sha256:{asset.sha256[:12]})"
        )
    for relative, reason in result.invalid:
        log.warn("SCAN", f"invalid: {relative} — {reason}")


# ---------------------------------------------------------------------------
# languages
# ---------------------------------------------------------------------------

def _list_language_codes() -> None:
    from ocr_reconstructor.ocr.languages import supported_language_codes

    try:
        codes = supported_language_codes()
    except OcrDocError as exc:
        _fail("OCR", exc)
    log.info("OCR", f"PaddleOCR supported languages ({len(codes)}):")
    for code in sorted(codes):
        typer.echo(f"  {code}")
    typer.echo(
        "Recognition models download automatically on first use. "
        "Use with: ocrdoc ocr --lang <code>"
    )


@languages_app.callback()
def languages_callback(ctx: typer.Context) -> None:
    if ctx.invoked_subcommand is None:
        _list_language_codes()


@languages_app.command("list")
def languages_list() -> None:
    _list_language_codes()


@languages_app.command("check")
def languages_check(
    lang: Annotated[str, typer.Option("--lang", help="Language spec to validate, e.g. id+en.")],
) -> None:
    from ocr_reconstructor.ocr.languages import (
        supported_language_codes,
        validate_language_spec,
    )

    try:
        validated = validate_language_spec(lang, supported_language_codes())
    except OcrDocError as exc:
        _fail("OCR", exc)
    log.info("OCR", f"language spec OK: {lang} → {'+'.join(validated)}")


# ---------------------------------------------------------------------------
# ocr
# ---------------------------------------------------------------------------

@app.command()
def ocr(
    input: InputOpt = None,
    workspace: WorkspaceOpt = None,
    lang: LangOpt = None,
    engine: EngineOpt = None,
    model: ModelOpt = None,
    skill: SkillOpt = None,
    effort: EffortOpt = None,
    max_tokens: MaxTokensOpt = None,
    device: DeviceOpt = None,
    preprocess: PreprocessOpt = None,
    force: ForceOpt = False,
    config: ConfigOpt = None,
    verbose: VerboseOpt = None,
) -> None:
    cfg = _load_config(
        config,
        {
            "input": _path_or_none(input),
            "workspace": _path_or_none(workspace),
            "ocr.language": lang,
            "ocr.engine": engine,
            "ai.model": model,
            "ai.skill": _parse_skill_list(skill, "--skill"),
            "ai.reasoning_effort": effort,
            "ai.max_tokens": max_tokens,
            "ocr.device": device,
            "preprocessing.enabled": preprocess,
            "verbose": verbose,
        },
    )
    try:
        summary = Pipeline(cfg).run_ocr(force=force)
    except OcrDocError as exc:
        _fail("OCR", exc)
    _exit_if_failed("OCR", summary)


# ---------------------------------------------------------------------------
# reconstruct
# ---------------------------------------------------------------------------

@app.command()
def reconstruct(
    workspace: WorkspaceOpt = None,
    provider: ProviderOpt = None,
    model: ModelOpt = None,
    skill: SkillOpt = None,
    effort: EffortOpt = None,
    max_tokens: MaxTokensOpt = None,
    force: ForceOpt = False,
    config: ConfigOpt = None,
    verbose: VerboseOpt = None,
) -> None:
    cfg = _load_config(
        config,
        {
            "workspace": _path_or_none(workspace),
            "ai.provider": provider,
            "ai.model": model,
            "ai.skill": _parse_skill_list(skill, "--skill"),
            "ai.reasoning_effort": effort,
            "ai.max_tokens": max_tokens,
            "verbose": verbose,
        },
    )
    try:
        summary = Pipeline(cfg).run_reconstruction(force=force)
    except OcrDocError as exc:
        _fail("AI", exc)
    _exit_if_failed("AI", summary)


# ---------------------------------------------------------------------------
# assemble
# ---------------------------------------------------------------------------

@app.command()
def assemble(
    workspace: WorkspaceOpt = None,
    config: ConfigOpt = None,
    verbose: VerboseOpt = None,
) -> None:
    cfg = _load_config(
        config,
        {"workspace": _path_or_none(workspace), "verbose": verbose},
    )
    try:
        report = Pipeline(cfg).assemble()
    except OcrDocError as exc:
        _fail("ASSEMBLY", exc)
    log.info("ASSEMBLY", f"pages {report.pages[0]}–{report.pages[-1]} → {report.output_path}")


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------

@app.command()
def export(
    workspace: WorkspaceOpt = None,
    format: FormatOpt = None,
    watermark: WatermarkOpt = None,
    watermark_position: Annotated[
        Optional[str],
        typer.Option(
            help=(
                "Watermark position: center, horizontal, vertical, diagonal, "
                "tile, top-left, top, top-right, left, right, bottom-left, "
                "bottom, bottom-right."
            ),
        ),
    ] = None,
    watermark_size: Annotated[
        Optional[int], typer.Option(help="Watermark font size (pt).")
    ] = None,
    watermark_opacity: Annotated[
        Optional[float], typer.Option(help="Watermark opacity, 0–1.")
    ] = None,
    watermark_rotation: Annotated[
        Optional[int], typer.Option(help="Watermark rotation in degrees.")
    ] = None,
    config: ConfigOpt = None,
    verbose: VerboseOpt = None,
) -> None:
    overrides: dict = {
        "workspace": _path_or_none(workspace),
        "verbose": verbose,
        "export.formats": _parse_formats(format),
    }
    if watermark is not None:
        overrides["export.watermark.enabled"] = True
        overrides["export.watermark.text"] = watermark
    if watermark_position is not None:
        overrides["export.watermark.position"] = watermark_position
    if watermark_size is not None:
        overrides["export.watermark.font_size"] = watermark_size
    if watermark_opacity is not None:
        overrides["export.watermark.opacity"] = watermark_opacity
    if watermark_rotation is not None:
        overrides["export.watermark.rotation"] = watermark_rotation
    cfg = _load_config(config, overrides)

    try:
        outputs = Pipeline(cfg).export(watermark_text=None)
    except OcrDocError as exc:
        _fail("EXPORT", exc)
    for path in outputs:
        typer.echo(f"[EXPORT] wrote {path}")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@app.command()
def run(
    input: InputOpt = None,
    workspace: WorkspaceOpt = None,
    lang: LangOpt = None,
    engine: EngineOpt = None,
    model: ModelOpt = None,
    skill: SkillOpt = None,
    effort: EffortOpt = None,
    max_tokens: MaxTokensOpt = None,
    format: FormatOpt = None,
    watermark: WatermarkOpt = None,
    device: DeviceOpt = None,
    preprocess: PreprocessOpt = None,
    provider: ProviderOpt = None,
    force: ForceOpt = False,
    config: ConfigOpt = None,
    verbose: VerboseOpt = None,
) -> None:
    overrides: dict = {
        "input": _path_or_none(input),
        "workspace": _path_or_none(workspace),
        "ocr.language": lang,
        "ocr.engine": engine,
        "ai.model": model,
        "ai.skill": _parse_skill_list(skill, "--skill"),
        "ai.reasoning_effort": effort,
        "ai.max_tokens": max_tokens,
        "ocr.device": device,
        "preprocessing.enabled": preprocess,
        "ai.provider": provider,
        "export.formats": _parse_formats(format),
        "verbose": verbose,
    }
    if watermark is not None:
        overrides["export.watermark.enabled"] = True
        overrides["export.watermark.text"] = watermark
    cfg = _load_config(config, overrides)

    try:
        report = Pipeline(cfg).run(force=force)
    except OcrDocError as exc:
        _fail("RUN", exc)
    log.info(
        "RUN",
        f"finished: {report.assets} image(s), OCR {report.ocr.ok}/{report.ocr.total}, "
        f"AI {report.ai.ok}/{report.ai.total}, {report.pages} page(s) assembled",
    )
    for path in report.outputs:
        typer.echo(f"[EXPORT] wrote {path}")


def main() -> None:
    _configure_stdout_utf8()
    app()


if __name__ == "__main__":
    main()
