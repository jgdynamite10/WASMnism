# Benchmark rollout: coordination plan (Tier 2 + GCP)

**Purpose:** Single on-disk plan so you, your team, and **multiple agents** (or humans) can execute in parallel without losing context. Update this file as work completes.

**Confidentiality:** Do **not** put API keys, account IDs, or production IPs in this file if the repo is public. Use `docs/BENCHMARK_ROLLOUT_PLAN.local.md` (gitignored pattern: `*.local.md`) for filled-in tickets, source IPs, and exact windows—copy from the templates below.

---

## How this relates to Cursor “Plan mode”

- **Plan mode** in Cursor is for **collaborative planning** in the IDE (scope, options, step-by-step design) before you implement. It is **not** what produced earlier chat answers unless you explicitly switched to Plan mode in the UI.
- **Recommended workflow:** Use **Plan mode** once to lock **scope, risks, and calendar**; use **Agent mode** (or subagents) to **implement** deploy scripts, run benches, and update `PROJECT_STATE.md` / `AGENT_HANDOVER.md` (private) after each session.
- **This document** is the **persistent** plan—Plan mode can **read and edit** it, but the file is the source of truth for multi-agent handoff.

---

## Goals (edit in place)

| Goal | Owner / agent | Status |
|------|----------------|--------|
| Tier 2: `ml-inference` build + deploy **Akamai** + **AWS Lambda** | TBD | 🟡 Branch `ml-inference` has ML + Lambda; local build + `cargo lambda build` OK. **Cloud deploy** needs operator (`spin aka deploy`, `make deploy-lambda` with `LAMBDA_*`) |
| Artifacts: model + vocab in expected paths; no secrets in git | TBD | 🟡 `gh release download v0.2.0-models` to `edge-gateway/models/toxicity/` (gitignored) + checksums in README |
| **Stakeholder & provider notice** (window + traffic profile) | TBD | 🟡 Checklist in `BENCHMARK_ROLLOUT_PLAN.local.md` — **send** before next heavy k6 (human) |
| **GCP** only: `gcp-runners-up` → bench → `validate-results.py` → teardown | TBD | 🟢 `make gcp-runners-up/sync` + teardown exercised Apr 27; re-run for next bench round. Validate used Apr 13 GCP `multiregion_*` dirs (see W5) |
| Scorecard + contract disclosure (e.g. v3.4, origin = GCP) | TBD | 🟢 `results/rollout_w5_gcp_base_apr13.{md,html,pdf}` from validated GCP dirs; `make report` supports `RESULT_*` overrides |

---

## Workstreams (parallelizable)

Use one row per “agent” or person. Each workstream should link PRs or branches and **log blockers** here.

| ID | Workstream | Inputs | Definition of done |
|----|------------|--------|----------------------|
| W1 | **Tier 2 engineering** | `ml-inference` branch, models, AWS creds | Health + validation pass on both endpoints |
| W2 | **Comms** | W1 endpoints (FQDN/region) | Notices sent; optional acks recorded in `.local.md` |
| W3 | **GCP infrastructure** | `gcloud` project `wasmnism` | 3 runners up, `gcp-runners.env` present locally (gitignored) |
| W4 | **k6 execution** | W1+W3 | Fresh `multiregion_*` dirs, `validate-results.py` green |
| W5 | **Report** | W4 | Scorecards + charts per `docs/AGENT_PLAYBOOK.md` (private) |

**Handoff rule:** W4 must not start until W1 **smoke/validate** is green. W2 can start in parallel with W1 if the **window** is provisional.

---

## Provider contact: best practice (summary)

