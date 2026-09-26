from __future__ import annotations

from pathlib import Path

import pytest

from ocr_reconstructor.config import (
    AppConfig,
    load_app_config,
)
from ocr_reconstructor.core.exceptions import ConfigError


def test_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Isolate from any config.yaml in the working directory so built-in
    # defaults are actually tested.
    monkeypatch.chdir(tmp_path)
    cfg = load_app_config(None, None)
    assert cfg.ocr.engine == "paddleocr"
    assert cfg.ocr.language == "en"
    assert cfg.ocr.output_format == "md"
    assert cfg.ocr.device == "auto"
    assert cfg.ocr.enable_mkldnn is False
    assert cfg.ai.model is None
    assert cfg.ai.skill == "default"
    assert cfg.ai.skills == ["default"]
    assert cfg.ai.provider == "openai"
    assert cfg.export.formats == ["docx"]
    assert cfg.export.watermark.enabled is False
    assert cfg.input_dir == cfg.workspace / "input"


def _write_config(tmp_path: Path, text: str, name: str = "config.yml") -> Path:
    config_file = tmp_path / name
    config_file.write_text(text, encoding="utf-8")
    return config_file


def test_device_from_yaml_and_cli(tmp_path: Path):
    config_file = _write_config(tmp_path, "ocr:\n  device: cpu\n")
    cfg = load_app_config(config_file, None)
    assert cfg.ocr.device == "cpu"
    cfg = load_app_config(config_file, {"ocr.device": "gpu"})
    assert cfg.ocr.device == "gpu"


def test_config_yml_is_discovered(tmp_path: Path):
    _write_config(tmp_path, "ocr:\n  device: cpu\n", "config.yml")
    cfg = load_app_config(None, None)
    assert cfg.ocr.device == "cpu"


def test_config_yaml_is_discovered_as_fallback(tmp_path: Path):
    _write_config(tmp_path, "ocr:\n  device: cpu\n", "config.yaml")
    cfg = load_app_config(None, None)
    assert cfg.ocr.device == "cpu"


def test_config_yml_wins_over_config_yaml(tmp_path: Path):
    _write_config(tmp_path, "ocr:\n  device: cpu\n", "config.yml")
    _write_config(tmp_path, "ocr:\n  device: gpu\n", "config.yaml")
    cfg = load_app_config(None, None)
    assert cfg.ocr.device == "cpu"


def test_enable_mkldnn_default_and_yaml(tmp_path: Path):
    cfg = load_app_config(None, None)
    assert cfg.ocr.enable_mkldnn is False
    config_file = _write_config(tmp_path, "ocr:\n  enable_mkldnn: true\n")
    cfg = load_app_config(config_file, None)
    assert cfg.ocr.enable_mkldnn is True
    cfg = load_app_config(config_file, {"ocr.enable_mkldnn": False})
    assert cfg.ocr.enable_mkldnn is False


def test_api_keys_default_to_none(tmp_path: Path):
    cfg = load_app_config(None, None)
    assert cfg.ai.api_key is None


def test_one_api_key_serves_both_stages(tmp_path: Path):
    """One key for every AI request (OCR and reconstruction)."""
    config_file = _write_config(tmp_path, "ai:\n  api_key: sk-shared\n")
    cfg = load_app_config(config_file, None)
    assert cfg.ai.api_key == "sk-shared"


def test_empty_api_key_is_unset(tmp_path: Path):
    config_file = _write_config(tmp_path, "ai:\n  api_key: ''\n")
    cfg = load_app_config(config_file, None)
    assert cfg.ai.api_key is None


def test_non_string_api_key_rejected(tmp_path: Path):
    config_file = _write_config(tmp_path, "ai:\n  api_key: 12345\n")
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(config_file, None)
    assert "ai.api_key" in excinfo.value.message


def test_invalid_device_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ocr.device": "tpu"})
    assert "ocr.device" in excinfo.value.message
    assert "cpu" in excinfo.value.hint


def test_invalid_engine_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ocr.engine": "some-unknown-engine"})
    assert "ocr.engine" in excinfo.value.message
    assert "openai_compatible" in excinfo.value.hint


