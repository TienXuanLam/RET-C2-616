# RET-C2-616 — RetailSupplierQualitySLAScorecardAgent

> **Category**: Cat 2 (orchestrates multiple steps to accomplish a specific use case)
> **Industry**: RET
> **Inherits**: AgentBaseGraph (L1-direct); `base_type: DocGenerationAgent` in config/agent.yaml is a descriptive label only (see comment there for rationale), not an actual base class
> **Status**: Draft

## Overview

Generates a multi-dimensional supplier SLA scorecard from procurement
performance data (delivery, defect/return, invoice accuracy, responsiveness).
Scores four KPI dimensions against configurable thresholds, flags
Subcontract Act (下請法) Article 4 prohibited-act conditions (unjustified
return rate, payment delay), and has an LLM generate a scorecard report with
per-supplier KPI summaries, trend narratives, corrective recommendations,
Subcontract Act compliance status, and GX Scope 3 data quality notes.
Outputs a structured JSON scorecard plus a Markdown report, with an S-4
audit log recording Subcontract Act compliance evidence.

## Why This Template Exists

This template is **one production unit of the Agent 1000 line** — not a standalone
deliverable. The project goal is to make us *capable of producing* 1,000+ templates
per FY26 September capacity. That capability is what unlocks AGENTIC STAR as the
global de facto platform for enterprise agent development.

Of every design decision in this template, ask:

> "Does this make the next template faster, or only this one better?"

If your answer is the latter, reconsider — generalize at Level 2, or refactor the
pattern. A template that is technically beautiful but cannot be replicated quickly
across industries fails the mission. See `/agenticai/project-charter.md` for the
three-layer vision and full purpose context.

## Requirements

- Python >= 3.11
- An `ANTHROPIC_API_KEY` secret for per-supplier scorecard narrative generation.

### Behaviour without the platform

The four KPI dimensions and Subcontract Act Article 4 flags are entirely
deterministic — computed by `KPIScoringNode` before the LLM ever runs, never
an LLM judgment call. When `ANTHROPIC_API_KEY` is unavailable or the LLM call
fails for a supplier, that supplier's narrative falls back to a deterministic
template built from the same KPI scores and flags. If every supplier in a
batch falls back, `MainNode` returns `status=retry` rather than silently
shipping an all-fallback scorecard.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest tests/ -v
```

## Project Structure

```
RET-C2-616/
├── docs/                 Design specification and test specification
├── src/
│   ├── api/server.py     Standalone HTTP entry point
│   ├── graph/            Outer AgentBaseGraph
│   ├── nodes/            Pre-process (payload normalization), main (KPI
│   │                     scoring + scorecard narrative), post-process
│   │                     (output assembly + S-3 PII gate)
│   ├── schemas/state.py  Flat TypedDict state
│   └── services/         Supplier normalization, KPI scoring, scorecard
│                         narrative, output assembly services
├── tests/                Unit, integration, and proof-of-boundary tests
├── config/
│   ├── agent.yaml        Static manifest
│   ├── config.yaml       Runtime parameters
│   ├── kpi_thresholds.yaml     KPI scoring thresholds
│   └── subcontract_rules.yaml  Subcontract Act Article 4 rule thresholds
└── cli.py                Marketplace entry point
```

## Customising

- `config/config.yaml`: `max_retry`, `timeout_s`.
- `config/kpi_thresholds.yaml`: the four KPI dimension scoring thresholds
  consulted by `KPIScoringNode`.
- `config/subcontract_rules.yaml`: the Subcontract Act Article 4 prohibited-act
  thresholds (unjustified return rate, payment delay days) consulted by
  `KPIScoringNode`.

## License

MIT — see [LICENSE](LICENSE).

## Status of this repository

This repository is provided as-is, with no warranty and no support commitment. See the
license for details.
