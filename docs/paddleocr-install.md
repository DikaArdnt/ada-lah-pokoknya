# Installing PaddleOCR (CPU-only and GPU)

Source of truth: [PaddleOCR 3.x — General OCR Pipeline Usage, §2 Quick
Start](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html#2-quick-start)
and [Installation](https://www.paddleocr.ai/latest/en/version3.x/installation.html).

PaddleOCR runs its models on an *inference engine*. The default and
recommended engine is **PaddlePaddle**, so installation is two steps:

1. install an inference engine (PaddlePaddle by default),
2. install the `paddleocr` package.

`ocrdoc` uses the PaddlePaddle engine.

## 1. Install the inference engine (PaddlePaddle)

Pick the build that matches the machine.

### CPU-only (no NVIDIA GPU)

```bash
python -m pip install paddlepaddle
```

This is the right choice for laptops, CI runners, and servers without a GPU.
`ocrdoc` already defaults to `ocr.device: auto`, which runs on the CPU when
no CUDA GPU is present; use `--device cpu` to force it.

### GPU (NVIDIA CUDA)

Install the CUDA build of PaddlePaddle matching your driver/CUDA version, as
described on the [PaddlePaddle Framework Installation
page](https://www.paddlepaddle.org.cn/en/install/quick). For example:

```bash
python -m pip install paddlepaddle-gpu
```

Then set `ocr.device: gpu` (or leave `auto`) in config, or pass
`--device gpu`. `ocrdoc` verifies at startup that a CUDA-enabled build and a
visible GPU are present, and fails with an actionable error otherwise.

> **Alternative engines.** PaddleOCR 3.5+ can also run on `transformers`
> (`python -m pip install "transformers>=5.10.0"`) or `onnxruntime`
> (`python -m pip install onnxruntime-gpu`). `ocrdoc` does not expose the
> `engine` switch and always uses PaddlePaddle.

## 2. Install PaddleOCR

```bash
# General OCR and document-image preprocessing only (what ocrdoc needs)
python -m pip install paddleocr

# Optional: all capabilities (document parsing, translation, KIE, ...)
# python -m pip install "paddleocr[all]"
```

For a development checkout of `ocrdoc` (includes pytest):

```bash
python -m pip install -e ".[dev]"
```

## 3. Verify

```bash
# PaddleOCR is installed
python -c "import paddleocr; print(f'PaddleOCR version: {paddleocr.__version__}')"

# PaddlePaddle and GPU availability (official verification snippet)
python -c "import paddle; print(f'Paddle version: {paddle.__version__}'); print(f'GPU available: {paddle.is_compiled_with_cuda()}'); print(f'GPU count: {paddle.device.cuda.device_count()}')"

# ocrdoc sees the languages
ocrdoc languages list
ocrdoc languages check --lang id
```

## Language models: all languages or specific ones?

There is **no separate per-language installation step**. PaddleOCR downloads
the required detection + recognition models automatically the first time a
language is used (cached under `~/.paddleocr`).

- **One language per run.** PaddleOCR loads one recognition model per run, so
  `--lang` takes a single code (`en`, `id`, `ch`, `japan`, …). There is no
  `id+en` multi-language mode — pick the document's primary language.
- **Default model = PP-OCRv6 (50 languages).** The default `ocr_version` is
  PP-OCRv6, which supports: `ch`, `chinese_cht`, `en`, `japan`, `af`, `az`,
  `bs`, `ca`, `cs`, `cy`, `da`, `de`, `es`, `et`, `eu`, `fi`, `fr`, `ga`,
  `gl`, `hr`, `hu`, `id`, `is`, `it`, `ku`, `la`, `lb`, `lt`, `lv`, `mi`,
  `ms`, `mt`, `nl`, `no`, `oc`, `pl`, `pt`, `qu`, `rm`, `ro`, `rs_latin`,
  `sk`, `sl`, `sq`, `sv`, `sw`, `tl`, `tr`, `uz`, `vi`, `french`, `german`.
- **Languages outside PP-OCRv6** (e.g. `korean`, `ru`, `uk`, `th`, `el`) are
  only available under PP-OCRv5 / PP-OCRv3. `ocrdoc` runs the default
  PP-OCRv6; see the appendix table in the source document for the full
  version ↔ language correspondence.
- **Pre-download a specific language** (e.g. for an offline machine): run
  once while online with that language, e.g. `ocrdoc ocr --lang id` on a
  sample image. The model is then cached for later offline use.
- To use several languages, run separate OCR passes with a different
  `--lang` per pass.

## Device values (PaddleOCR 3.x)

PaddleOCR 3.x accepts `cpu`, `gpu:0` (first GPU), `npu:0`, `xpu:0`, etc.
`ocrdoc` keeps a simpler `ocr.device` of `auto | gpu | cpu` and maps it:

| `ocr.device` | PaddleOCR `device` |
|---|---|
| `cpu` | `cpu` |
| `gpu` (GPU verified) | `gpu:0` |
| `auto` + GPU | `gpu:0` |
| `auto` + no GPU | `cpu` |

`ocrdoc` also disables PaddleOCR's optional modules
(`use_doc_orientation_classify`, `use_doc_unwarping`,
`use_textline_orientation`) to match the official quick start — they add
latency and extra model downloads and are unnecessary for scanned documents.

`ocrdoc` also disables oneDNN/MKLDNN by default
(`ocr.enable_mkldnn: false`). PaddlePaddle 3.x (e.g. 3.3.1) crashes on the
PP-OCRv6 models when MKLDNN is enabled with
`(Unimplemented) ConvertPirAttribute2RuntimeAttribute not support
[pir::ArrayAttribute<pir::DoubleAttribute>]` (onednn_instruction.cc:118).
If you hit this, make sure `ocr.enable_mkldnn` is `false` (the default) — do
not enable it until the PaddlePaddle fix is available.

## Notes

- The first OCR run downloads models, so keep internet access available.
- PaddleOCR itself supports Python 3.8+; check the PaddlePaddle wheel page
  for the matching Python/CUDA combination.