def test_vision_engine_from_yaml_and_cli(tmp_path: Path):
    """Engine settings come from the shared ai section."""
    config_file = _write_config(
        tmp_path,
        "ocr:\n  engine: openai\nai:\n  model: gpt-4o\n"
        "  skill: [default]\n  temperature: 0.2\n"
        "  max_tokens: 3000\n  timeout: 60\n  max_retries: 5\n",
    )
    cfg = load_app_config(config_file, None)
    assert cfg.ocr.engine == "openai"
    assert cfg.ai.model == "gpt-4o"
    assert cfg.ai.skills == ["default"]
    assert cfg.ai.temperature == 0.2
    assert cfg.ai.max_tokens == 3000
    assert cfg.ai.timeout == 60.0
    assert cfg.ai.max_retries == 5

    cfg = load_app_config(
        config_file,
        {"ocr.engine": "openai_compatible", "ai.model": "llava"},
    )
    assert cfg.ocr.engine == "openai_compatible"
    assert cfg.ai.model == "llava"


def test_vision_engine_from_yaml(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "ocr:\n  engine: openai_compatible\nai:\n  model: llava-1.6\n"
        "  skill: [default]\n"
        "  base_url: http://localhost:11434/v1\n",
        encoding="utf-8",
    )
    cfg = load_app_config(config_file, None)
    assert cfg.ocr.engine == "openai_compatible"
    assert cfg.ai.model == "llava-1.6"
    assert cfg.ai.skills == ["default"]
    assert cfg.ai.base_url == "http://localhost:11434/v1"


def test_yaml_layer(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "ocr:\n  language: ind+eng\nexport:\n  format: [docx, pdf]\n",
        encoding="utf-8",
    )
    cfg = load_app_config(config_file, None)
    assert cfg.ocr.language == "ind+eng"
    assert cfg.export.formats == ["docx", "pdf"]


def test_cli_overrides_yaml(tmp_path: Path):
    config_file = _write_config(tmp_path, "ocr:\n  language: deu\n")
    cfg = load_app_config(config_file, {"ocr.language": "fra"})
    assert cfg.ocr.language == "fra"


def test_cli_none_values_are_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    cfg = load_app_config(None, {"ocr.language": None, "ai.model": None})
    assert cfg.ocr.language == "en"
    assert cfg.ai.model is None


def test_export_formats_from_yaml(tmp_path: Path):
    config_file = _write_config(tmp_path, "export:\n  formats: [pdf, docx]\n")
    cfg = load_app_config(config_file, None)
    assert cfg.export.formats == ["pdf", "docx"]


def test_missing_config_file_is_actionable(tmp_path: Path):
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(tmp_path / "nope.yaml", None)
    assert "not found" in excinfo.value.message


def test_invalid_export_format_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"export.formats": ["xlsx"]})
    assert "Invalid export format" in excinfo.value.message


def test_invalid_watermark_opacity_rejected():
    with pytest.raises(ConfigError):
        load_app_config(None, {"export.watermark.opacity": 1.5})


@pytest.mark.parametrize(
    "position",
    [
        "center",
        "horizontal",
        "vertical",
        "diagonal",
        "tile",
        "top",
        "top-left",
        "top-right",
        "left",
        "right",
        "bottom",
        "bottom-left",
        "bottom-right",
    ],
)
def test_valid_watermark_positions_accepted(position: str):
    cfg = load_app_config(None, {"export.watermark.position": position})
    assert cfg.export.watermark.position == position


def test_invalid_watermark_position_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"export.watermark.position": "middle"})
    assert "Invalid" in excinfo.value.message


def test_invalid_output_format_rejected():
    with pytest.raises(ConfigError):
        load_app_config(None, {"ocr.output_format": "docx"})


def test_explicit_workspace_changes_default_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    cfg = load_app_config(None, {"workspace": "./ws2"})
    assert cfg.input_dir == Path("./ws2/input")
    assert cfg.ocr_dir == Path("./ws2/ocr")
    assert cfg.manifest_path == Path("./ws2/manifest.json")


def test_explicit_input_wins_over_workspace_default():
    cfg = load_app_config(None, {"workspace": "./ws2", "input": "./scans"})
    assert cfg.input_dir == Path("./scans")


def test_derived_paths(tmp_path: Path):
    cfg = AppConfig(workspace=tmp_path)
    assert cfg.preprocessed_dir == tmp_path / "preprocessed"
    assert cfg.reconstructed_dir == tmp_path / "reconstructed"
    assert cfg.output_dir == tmp_path / "output"
    assert cfg.document_md == tmp_path / "output" / "document.md"


def test_ai_request_parameter_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    cfg = load_app_config(None, None)
    assert cfg.ai.reasoning_effort is None
    assert cfg.ai.max_tokens is None
    assert cfg.ai.base_url is None
    assert cfg.ai.extra_headers is None
    assert cfg.ai.timeout == 120.0
    assert cfg.ai.max_retries == 2


