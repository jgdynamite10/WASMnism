# Benchmark rollout plan (this repository)

The full **Benchmark rollout: coordination plan (Tier 2 + GCP)** is **not** committed. Keep your real plan locally as `docs/BENCHMARK_ROLLOUT_PLAN.md` (list that path in `.gitignore` so it is never pushed).

**Suggested format:** YAML frontmatter (`name`, `overview`, `isProject: false`) plus Markdown sections, like Cursor **Plan** (`.plan.md`) files.

**Content to include:** goals (Tier 2, GCP, scorecards), workstreams W1 through W5, vendor contact summary, copy-paste notice email, technical sequence. Use `docs/BENCHMARK_ROLLOUT_PLAN.local.md` for tickets, GCP egress IPs, and ARNs (gitignored by `docs/*.local.md`).

**See also:** `docs/benchmark_contract.md` (v3.4). Private: `AGENT_HANDOVER.md`, `PROJECT_STATE.md` if you use them.

After adding `docs/BENCHMARK_ROLLOUT_PLAN.md` to `.gitignore`, run `git rm --cached docs/BENCHMARK_ROLLOUT_PLAN.md` if the file was previously tracked, then commit.