| Provider | When to contact | How (typical) | What to say (include) |
|----------|-----------------|---------------|------------------------|
| **Akamai** | Any **significant** synthetic load to **your** hostname on Akamai/Functions; follow their load-testing guidance. | **Account / support** path you already use for Akamai; Community reference: [Best Practices for Load Testing with Akamai CDN](https://community.akamai.com/customers/s/article/Best-Practices-for-Load-Testing-with-Akamai-CDN?language=en_US). | Non-destructive **performance** test; **date/time (UTC)**; **peak RPS/VU** (order of magnitude); **regions**; **source** = a few **GCP** egress IPs (put real IPs only in `.local.md`); DRI contact. |
| **Fastly** | Spikes in bandwidth/compute on **your** service; some contracts mention **utilization spikes**—when in doubt, open a ticket **before** the spike. | [Fastly Customer Support](https://www.fastly.com/services/customer-support); tickets: [support.fastly.com](https://support.fastly.com) (per Fastly docs). | Service ID(s), window (UTC), expected **traffic increase**, test type (k6 to **your** property), DRI. **Note:** Fastly’s **penetration / DDoS** testing doc is separate ([Security testing your service behind Fastly](https://docs.fastly.com/products/security-testing-your-service-behind-fastly))—use that path only if your test is in that category; *performance* load is usually a **general support / account** conversation. |
| **Cloudflare** | High RPS from **few** client IPs can trip **abuse** protections; **Workers** limits/quotas may need review. | **Dashboard → Support** (plan-dependent) or **enterprise** TAM/CSM if you have one. **Docs:** [Workers platform limits](https://developers.cloudflare.com/workers/platform/limits/) (includes note on abuse protection and when to **contact support** for high RPS from few IPs). | Zone/account, Worker name, window (UTC), VU/RPS order of magnitude, that traffic is **authorized** load test. |
| **AWS (Lambda)** | Concurrency, throttles, **regional** limits, large deploy artifacts. | **AWS Support** (if you have a paid plan) for **Service Quota** or Lambda concurrency; **Service Quotas** console to request limit increases. | Region(s), expected **invocation rate** and **duration**, memory/timeout, link to your **own** function ARN in `.local.md` only. |

**Rule of thumb:** If the test could be mistaken for an attack (volume from few IPs, sharp ramps), **notify in writing** and keep a **single DRI** reachable during the window.

---

## Copy-paste: notification email (public-safe)

**Subject:** Planned performance benchmark — [Your project] — [date range] UTC

**Body (fill brackets):**

> We will run **authorized, non-destructive load tests** (k6) against our own endpoints for **performance measurement** (not penetration testing).  
> - **Window (UTC):** [start] – [end]  
> - **Property / service:** [hostname or service ID]  
> - **Origin of traffic:** a small number of **Google Cloud** VMs in [regions] (source IPs available on request to support).  
> - **Peak load (approx):** [e.g. up to N concurrent clients / RPS]  
> - **DRI:** [name, email, phone]  
>  
> Please confirm if you need any **allowlist** or **quota** adjustment. We can adjust the window to avoid conflict with your maintenance or known events.

For **Cloudflare**, add: *“We are aware of Workers limits and abuse protections per [Workers limits](https://developers.cloudflare.com/workers/platform/limits/); this is coordinated load to our own Worker.”*

For **Fastly**, add: *“We are load-testing our own Fastly service; if this may trigger a utilization review, we are providing advance notice per your support process.”*

For **AWS**, add: *“We may open a Service Quota request for Lambda [concurrency / other] in [region] if we approach limits.”*

---

## Technical sequence (reference)

1. `git checkout ml-inference` (or work from a PR).  
2. Place model artifacts per branch docs; run **validate** on Akamai + Lambda URLs.  
3. **After** comms (or in parallel for window ≥ lead time): `gcloud config set project wasmnism` → `make gcp-runners-up` → `make gcp-runners-sync`.  
4. `make bench-multiregion-gcp` / `make bench-full-gcp` per `Makefile` and `docs/AGENT_PLAYBOOK.md` (if `AGENT_PLAYBOOK.md` is present locally).  
5. `python3 bench/validate-results.py` on each platform’s `multiregion_*` directory.  
6. `make gcp-runners-down` when finished.  
7. Generate scorecards; disclose **runner origin: GCP** and **contract version**.

---

## Local file for secrets / specifics (create yourself)

Create **`docs/BENCHMARK_ROLLOUT_PLAN.local.md`** (gitignored by `docs/*.local.md`) with:

- Exact **UTC** windows (may shift).  
- **GCP runner IPs** (for vendor tickets).  
- **Service IDs** (Fastly), **zone names** (Cloudflare), **Lambda ARNs** (AWS).  
- **Ticket numbers** and “approved to proceed” notes.  
- **DRIs** and phone numbers.

---

## Checklist before first k6 request

- [ ] Tier 2 (or Tier 1-only scope) **explicitly** decided.  
- [ ] **Validation** script passes for every URL under test.  
- [ ] `bench/validate-results.py` understood; result dirs will use `gcp-*` region names for GCP.  
- [ ] Providers **notified** (or risk accepted in writing for internal runs).  
- [ ] `make security-check` before any commit; **no** `results/` or raw JSON in git.

---

## Revision log

| Date | Change |
|------|--------|
| 2026-04-27 | Initial plan: multi-agent coordination + provider contact summary + links. |
