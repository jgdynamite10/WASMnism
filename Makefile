.PHONY: prereqs build build-frontend build-lambda deploy-akamai deploy-fastly deploy-workers deploy-lambda test clean validate benchmark bench-multiregion bench-full scorecard report security-check install-hooks cleanup-stale runners-up runners-status runners-sync runners-down gcp-runners-up gcp-runners-status gcp-runners-sync gcp-runners-down bench-tier2-cold-ml bench-tier2-warm-ml bench-tier2-cache-hit bench-tier2-mixed bench-tier2-clip-rules bench-tier2-all bench-tier2-gcp push-all sync-org help

# Default gateway URL (override with URL=...)
URL ?= https://0ae93a16-62c9-44cc-8a2b-23f7c6b9bae1.fwf.app
PLATFORM ?= akamai

# ── Prerequisites ────────────────────────────────────────────
prereqs:
	@echo "=== Checking prerequisites ==="
	@command -v rustc    >/dev/null 2>&1 && echo "  rust:     $$(rustc --version)" || echo "  MISSING: rustc (https://rustup.rs)"
	@command -v cargo    >/dev/null 2>&1 && echo "  cargo:    $$(cargo --version)" || echo "  MISSING: cargo"
	@rustup target list --installed 2>/dev/null | grep -q wasm32-wasip1 && echo "  wasm32:   installed" || echo "  MISSING: rustup target add wasm32-wasip1"
	@command -v spin     >/dev/null 2>&1 && echo "  spin:     $$(spin --version)" || echo "  MISSING: spin (https://developer.fermyon.com/spin/v3/install)"
	@command -v node     >/dev/null 2>&1 && echo "  node:     $$(node --version)" || echo "  MISSING: node (https://nodejs.org)"
	@command -v npm      >/dev/null 2>&1 && echo "  npm:      $$(npm --version)" || echo "  MISSING: npm"
	@command -v k6       >/dev/null 2>&1 && echo "  k6:       $$(k6 version)" || echo "  MISSING: k6 (https://k6.io/docs/get-started/installation/)"
	@command -v python3  >/dev/null 2>&1 && echo "  python3:  $$(python3 --version)" || echo "  MISSING: python3"
	@command -v curl     >/dev/null 2>&1 && echo "  curl:     OK" || echo "  MISSING: curl"
	@echo ""

# ── Build ────────────────────────────────────────────────────
build:
	$(MAKE) -C edge-gateway build-spin

build-frontend:
	$(MAKE) -C edge-gateway build-frontend

# Tier 2 (ml-inference): native Lambda + Tract; requires LAMBDA_ROLE, LAMBDA_S3_BUCKET
build-lambda:
	$(MAKE) -C edge-gateway build-lambda

test:
	$(MAKE) -C edge-gateway test

clean:
	$(MAKE) -C edge-gateway clean

# ── Deploy ───────────────────────────────────────────────────
deploy-akamai:
	$(MAKE) -C edge-gateway deploy-akamai

deploy-fastly:
	$(MAKE) -C edge-gateway deploy-fastly

deploy-workers:
	$(MAKE) -C edge-gateway deploy-workers

deploy-lambda:
	$(MAKE) -C edge-gateway deploy-lambda

# ── Benchmark (single region, local machine) ─────────────────
validate:
	./bench/run-validation.sh $(PLATFORM) $(URL)

benchmark:
	./bench/reproduce.sh $(PLATFORM) $(URL) $(BENCH_FLAGS)

# ── Benchmark (multi-region, from k6 runners) ────────────────
bench-multiregion:
	./bench/run-multiregion.sh $(PLATFORM) $(URL) $(BENCH_FLAGS)

# Multi-region from GCP runners (neutral origin)
bench-multiregion-gcp:
	./bench/run-multiregion.sh $(PLATFORM) $(URL) --provider gcp $(BENCH_FLAGS)

# ── Extended Benchmark (full suite: base + ladder-1000 + soak + spike) ──
bench-full:
	./bench/run-full-suite.sh $(PLATFORM) $(URL) $(BENCH_FLAGS)

# Multi-region full suite from GCP runners
bench-full-gcp:
	./bench/run-multiregion.sh $(PLATFORM) $(URL) --provider gcp --full $(BENCH_FLAGS)

# ── Tier 2 Benchmarks (per docs/benchmark_contract_tier2.md v1.0) ──────────
# Individual scenarios — run k6 locally against a single URL.
# Use PLATFORM=akamai-ml or PLATFORM=lambda-ml for tagging.

