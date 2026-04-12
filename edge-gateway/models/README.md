# ML Model: MiniLMv2-toxic-jigsaw

> **Note:** ML models are used on the `ml-inference` branch (Tier 2) only.
> The `rules-only` branch does not use ML inference.

## Overview

A distilled MiniLM v2 transformer (22.7M parameters) fine-tuned on the
Jigsaw toxic-comment dataset for binary toxicity classification.

## Download

The model files are hosted as a GitHub Release (too large for git):

```bash
cd edge-gateway/models/toxicity/
gh release download v0.2.0-models --repo jgdynamite/WASMnism
```

Or download manually from:
**https://github.com/jgdynamite/WASMnism/releases/tag/v0.2.0-models**

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

## Base Model Source

| Property | Value |
|----------|-------|
| Base model | [nreimers/MiniLMv2-L6-H384-distilled-from-RoBERTa-Large](https://huggingface.co/nreimers/MiniLMv2-L6-H384-distilled-from-RoBERTa-Large) |
| Fine-tuning dataset | [Jigsaw Toxic Comment Classification](https://www.kaggle.com/c/jigsaw-toxic-comment-classification-challenge) |
| Parameters | 22.7M |
| Fine-tuning task | Multi-label binary classification (`toxic`, `severe_toxic`) |

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
   - Base: `nreimers/MiniLMv2-L6-H384-distilled-from-RoBERTa-Large` from HuggingFace
   - Dataset: Jigsaw Toxic Comment Classification Challenge (Kaggle)
   - Output: PyTorch `.pt` checkpoint with `toxic` and `severe_toxic` heads
2. **ONNX export** — `torch.onnx.export()` with opset 14, fixed input shapes
3. **Vocabulary trim** — Reduced WordPiece vocabulary from 30,522 to 8,000 tokens
   to fit WASM deployment size limits while retaining >99% coverage of toxic-comment corpus
4. **Tract NNEF** — Converted ONNX to Tract's native NNEF format using
   `tools/convert-to-nnef/` to avoid expensive protobuf parsing in the WASM runtime

## Regenerating from scratch

```bash
# 1. Download the base model from HuggingFace
#    https://huggingface.co/nreimers/MiniLMv2-L6-H384-distilled-from-RoBERTa-Large

# 2. Fine-tune on Jigsaw toxic-comment dataset
#    https://www.kaggle.com/c/jigsaw-toxic-comment-classification-challenge
#    Train a multi-label classifier with toxic + severe_toxic output heads

# 3. Export to ONNX (opset 14, fixed shapes: batch=1, seq_len=128)
#    torch.onnx.export(model, dummy_input, "model.onnx", opset_version=14)

# 4. Trim vocabulary from 30,522 to 8,000 tokens
#    Keep top 8,000 by frequency in the Jigsaw corpus + all special tokens

# 5. Convert ONNX to Tract NNEF:
cd edge-gateway/tools/convert-to-nnef
cargo run -- ../../models/toxicity/model.onnx ../../models/toxicity/model.nnef.tar
```

The conversion tool source is at `tools/convert-to-nnef/src/main.rs`.

## Why NNEF?

ONNX parsing requires protobuf, which adds significant binary size and
startup latency in WASM. Tract's NNEF format is a simple tar archive of
tensor files — no protobuf needed. This reduces cold start model
deserialization significantly compared to ONNX.

## ML availability by platform (Tier 2 only)

| Platform | ML Support | Why |
|----------|-----------|-----|
| Akamai Functions (Spin) | Yes | WASI filesystem mounts model files |
| AWS Lambda | Yes | Native filesystem at `/var/task/models/toxicity/` |

Tier 1 platforms (Fastly Compute, Cloudflare Workers) do not support ML inference
due to runtime filesystem constraints.
