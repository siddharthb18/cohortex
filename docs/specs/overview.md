# Cohortex — Specification Set: Overview & Originality

> Exported from the Cohortex specification doc on 2026-10-02. The doc is the source of truth;
> re-export these files whenever it changes. Diagrams live only in the doc.

## Verdict

**The idea is original enough to build, with three changes.** No existing public project combines agentic reliability investigations, HDD + SSD fleet telemetry, and evals that check every numeric claim against independent SQL. Two close neighbors exist, so the project must be positioned against them and cite them.

1. **Rename it.** "FleetLens" is already used by at least four GitHub projects, including an MCP server for coding agents and a published npm package. The working name is now **Cohortex** (a drive *cohort* is the unit every investigation is about).
2. **Do not build a text-to-SQL chatbot over Drive Stats.** Backblaze's own developer advocate published exactly that in 2025: a LangGraph ReAct agent that writes SQL against Drive Stats, with a public repo. Cohortex never lets the model write SQL; it calls typed, read-only tools, and its product is an investigation report, not a Q&A answer.
3. **Cite the research neighbor.** KORAL (IPDPS 2026) grounds LLM analysis of Alibaba SSD telemetry in knowledge graphs. Cohortex is an engineering platform, not a KG pipeline, and says so in its README.

**On "plagiarism" specifically:** plagiarism means presenting someone else's code or words as your own. Writing the system from scratch, attributing the datasets as their licenses require, and citing related work in the README removes that risk. The realistic risk is a reviewer thinking "this is the Backblaze tutorial"; changes 2 and 3 address that directly.

## Prior art and how Cohortex differs

| Prior work | What it does | Overlap | How Cohortex differs |
| --- | --- | --- | --- |
| [Backblaze ai-agent-demo](https://github.com/backblaze-b2-samples/ai-agent-demo) ([blog](https://www.backblaze.com/blog/building-an-ai-agent-with-backblaze-b2-langchain-and-drive-stats/)) | Notebook agent that turns natural-language questions into SQL over Drive Stats via Trino | Same dataset, agent pattern | No model-written SQL; typed tools only. Multi-step investigations with cited reports. Independent SQL ground truth grades the agent. SSD data, streaming, alerts, deployed platform |
| [KORAL](https://arxiv.org/abs/2602.10246), IPDPS 2026 | LLM + data and literature knowledge graphs for SSD analysis on Alibaba and Google data; reports a faithfulness-precision metric | Evidence-grounded SSD analysis on the Alibaba dataset | No knowledge graph; tool-calling agent over MCP; HDD + SSD; CI-gated evals; production services. Adopts and credits the faithfulness-precision idea |
| Backblaze failure-prediction repos (e.g. [this](https://github.com/nuhamushtaqbtech-star/Hard-Drive-Failure-Prediction), [this](https://github.com/tzujohsu/backblaze-survival-analysis)) | ML models or survival analysis on SMART data | The risk-scoring component | The model is one tool the agent calls, not the product |
| LLM root-cause-analysis research ([FSE 2024 study](https://dl.acm.org/doi/10.1145/3663529.3663841), [FORGE 2026](https://uwaterloo.ca/waterloo-intelligent-systems-engineering-lab/projects/llm-reasoning-failures-cloud-root-cause-analysis)) | Agents diagnosing cloud incidents from logs and metrics | The agentic RCA pattern | Different domain: storage fleet telemetry with public, checkable ground truth |
| [Industrial test-failure analysis report](https://arxiv.org/html/2609.21843) (2026) | Found a multi-agent setup gave no quality gain over one agent at about 3× the latency and 2× the cost | Agent architecture choice | Cohortex builds both and measures the trade-off on its own evals (Evaluation spec, section 4) |

**Cohortex's original contribution, in one sentence:** agentic reliability investigations over public HDD and SSD fleet telemetry, where every numeric claim is verified in CI against independently computed SQL, plus a measured comparison of single-agent and orchestrator-workers designs.

## Name and AI-assisted build policy

**Name.** FleetLens collides with [tata1mg/fleetlens](https://github.com/tata1mg/fleetlens), [cowcow02/fleetlens](https://github.com/cowcow02/fleetlens), [carlok/fleetlens](https://github.com/carlok/fleetlens) and [bryan-tieu/FleetLens](https://github.com/bryan-tieu/FleetLens). No storage or AI software named Cohortex turned up; the only near match is an unrelated 2016 health-research repo, [CohortEx](https://github.com/MTFA/CohortEx). Before creating the GitHub repo, re-search the name on GitHub, PyPI and npm; renaming later only means a find-and-replace across these specs.

**Building with Claude agents is legitimate, if it is honest.** Amazon's intern posting asks for AI-assisted development with critical validation, and Micron encourages AI tools but disqualifies fabricated qualifications. Four rules keep the project defensible:

1. The README has a "How this was built" section stating that Claude agents wrote much of the code from these specs, and that Siddharth designed, reviewed and evaluated it.
2. Some work is human-only and stays that way: error-analysis labels, judge-validation labels, golden-set review, and accepting or rejecting ADRs (Agent build plan, section 3).
3. Every work package ends with an explain-back check: Siddharth can explain each module, change it without help, and defend its trade-offs in an interview.
4. Datasets are attributed per their terms: Backblaze asks users to cite it as the source and not to sell the data ([Drive Stats page](https://www.backblaze.com/cloud-storage/resources/hard-drive-test-data)); the Alibaba logs ask users to cite the DSN 2021 paper ([dataset readme](https://github.com/alibaba-edu/dcbrain/tree/master/ssd_smart_logs)).

## Document map

The set is written so a Claude agent can build any work package from it without guessing; anything the specs do not settle goes into `docs/open-questions.md`, never into invented behavior.

| File | What it settles | Who reads it |
| --- | --- | --- |
| [design.md](design.md) | What the system is: goals, architecture, data layers, flows, decisions (ADRs), deployment | Everyone, first |
| [SRS.md](SRS.md) | What it must do: use cases and numbered functional and non-functional requirements with acceptance tests | Agents implementing features; reviewers checking scope |
| [ERS.md](ERS.md) | How it is built: stack and versions, repo layout, coding and testing standards, CI, security, observability, budgets | Every agent session |
| [contracts.md](contracts.md) | Exact interfaces: dataset mappings, database DDL, Kafka events, REST endpoints, MCP tool schemas, report schema | Agents writing code that crosses a boundary |
| [evaluation.md](evaluation.md) | How quality is measured: metrics, golden-set format, graders, judge validation, CI gate, experiments | Agents building the eval harness; Siddharth |
| [build-plan.md](build-plan.md) | In what order: CLAUDE.md template, work packages with dependencies and acceptance, human-owned tasks | Siddharth, to hand work to agents |

"ERS" here means Engineering Requirements Specification: the constraints on *how* the system is built, complementing the SRS's *what*.

**Reading order for an agent session:** CLAUDE.md → ERS → the work package in the build plan → the SRS requirements and contracts it cites → code.
