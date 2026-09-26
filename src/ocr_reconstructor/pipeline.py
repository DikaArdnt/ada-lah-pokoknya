from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Optional

from ocr_reconstructor.ai.base import AIProvider
from ocr_reconstructor.ai.registry import create_provider
from ocr_reconstructor.ai.reconstruction import (
    ReconstructionService,
    compute_cache_key,
)
from ocr_reconstructor.config import AppConfig
from ocr_reconstructor.core.exceptions import (
    AIProviderError,
    AssemblyError,
    ConfigError,
    InvalidAIResponseError,
    OcrDocError,
    SkillError,
)
from ocr_reconstructor.core.manifest import Manifest, utc_now_iso
from ocr_reconstructor.core.models import ImageAsset, PageRecord, Status, new_page_record
from ocr_reconstructor.documents.assembler import AssemblyReport, assemble_document
from ocr_reconstructor.documents.docx import export_docx
from ocr_reconstructor.documents.pdf import export_pdf
from ocr_reconstructor.imaging.preprocessing import preprocess_image
from ocr_reconstructor.imaging.scanner import ScanResult, scan_images
from ocr_reconstructor.ocr.base import OcrEngine, ocr_output_stem, write_ocr_output
from ocr_reconstructor.ocr.factory import (
    create_ocr_engine,
    uses_vision_engine,
)
from ocr_reconstructor.skills.registry import SkillRegistry
from ocr_reconstructor.utils import logging as log
from ocr_reconstructor.utils.filesystem import ensure_dir, read_text
from ocr_reconstructor.utils.hashing import sha256_text

ProviderFactory = Callable[[], AIProvider]


@dataclass
class StageSummary:
    stage: str
    ok: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def total(self) -> int:
        return self.ok + self.skipped + self.failed


@dataclass
class PipelineReport:
    assets: int
    ocr: StageSummary
    ai: StageSummary
    pages: int
    outputs: list[Path] = field(default_factory=list)