def test_ai_extra_headers_from_yaml(tmp_path: Path):
    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "ai:\n  extra_headers:\n    X-Title: ocrdoc\n    HTTP-Referer: https://myapp.dev\n",
        encoding="utf-8",
    )
    cfg = load_app_config(config_file, None)
    assert cfg.ai.extra_headers == {
        "X-Title": "ocrdoc",
        "HTTP-Referer": "https://myapp.dev",
    }


def test_invalid_extra_headers_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ai.extra_headers": ["not-a-mapping"]})
    assert "extra_headers" in excinfo.value.message


def test_ai_request_parameters_from_yaml(tmp_path: Path):
    config_file = _write_config(
        tmp_path,
        "ai:\n  reasoning_effort: HIGH\n  max_tokens: 4000\n"
        "  base_url: https://api.example.com/v1\n"
        "  timeout: 30\n  max_retries: 5\n",
    )
    cfg = load_app_config(config_file, None)
    assert cfg.ai.reasoning_effort == "high"  # normalized to lowercase
    assert cfg.ai.max_tokens == 4000
    assert cfg.ai.base_url == "https://api.example.com/v1"
    assert cfg.ai.timeout == 30.0
    assert cfg.ai.max_retries == 5


def test_ai_request_parameters_cli_override(tmp_path: Path):
    config_file = _write_config(tmp_path, "ai:\n  reasoning_effort: high\n")
    cfg = load_app_config(
        config_file, {"ai.reasoning_effort": "minimal", "ai.max_tokens": 800}
    )
    assert cfg.ai.reasoning_effort == "minimal"
    assert cfg.ai.max_tokens == 800


def test_invalid_reasoning_effort_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ai.reasoning_effort": "turbo"})
    assert "reasoning_effort" in excinfo.value.message
    assert "minimal" in excinfo.value.hint


def test_invalid_max_tokens_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ai.max_tokens": 0})
    assert "max_tokens" in excinfo.value.message


# ---------------------------------------------------------------------------
# Unified AI processing: removed keys fail loudly with migration hints
# ---------------------------------------------------------------------------


def test_removed_ocr_skill_rejected(tmp_path: Path):
    config_file = _write_config(tmp_path, "ai:\n  ocr_skill: default\n")
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(config_file, None)
    assert "ai.ocr_skill" in excinfo.value.message
    assert "ai.skill: [skill1, skill2]" in excinfo.value.hint


def test_removed_ocr_temperature_rejected(tmp_path: Path):
    config_file = _write_config(tmp_path, "ai:\n  ocr_temperature: 0.0\n")
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(config_file, None)
    assert "ai.ocr_temperature" in excinfo.value.message
    assert "ai.temperature" in excinfo.value.hint


def test_removed_reconstruct_rejected(tmp_path: Path):
    config_file = _write_config(tmp_path, "ai:\n  reconstruct: false\n")
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(config_file, None)
    assert "ai.reconstruct" in excinfo.value.message
    assert "paddleocr" in excinfo.value.hint


def test_removed_key_via_cli_override_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ai.ocr_skill": ["default"]})
    assert "ai.ocr_skill" in excinfo.value.message


# ---------------------------------------------------------------------------
# Skill pairing: one list (ai.skill) for every AI request
# ---------------------------------------------------------------------------


def test_ai_skill_yaml_list_pairs_skills(tmp_path: Path):
    config_file = _write_config(tmp_path, "ai:\n  skill: [skill1, skill2]\n")
    cfg = load_app_config(config_file, None)
    assert cfg.ai.skills == ["skill1", "skill2"]
    assert cfg.ai.skill == "skill1"  # primary skill stays available


def test_ai_skill_single_name_stays_a_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_app_config(None, None)
    assert cfg.ai.skills == ["default"]
    assert cfg.ai.skill == "default"


def test_ai_skill_cli_list_override_wins(tmp_path: Path):
    config_file = _write_config(tmp_path, "ai:\n  skill: default\n")
    cfg = load_app_config(config_file, {"ai.skill": ["skill1", "skill2"]})
    assert cfg.ai.skills == ["skill1", "skill2"]


def test_skill_duplicates_collapse_in_order():
    cfg = load_app_config(None, {"ai.skill": ["skill1", "skill2", "skill1"]})
    assert cfg.ai.skills == ["skill1", "skill2"]


def test_empty_ai_skill_list_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ai.skill": []})
    assert "ai.skill" in excinfo.value.message
    assert "at least one skill" in excinfo.value.message


def test_empty_skill_entry_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ai.skill": ["ok", " "]})
    assert "ai.skill" in excinfo.value.message


def test_non_string_skill_value_rejected():
    with pytest.raises(ConfigError) as excinfo:
        load_app_config(None, {"ai.skill": 42})
    assert "ai.skill" in excinfo.value.message