bench-tier2-cold-ml:
	@if [ -z "$(URL)" ]; then echo "Usage: make bench-tier2-cold-ml URL=<endpoint> [PLATFORM=akamai-ml|lambda-ml]"; exit 1; fi
	GATEWAY_URL="$(URL)" PLATFORM="$(if $(PLATFORM),$(PLATFORM),tier2)" k6 run bench/cold-ml.js

bench-tier2-warm-ml:
	@if [ -z "$(URL)" ]; then echo "Usage: make bench-tier2-warm-ml URL=<endpoint> [PLATFORM=akamai-ml|lambda-ml]"; exit 1; fi
	GATEWAY_URL="$(URL)" PLATFORM="$(if $(PLATFORM),$(PLATFORM),tier2)" k6 run bench/warm-ml.js

bench-tier2-cache-hit:
	@if [ -z "$(URL)" ]; then echo "Usage: make bench-tier2-cache-hit URL=<endpoint> [PLATFORM=akamai-ml|lambda-ml]"; exit 1; fi
	GATEWAY_URL="$(URL)" PLATFORM="$(if $(PLATFORM),$(PLATFORM),tier2)" k6 run bench/cache-hit.js

bench-tier2-mixed:
	@if [ -z "$(URL)" ]; then echo "Usage: make bench-tier2-mixed URL=<endpoint> [PLATFORM=akamai-ml|lambda-ml]"; exit 1; fi
	GATEWAY_URL="$(URL)" PLATFORM="$(if $(PLATFORM),$(PLATFORM),tier2)" k6 run bench/mixed-load.js

bench-tier2-clip-rules:
	@if [ -z "$(URL)" ]; then echo "Usage: make bench-tier2-clip-rules URL=<endpoint> [PLATFORM=akamai-ml|lambda-ml]"; exit 1; fi
	GATEWAY_URL="$(URL)" PLATFORM="$(if $(PLATFORM),$(PLATFORM),tier2)" k6 run bench/clip-rules-only.js

# Run all 5 Tier 2 scenarios sequentially against ONE URL (single-machine).
# Output: results/$(PLATFORM)/tier2_<timestamp>/local/<scenario>.json
# Useful for development; for multi-region see bench-tier2-gcp below.
bench-tier2-all:
	@if [ -z "$(URL)" ] || [ -z "$(PLATFORM)" ]; then \
		echo "Usage: make bench-tier2-all URL=<endpoint> PLATFORM=akamai-ml|lambda-ml"; \
		echo "Example: make bench-tier2-all URL=https://f9318a6c-...fwf.app PLATFORM=akamai-ml"; \
		exit 1; \
	fi
	@TS=$$(date +%Y%m%d_%H%M%S); \
	OUTDIR="results/$(PLATFORM)/tier2_$$TS/local"; \
	mkdir -p "$$OUTDIR"; \
	echo "=== Tier 2 suite for $(PLATFORM) at $(URL) ==="; \
	echo "Output: $$OUTDIR"; \
	for s in cold-ml warm-ml cache-hit mixed-load clip-rules-only; do \
		echo ""; \
		echo "── $$s ──"; \
		GATEWAY_URL="$(URL)" PLATFORM="$(PLATFORM)" \
			k6 run --out "json=$$OUTDIR/$$s.json" "bench/$$s.js" || exit $$?; \
	done; \
	echo ""; \
	echo "=== Done. Validate with: python3 bench/validate-results.py results/$(PLATFORM)/tier2_$$TS ==="

# Multi-region Tier 2 from GCP runners.
# NOTE: Requires bench/run-tier2-multiregion.sh (not yet authored — W4 prep work).
# Until then, run from each runner manually after `make gcp-runners-sync` copies bench/* over.
bench-tier2-gcp:
	@if [ ! -x bench/run-tier2-multiregion.sh ]; then \
		echo "ERROR: bench/run-tier2-multiregion.sh does not exist yet."; \
		echo "  - For local single-URL runs:  make bench-tier2-all URL=<u> PLATFORM=<p>"; \
		echo "  - For multi-region: 1) make gcp-runners-up && make gcp-runners-sync"; \
		echo "                      2) ssh into each runner and run bench/cold-ml.js etc."; \
		echo "                      3) scp the JSON outputs back to results/<platform>/tier2_<ts>/<region>/"; \
		echo "  - Or author bench/run-tier2-multiregion.sh based on bench/run-multiregion.sh as W4 prep."; \
		exit 1; \
	fi
	./bench/run-tier2-multiregion.sh $(PLATFORM) $(URL) --provider gcp $(BENCH_FLAGS)