class Pipeline:
    def __init__(
        self,
        config: AppConfig,
        provider_factory: Optional[ProviderFactory] = None,
    ) -> None:
        self.config = config
        self.skills = SkillRegistry(config.skills_dir)
        self.manifest = Manifest.load(config.manifest_path)
        self._provider_factory = provider_factory

    # -- helpers -------------------------------------------------------------

    def _workspace_relative(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.config.workspace.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def _make_provider(self) -> AIProvider:
        if self._provider_factory is not None:
            return self._provider_factory()
        return create_provider(
            self.config.ai.provider,
            model=self.config.ai.model,
            api_key=self.config.ai.api_key,
            base_url=self.config.ai.base_url,
            timeout=self.config.ai.timeout,
            max_retries=self.config.ai.max_retries,
            extra_headers=self.config.ai.extra_headers,
        )

    # -- stage: scan ----------------------------------------------------------

    def scan(self) -> ScanResult:
        cfg = self.config
        log.info("SCAN", f"input={cfg.input_dir}")
        result = scan_images(cfg.input_dir)

        now = utc_now_iso()
        for relative, reason in result.invalid:
            record = self.manifest.get(relative)
            if record is None:
                record = PageRecord(
                    source=relative,
                    sequence=0,  # 0 marks a non-processable asset
                    sha256="",
                    created_at=now,
                    updated_at=now,
                    filename=Path(relative).name,
                )
            record.record_error("SCAN", reason)
            self.manifest.upsert(record)
            log.warn("SCAN", f"invalid image skipped: {relative} ({reason})")

        for asset in result.assets:
            record = self.manifest.get(asset.relative_path)
            if record is None:
                record = new_page_record(asset, now)
                log.debug("SCAN", f"new page: {asset.relative_path}")
            else:
                record.sequence = asset.sequence
                record.size_bytes = asset.size_bytes
                if record.sha256 != asset.sha256:
                    log.info("SCAN", f"source changed, stages reset: {asset.relative_path}")
                    record = new_page_record(asset, now)
            self.manifest.upsert(record)

        self.manifest.save()
        log.info(
            "SCAN",
            f"{len(result.assets)} image(s) discovered, "
            f"{len(result.invalid)} invalid, "
            f"manifest: {cfg.manifest_path}",
        )
        return result

    # -- stage: OCR -------------------------------------------------------------

    def run_ocr(
        self, assets: list[ImageAsset] | None = None, force: bool = False
    ) -> StageSummary:
        cfg = self.config
        summary = StageSummary("OCR")

        if assets is None:
            assets = self.scan().assets
        if not assets:
            log.warn("OCR", "no images to process")
            return summary

        # Both routes run ONE AI request per page through the shared
        # service. The hosted engines combine transcription + skills in
        # that request, so the response already is the reconstructed page
        # and the separate AI stage skips those pages. The self-hosted
        # engine (paddleocr) runs OCR locally, then repairs the text.
        combined = uses_vision_engine(cfg)
        combined_skills = list(cfg.ai.skills) if combined else []

        log.info(
            "OCR",
            f"engine={cfg.ocr.engine} lang={cfg.ocr.language} "
            f"device={cfg.ocr.device} "
            f"preprocessing={'on' if cfg.preprocessing.enabled else 'off'} "
            f"mkldnn={'on' if cfg.ocr.enable_mkldnn else 'off'} "
            f"format={cfg.ocr.output_format} "
            f"route={"single AI request per image" if combined else "local OCR + separate AI request"}" +
            (f" skills={'+'.join(combined_skills)}" if combined_skills else ""),
        )

        engine: OcrEngine | None = None

        def get_engine() -> OcrEngine:
            nonlocal engine
            if engine is None:
                # The pipeline's provider (real or injected) serves both
                # the OCR and the AI stage.
                engine = create_ocr_engine(cfg, self.skills, self._make_provider)
            return engine

        ensure_dir(cfg.ocr_dir)
        if cfg.preprocessing.enabled:
            ensure_dir(cfg.preprocessed_dir)
        if combined:
            # Combined mode writes reconstructed pages during OCR too.
            ensure_dir(cfg.reconstructed_dir)

        all_relative = [asset.relative_path for asset in assets]
        stems = {rel: ocr_output_stem(rel, all_relative) for rel in all_relative}

        for index, asset in enumerate(assets, start=1):
            record = self.manifest.get(asset.relative_path)
            if record is None:
                record = new_page_record(asset, utc_now_iso())

            stem = stems[asset.relative_path]
            ocr_path = cfg.ocr_dir / f"{stem}.{cfg.ocr.output_format}"
            ocr_relative = self._workspace_relative(ocr_path)

            if (
                not force
                and record.ocr_status == Status.DONE.value
                and record.ocr_file == ocr_relative
                and ocr_path.is_file()
            ):
                summary.skipped += 1
                log.progress("OCR", index, len(assets), f"{asset.filename} → skipped (already done)")
                self.manifest.upsert(record)
                continue

            if engine is None:
                # Validation/init failures here are stage-wide and
                # propagate to the CLI (reported once, stage aborted).
                engine = get_engine()

            source_path = asset.path
            if cfg.preprocessing.enabled:
                preprocessed_path = cfg.preprocessed_dir / f"{stem}.png"
                try:
                    preprocess_image(asset.path, preprocessed_path, cfg.preprocessing)
                    source_path = preprocessed_path
                except OcrDocError as exc:
                    record.ocr_status = Status.ERROR.value
                    record.record_error("OCR", exc.message)
                    self.manifest.upsert(record)
                    summary.failed += 1
                    log.error("OCR", f"{asset.filename}: {exc}")
                    continue

            try:
                ocr_result = engine.run(source_path)
                write_ocr_output(ocr_path, ocr_result.text)
                record.ocr_status = Status.DONE.value
                record.ocr_file = ocr_relative
                record.ocr_language = ocr_result.language
                record.ocr_sha256 = sha256_text(ocr_result.text)
                record.ocr_finished_at = utc_now_iso()
                record.clear_errors("OCR")
                summary.ok += 1
                progress_note = f"{asset.filename} → {len(ocr_result.text)} chars"
                if combined:
                    # The hosted response already went through every skill,
                    # so it is the reconstructed page too — persist it and
                    # mark the page done for the AI stage.
                    reconstructed_path = (
                        cfg.reconstructed_dir / f"{record.sequence:03d}.md"
                    )
                    reconstructed_path.write_text(ocr_result.text, encoding="utf-8")
                    record.ai_status = Status.DONE.value
                    record.ai_provider = cfg.ocr.engine
                    record.ai_model = getattr(engine, "model", None)
                    record.ai_skill = " + ".join(combined_skills)
                    record.ai_cache_key = None
                    record.ai_combined = True
                    record.reconstructed_file = self._workspace_relative(
                        reconstructed_path
                    )
                    record.ai_finished_at = utc_now_iso()
                    record.clear_errors("AI")
                    progress_note += " · image + skills in one request"
                log.progress(
                    "OCR",
                    index,
                    len(assets),
                    progress_note,
                )
            except OcrDocError as exc:
                record.ocr_status = Status.ERROR.value
                record.record_error("OCR", exc.message)
                summary.failed += 1
                log.error("OCR", f"{asset.filename}: {exc}")
                if isinstance(exc, AIProviderError) and not isinstance(
                    exc, InvalidAIResponseError
                ):
                    # Provider-level failure (missing key, endpoint
                    # unreachable, rate limit, timeout): every remaining
                    # image fails identically — abort instead of retrying.
                    self.manifest.upsert(record)
                    self.manifest.save()
                    raise
            finally:
                self.manifest.upsert(record)

        self.manifest.save()
        log.info(
            "OCR",
            f"{summary.ok} ok, {summary.skipped} skipped, {summary.failed} failed",
        )
        return summary

    # -- stage: AI reconstruction --------------------------------------------------

    def _page_text_for_context(self, record: PageRecord) -> str | None:
        cfg = self.config
        if record.reconstructed_file:
            path = cfg.workspace / record.reconstructed_file
            if path.is_file():
                return read_text(path)
        if record.ocr_file:
            path = cfg.workspace / record.ocr_file
            if path.is_file():
                return read_text(path)
        return None

    def run_reconstruction(self, force: bool = False) -> StageSummary:
        cfg = self.config
        summary = StageSummary("AI")

        records = [r for r in self.manifest.records() if r.sequence > 0]
        ready = [r for r in records if r.ocr_status == Status.DONE.value and r.ocr_file]
        if not ready:
            log.warn("AI", "no pages with completed OCR — run `ocrdoc ocr` first")
            return summary

        if not cfg.ai.skills:
            raise ConfigError(
                "ai.skill must name at least one reconstruction skill.",
                "Set ai.skill in config.yml (a YAML list pairs several "
                "skills) or pass --skill a,b.",
            )
        try:
            # Every paired skill is resolved up front so a missing skill
            # aborts the stage before any request is sent.
            skills = [self.skills.get(name) for name in cfg.ai.skills]
        except SkillError as exc:
            log.error("AI", str(exc))
            raise

        ensure_dir(cfg.reconstructed_dir)

        # OCR text per page; drop pages whose OCR file vanished.
        working: dict[str, str] = {}
        for record in ready:
            ocr_path = cfg.workspace / record.ocr_file  # type: ignore[operator]
            if not ocr_path.is_file():
                record.ai_status = Status.ERROR.value
                record.record_error("AI", f"OCR output file missing: {record.ocr_file}")
                self.manifest.upsert(record)
                summary.failed += 1
                log.error("AI", f"{record.source}: OCR output file missing")
            else:
                working[record.source] = read_text(ocr_path)

        if not working:
            self.manifest.save()
            return summary

        log.info(
            "AI",
            f"provider={cfg.ai.provider} model={cfg.ai.model or '(provider default)'} "
            f"skill={'+'.join(one.name for one in skills)} pages={len(working)}",
        )

        provider: AIProvider | None = None
        service: ReconstructionService | None = None
        # A page produced by a single image request in the OCR stage stays
        # valid only while the OCR stage still routes through a hosted
        # engine; switching back to paddleocr must re-run that page.
        combined_now = uses_vision_engine(self.config)

        def context_of(record: PageRecord) -> str | None:
            text = self._page_text_for_context(record)
            if text is None:
                return None
            tail = text.strip()[-cfg.ai.context_chars :]
            return tail or None

        prev_tail: str | None = None
        index = 0
        for record in records:
            ocr_text = working.get(record.source)
            if ocr_text is None:
                # Page not ready (OCR pending/failed) — reset context chain.
                prev_tail = None
                continue

            index += 1
            reconstructed_path = cfg.reconstructed_dir / f"{record.sequence:03d}.md"
            reconstructed_relative = self._workspace_relative(reconstructed_path)
            cache_key = compute_cache_key(
                provider_name=cfg.ai.provider,
                model=cfg.ai.model or "",
                skill=skills,
                ocr_text=ocr_text,
                previous_tail=prev_tail,
                request_params={
                    "temperature": cfg.ai.temperature,
                    "reasoning_effort": cfg.ai.reasoning_effort,
                    "max_tokens": cfg.ai.max_tokens,
                },
            )

            if (
                not force
                and record.ai_status == Status.DONE.value
                and reconstructed_path.is_file()
                and (
                    record.ai_cache_key == cache_key
                    or (record.ai_combined and combined_now)
                )
            ):
                summary.skipped += 1
                reason = (
                    "done by the OCR stage (single image request)"
                    if record.ai_combined
                    else "cached"
                )
                log.progress("AI", index, len(working), f"{record.source} → skipped ({reason})")
                self.manifest.upsert(record)
            else:
                if provider is None or service is None:
                    provider = self._make_provider()
                    service = ReconstructionService(
                        provider=provider,
                        skills=self.skills,
                        model=cfg.ai.model,
                        temperature=cfg.ai.temperature,
                        context_chars=cfg.ai.context_chars,
                        reasoning_effort=cfg.ai.reasoning_effort,
                        max_tokens=cfg.ai.max_tokens,
                    )
                try:
                    result = service.process(
                        cfg.ai.skills,
                        ocr_text=ocr_text,
                        previous_tail=prev_tail,
                        source_name=record.source,
                    )
                    reconstructed_path.write_text(result.text, encoding="utf-8")
                    record.ai_status = Status.DONE.value
                    record.ai_provider = result.provider
                    record.ai_model = result.model
                    record.ai_skill = result.skill
                    # Store the config-derived cache key (not the provider
                    # instance's) so resume can recompute it without
                    # instantiating a provider (which needs credentials).
                    record.ai_cache_key = cache_key
                    # Produced by this stage, not by a single image
                    # request in the OCR stage (relevant after switching
                    # ocr.engine back to paddleocr and re-running).
                    record.ai_combined = False
                    record.reconstructed_file = reconstructed_relative
                    record.ai_finished_at = utc_now_iso()
                    record.clear_errors("AI")
                    summary.ok += 1
                    log.progress(
                        "AI",
                        index,
                        len(working),
                        f"{record.source} → {len(result.text)} chars "
                        f"({result.provider}:{result.model})",
                    )
                except OcrDocError as exc:
                    record.ai_status = Status.ERROR.value
                    record.record_error("AI", exc.message)
                    summary.failed += 1
                    log.error("AI", f"{record.source}: {exc}")
                    if not isinstance(exc, InvalidAIResponseError):
                        # Provider-level failure (missing key, rate limit,
                        # timeout, unknown provider): remaining pages would
                        # fail the same way — abort the stage.
                        self.manifest.upsert(record)
                        self.manifest.save()
                        raise
                finally:
                    self.manifest.upsert(record)

            prev_tail = context_of(record)

        self.manifest.save()
        log.info(
            "AI",
            f"{summary.ok} ok, {summary.skipped} skipped, {summary.failed} failed",
        )
        return summary

    # -- stage: assembly --------------------------------------------------------

    def assemble(self) -> AssemblyReport:
        cfg = self.config
        ensure_dir(cfg.reconstructed_dir)
        sources = {
            record.sequence: record.source
            for record in self.manifest.records()
            if record.sequence > 0
        }
        report = assemble_document(cfg.reconstructed_dir, cfg.document_md, sources)
        log.info("ASSEMBLY", f"{len(report.pages)} page(s) → {cfg.document_md}")
        return report

    # -- stage: export -----------------------------------------------------------

    def export(
        self,
        formats: list[str] | None = None,
        watermark_text: str | None = None,
    ) -> list[Path]:
        cfg = self.config
        if not cfg.document_md.is_file():
            raise AssemblyError(
                f"Assembled document not found: {cfg.document_md}",
                "Run `ocrdoc assemble` (or the full `ocrdoc run`) first.",
            )
        selected_formats = formats or cfg.export.formats
        watermark_cfg = cfg.export.watermark
        if watermark_text is not None:
            watermark_cfg = replace(watermark_cfg, enabled=True, text=watermark_text)

        text = read_text(cfg.document_md)
        outputs: list[Path] = []
        for index, fmt in enumerate(selected_formats, start=1):
            if fmt == "docx":
                path = export_docx(text, cfg.output_dir / "document.docx", watermark_cfg)
            elif fmt == "pdf":
                path = export_pdf(text, cfg.output_dir / "document.pdf", watermark_cfg)
            else:  # pragma: no cover - config validation already filters
                raise ConfigError(f"Unsupported export format: {fmt}")
            outputs.append(path)
            log.progress("EXPORT", index, len(selected_formats), f"{fmt} → {path}")
        return outputs

    # -- full pipeline --------------------------------------------------------------

    def run(self, force: bool = False) -> PipelineReport:
        scan_result = self.scan()
        if not scan_result.assets:
            raise ConfigError(
                f"No supported images found in '{self.config.input_dir}'.",
                "Add images (.png .jpg .jpeg .tiff .tif .webp .bmp) to the "
                "input directory, or pass --input with the correct path.",
            )

        ocr_summary = self.run_ocr(assets=scan_result.assets, force=force)
        ai_summary = self.run_reconstruction(force=force)

        if scan_result.invalid:
            names = ", ".join(relative for relative, _ in scan_result.invalid)
            log.error(
                "RUN",
                f"{len(scan_result.invalid)} discovered image(s) could not be "
                f"read: {names}.",
            )
            raise OcrDocError(
                f"{len(scan_result.invalid)} image(s) failed validation: {names}",
                "Fix or remove the listed file(s), then re-run `ocrdoc run` — "
                "valid pages are cached in the manifest. Assembly is skipped "
                "to avoid silently building a document from a partial set.",
            )

        if ocr_summary.failed or ai_summary.failed:
            failed = ocr_summary.failed + ai_summary.failed
            log.error(
                "RUN",
                f"{failed} page(s) failed; document assembly skipped to avoid "
                "silently dropping pages. Fix the cause and re-run "
                "`ocrdoc run` — completed stages are cached in the manifest.",
            )
            raise OcrDocError(f"Pipeline finished with {failed} failed page(s).")

        assembly = self.assemble()
        outputs = self.export()
        return PipelineReport(
            assets=len(scan_result.assets),
            ocr=ocr_summary,
            ai=ai_summary,
            pages=len(assembly.pages),
            outputs=outputs,
        )
