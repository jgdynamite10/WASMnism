# WASMnism

Portable ClipClap Edge Gateway benchmark — same gateway logic deployed across WASM-first edge platforms (Akamai/Spin, Fastly, Cloudflare Workers) and AWS Lambda, with a decision-grade price-per-performance scorecard.

## Attribution

The **inference service** is based on [ClipClap](https://github.com/akafinch/clipclap) by akafinch. We use it as the upstream ML backend (CLIP/CLAP image and audio classification). The edge gateway, benchmark harness, and multi-platform deployment are additions for this project.

## Project Structure

```
WASMnism/
├── clipclap/           # Inference service (FastAPI + CLIP/CLAP) — from akafinch/clipclap
├── edge-gateway/       # Portable gateway: Rust core + platform adapters
├── docs/               # Benchmark contract, execution plan, architecture
├── bench/              # k6 scripts, fixtures (to be added)
└── cost/               # Cost model (to be added)
```

## Quick Start

See [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md) for the full roadmap. Current status: benchmark contract defined, Spin adapter implemented.

## License

MIT (see clipclap for its license)