# ── Scorecard ────────────────────────────────────────────────
scorecard:
	@if [ -z "$(A)" ] || [ -z "$(B)" ] || [ -z "$(C)" ]; then \
		echo "Usage: make scorecard A=results/akamai/<dir> B=results/fastly/<dir> C=results/workers/<dir> [OUT=scorecard.md]"; \
		exit 1; \
	fi
	python3 bench/build-scorecard.py $(A) $(B) $(C) $(if $(OUT),$(OUT))

# ── k6 Runner Infrastructure (Linode) ───────────────────────
runners-up:
	./deploy/k6-runner-setup.sh provision

runners-status:
	./deploy/k6-runner-setup.sh status

runners-sync:
	./deploy/k6-runner-setup.sh sync

runners-down:
	./deploy/k6-runner-setup.sh teardown

# ── k6 Runner Infrastructure (GCP — neutral origin) ────────
gcp-runners-up:
	./deploy/gcp-runner-setup.sh provision

gcp-runners-status:
	./deploy/gcp-runner-setup.sh status

gcp-runners-sync:
	./deploy/gcp-runner-setup.sh sync

gcp-runners-down:
	./deploy/gcp-runner-setup.sh teardown

# ── Report Generation ─────────────────────────────────────────
# Optional: set RESULT_AKAMAI, RESULT_FASTLY, RESULT_WORKERS to exact multiregion_* paths
# (e.g. validated GCP base runs). Otherwise the latest multiregion_* per platform is used.
report:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make report PLATFORMS=\"akamai fastly workers\" NAME=\"scorecard_name\""; \
		echo "Optional: RESULT_AKAMAI=... RESULT_FASTLY=... RESULT_WORKERS=... (override auto latest)"; \
		exit 1; \
	fi
	@echo "=== Validating results ==="
	@set -e; DIRS=""; \
	if [ -n "$(RESULT_AKAMAI)" ] && [ -n "$(RESULT_FASTLY)" ] && [ -n "$(RESULT_WORKERS)" ]; then \
		DIRS="$(RESULT_AKAMAI) $(RESULT_FASTLY) $(RESULT_WORKERS)"; \
		echo "Using explicit result dirs: $$DIRS"; \
	else \
		for p in $(PLATFORMS); do \
			latest=$$(ls -td results/$$p/multiregion_* 2>/dev/null | head -1); \
			if [ -z "$$latest" ]; then echo "ERROR: No results for $$p"; exit 1; fi; \
			DIRS="$$DIRS $$latest"; \
		done; \
	fi; \
	python3 bench/validate-results.py $$DIRS
	@echo "=== Generating scorecard ==="
	./bench/generate-scorecard.sh results/$(NAME).md

# ── Security ──────────────────────────────────────────────────
security-check:
	./scripts/pre-push-check.sh

install-hooks:
	./scripts/install-hooks.sh

# ── Cleanup ───────────────────────────────────────────────────
cleanup-stale:
	./bench/cleanup-stale.sh

# ── Mirror policy: keep `org` and `origin` in sync ─────────────
# Policy: `org` (jgdynamite10/WASMnism) is a mandatory mirror of `origin`
# (jgdynamite/WASMnism). Every push to `origin` MUST be followed by a push
# to `org`. Use `make push-all` instead of `git push` whenever practical.
#
# `make push-all`  pushes the current branch to both remotes.
# `make sync-org`  brings `org` up to date with `origin` for main +
#                  ml-inference (use after a peer pushes to origin without
#                  remembering to mirror).

push-all:
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
	echo "=== Pushing $$branch to origin ==="; \
	git push origin "$$branch"; \
	echo ""; \
	echo "=== Pushing $$branch to org (mirror) ==="; \
	git push org "$$branch"

sync-org:
	@echo "=== Fast-forwarding org/main to match origin/main ==="
	git fetch origin main
	git push org refs/remotes/origin/main:refs/heads/main
	@echo ""
	@echo "=== Fast-forwarding org/ml-inference to match origin/ml-inference ==="
	git fetch origin ml-inference
	git push org refs/remotes/origin/ml-inference:refs/heads/ml-inference
	@echo ""
	@echo "=== Verification ==="
	@printf "origin: "; git ls-remote origin main      | awk '{print $$1}' | tr -d '\n'; printf "  (main)\n"
	@printf "org:    "; git ls-remote org    main      | awk '{print $$1}' | tr -d '\n'; printf "  (main)\n"
	@printf "origin: "; git ls-remote origin ml-inference | awk '{print $$1}' | tr -d '\n'; printf "  (ml-inference)\n"
	@printf "org:    "; git ls-remote org    ml-inference | awk '{print $$1}' | tr -d '\n'; printf "  (ml-inference)\n"

