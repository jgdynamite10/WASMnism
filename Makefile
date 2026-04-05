.PHONY: prereqs build build-frontend deploy-fermyon deploy-akamai deploy-fastly test clean validate benchmark bench-multiregion scorecard runners-up runners-status runners-sync runners-down help

# Default gateway URL (override with URL=...)
URL ?= https://wasm-prompt-firewall-imjy4pe0.fermyon.app
PLATFORM ?= fermyon

# ── Prerequisites ────────────────────────────────────────────
prereqs:
	@echo "=== Checking prerequisites ==="
	@command -v rustc    >/dev/null 2>&1 && echo "  rust:     $$(rustc --version)" || echo "  MISSING: rustc (https://rustup.rs)"
	@command -v cargo    >/dev/null 2>&1 && echo "  cargo:    $$(cargo --version)" || echo "  MISSING: cargo"
	@rustup target list --installed 2>/dev/null | grep -q wasm32-wasip1 && echo "  wasm32:   installed" || echo "  MISSING: rustup target add wasm32-wasip1"
	@command -v spin     >/dev/null 2>&1 && echo "  spin:     $$(spin --version)" || echo "  MISSING: spin (https://developer.fermyon.com/spin/install)"
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
deploy-fermyon:
	$(MAKE) -C edge-gateway deploy-spin

deploy-akamai:
	$(MAKE) -C edge-gateway deploy-akamai

deploy-fastly:
	$(MAKE) -C edge-gateway deploy-fastly

# ── Benchmark (single region, local machine) ─────────────────
validate:
	./bench/run-validation.sh $(PLATFORM) $(URL)

benchmark:
	./bench/reproduce.sh $(PLATFORM) $(URL) $(BENCH_FLAGS)

# ── Benchmark (multi-region, from k6 runners) ────────────────
bench-multiregion:
	./bench/run-multiregion.sh $(PLATFORM) $(URL) $(BENCH_FLAGS)

# ── Scorecard ────────────────────────────────────────────────
scorecard:
	@if [ -z "$(A)" ] || [ -z "$(B)" ]; then \
		echo "Usage: make scorecard A=results/fermyon/<ts> B=results/<other>/<ts> [OUT=scorecard.md]"; \
		exit 1; \
	fi
	python3 bench/build-scorecard.py $(A) $(B) $(OUT)

# ── k6 Runner Infrastructure ────────────────────────────────
runners-up:
	./deploy/k6-runner-setup.sh provision

runners-status:
	./deploy/k6-runner-setup.sh status

runners-sync:
	./deploy/k6-runner-setup.sh sync

runners-down:
	./deploy/k6-runner-setup.sh teardown

# ── Help ─────────────────────────────────────────────────────
help:
	@echo "WASMnism — WASM Edge Gateway Benchmark"
	@echo ""
	@echo "Prerequisites:"
	@echo "  make prereqs                         Check all required tools"
	@echo ""
	@echo "Build & Deploy:"
	@echo "  make build                           Build WASM gateway + frontend"
	@echo "  make deploy-fermyon                  Build + deploy to Fermyon Cloud"
	@echo "  make deploy-akamai                   Build + deploy to Akamai Functions"
	@echo "  make deploy-fastly                   Build + deploy to Fastly Compute"
	@echo "  make test                            Run Rust unit tests"
	@echo ""
	@echo "Benchmark (single region):"
	@echo "  make validate PLATFORM=akamai URL=<url>              Run 9-scenario validation"
	@echo "  make benchmark PLATFORM=akamai URL=<url>             Full pipeline: validate → 7-run → medians"
	@echo "  make benchmark PLATFORM=akamai URL=<url> BENCH_FLAGS='--ml --cold'"
	@echo "  (PLATFORM defaults to 'fermyon'; set to 'akamai', 'fastly', etc. for other platforms)"
	@echo ""
	@echo "Benchmark (multi-region):"
	@echo "  make runners-up                                      Provision 3 Linode k6 runners"
	@echo "  make runners-sync                                    Copy latest scripts to runners"
	@echo "  make bench-multiregion PLATFORM=akamai URL=<url>     Run from all 3 regions"
	@echo "  make runners-down                                    Teardown runners"
	@echo ""
	@echo "Scorecard:"
	@echo "  make scorecard A=<dir1> B=<dir2>     Compare two result sets"
