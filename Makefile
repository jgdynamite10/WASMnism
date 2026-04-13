.PHONY: prereqs build build-frontend deploy-akamai deploy-fastly deploy-workers test clean validate benchmark bench-multiregion bench-full scorecard report security-check install-hooks cleanup-stale runners-up runners-status runners-sync runners-down gcp-runners-up gcp-runners-status gcp-runners-sync gcp-runners-down help

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
report:
	@if [ -z "$(NAME)" ]; then \
		echo "Usage: make report PLATFORMS=\"akamai fastly workers\" NAME=\"scorecard_name\""; \
		exit 1; \
	fi
	@echo "=== Validating results ==="
	@for p in $(PLATFORMS); do \
		latest=$$(ls -td results/$$p/multiregion_* 2>/dev/null | head -1); \
		if [ -z "$$latest" ]; then echo "ERROR: No results for $$p"; exit 1; fi; \
		DIRS="$$DIRS $$latest"; \
	done; \
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
	@echo "  make bench-multiregion-gcp PLATFORM=akamai URL=<url> Run from all 3 GCP regions"
	@echo "  make bench-full-gcp PLATFORM=akamai URL=<url>        Full suite from GCP (1K VUs, soak, spike)"
	@echo "  make gcp-runners-down                                Teardown GCP runners"
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
