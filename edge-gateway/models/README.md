# ML Model: MiniLMv2-toxic-jigsaw

## Overview

A distilled MiniLM v2 transformer (22.7M parameters) fine-tuned on the
Jigsaw toxic-comment dataset for binary toxicity classification.

## Files

| File | Size | SHA-256 |
|------|------|---------|
| `toxicity/model.nnef.tar` | 53 MB | `aaf95fcf4aef8e7636a7bf40e2cb3f4ed03eb039b8bd32e96c348224bca99377` |
| `toxicity/vocab.txt` | 56 KB | `04332de50cb467423bfd623703c8c05e830a57a2f325cda835a29bef7626655f` |

## Verify integrity

```bash
cd edge-gateway/models
shasum -a 256 -c << 'CHECKSUMS'
aaf95fcf4aef8e7636a7bf40e2cb3f4ed03eb039b8bd32e96c348224bca99377  toxicity/model.nnef.tar
04332de50cb467423bfd623703c8c05e830a57a2f325cda835a29bef7626655f  toxicity/vocab.txt
CHECKSUMS
```

## Categories

| Output | Threshold | Verdict |
|--------|-----------|---------|
| `toxic` >= 0.80 | Hard block | `block` |
| `severe_toxic` >= 0.80 | Hard block | `block` |
| `toxic` >= 0.50 | Soft flag | `review` |
| Below thresholds | — | no ML flag |

## Conversion Pipeline

The model was converted through these steps:

1. **PyTorch** — Fine-tuned MiniLM v2 on Jigsaw toxic-comment dataset
2. **ONNX export** — `torch.onnx.export()` with dynamic axes
3. **Vocabulary trim** — Reduced WordPiece vocabulary from 30,522 to 8,000 tokens
   to fit WASM deployment size limits while retaining >99% coverage of toxic-comment corpus
4. **Tract NNEF** — Converted ONNX to Tract's native NNEF format using
   `tools/convert-to-nnef/` to avoid expensive protobuf parsing in the WASM runtime

## Regenerating from scratch

```bash
# 1. Train or download the PyTorch model (not included in this repo)
# 2. Export to ONNX
# 3. Trim vocabulary (custom script, retains top 8000 tokens by frequency)
# 4. Convert to NNEF:
cd edge-gateway/tools/convert-to-nnef
cargo run -- ../../models/toxicity/model.onnx ../../models/toxicity/model.nnef.tar
```

The conversion tool source is at `tools/convert-to-nnef/src/main.rs`.

## Why NNEF?

ONNX parsing requires protobuf, which adds significant binary size and
startup latency in WASM. Tract's NNEF format is a simple tar archive of
tensor files — no protobuf needed. This reduces cold start model
deserialization significantly compared to ONNX.