# ── Help ─────────────────────────────────────────────────────
help:
	@echo "WASMnism — WASM Edge Gateway Benchmark"
	@echo ""
	@echo "Prerequisites:"
	@echo "  make prereqs                         Check all required tools"
	@echo ""
	@echo "Build & Deploy:"
	@echo "  make build                           Build WASM gateway + frontend"
	@echo "  make deploy-akamai                   Build + deploy to Akamai Functions"
	@echo "  make deploy-fastly                   Build + deploy to Fastly Compute"
	@echo "  make deploy-workers                  Build + deploy to Cloudflare Workers"
	@echo "  make build-lambda                    (Tier 2) Build AWS Lambda (ARM64) + static assets"
	@echo "  make deploy-lambda                   (Tier 2) deploy — needs LAMBDA_ROLE, LAMBDA_S3_BUCKET"
	@echo "  make test                            Run Rust unit tests"
	@echo ""
	@echo "Benchmark (single region):"
	@echo "  make validate PLATFORM=akamai URL=<url>              Run 8-scenario validation"
	@echo "  make benchmark PLATFORM=akamai URL=<url>             Full pipeline: validate → 7-run → medians"
	@echo "  make benchmark ... BENCH_FLAGS='--cold'              Include cold start (~20 min extra)"
	@echo "  make bench-full PLATFORM=akamai URL=<url>            Extended suite: base + 1K ladder + soak + spike"
	@echo ""
	@echo "Benchmark (multi-region, Linode runners):"
	@echo "  make runners-up                                      Provision 3 Linode k6 runners"
	@echo "  make runners-sync                                    Copy latest scripts to runners"
	@echo "  make bench-multiregion PLATFORM=akamai URL=<url>     Run from all 3 Linode regions"
	@echo "  make runners-down                                    Teardown Linode runners"
	@echo ""
	@echo "Benchmark (multi-region, GCP runners — neutral origin):"
	@echo "  make gcp-runners-up                                  Provision 3 GCP e2-standard-4 runners"
	@echo "  make gcp-runners-sync                                Copy latest scripts to GCP runners"
	@echo "  make bench-multiregion-gcp PLATFORM=akamai URL=<url> Run Tier 1 from all 3 GCP regions"
	@echo "  make bench-full-gcp PLATFORM=akamai URL=<url>        Full suite from GCP (1K VUs, soak, spike)"
	@echo "  make gcp-runners-down                                Teardown GCP runners"
	@echo ""
	@echo "Tier 2 Benchmarks (ml-inference branch, per benchmark_contract_tier2.md v1.0):"
	@echo "  make bench-tier2-cold-ml URL=<url>   [PLATFORM=akamai-ml|lambda-ml]   10 cold-ML iterations, 60s idle"
	@echo "  make bench-tier2-warm-ml URL=<url>   [PLATFORM=akamai-ml|lambda-ml]   30s warmup + 60s sustained ML"
	@echo "  make bench-tier2-cache-hit URL=<url> [PLATFORM=akamai-ml|lambda-ml]   2 prime + 20 cache hits"
	@echo "  make bench-tier2-mixed URL=<url>     [PLATFORM=akamai-ml|lambda-ml]   5 min @ 10 VUs, 95%/5% rules/ML"
	@echo "  make bench-tier2-clip-rules URL=<url> [PLATFORM=...] /api/clip/moderate ml:false handler-weight"
	@echo "  make bench-tier2-all URL=<url> PLATFORM=akamai-ml|lambda-ml         Run all 5 → results/<p>/tier2_*/local/"
	@echo ""
	@echo "Scorecard:"
	@echo "  make scorecard A=<akamai_dir> B=<fastly_dir> C=<workers_dir> [OUT=file.md]"
	@echo ""
	@echo "Report (validate + generate):"
	@echo "  make report PLATFORMS=\"akamai fastly workers\" NAME=\"scorecard_name\""
	@echo ""
	@echo "Housekeeping:"
	@echo "  make security-check                  Scan tracked files for secrets/IPs/PII"
	@echo "  make install-hooks                   Install pre-push security hook"
	@echo "  make cleanup-stale                   List stale result directories"
	@echo ""
	@echo "Git mirror (origin → org always in sync):"
	@echo "  make push-all                        Push current branch to BOTH origin and org"
	@echo "  make sync-org                        Bring org up to date with origin (main + ml-inference)"
