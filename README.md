# ai-audit-kit

A zero-dependency toolkit for running fixed-scope **AI Agent & Chatbot Audits** (evaluation, hallucination checks, and security probing).

Runs a **Golden Set** against your bot, measures semantic correctness, numerical honesty, clarification behavior, and tool selection across multiple stochastic runs, probes for prompt injection & OWASP LLM vulnerabilities, and generates Markdown + CSV audit reports mapped to **OWASP LLM Top 10** and **NIST AI RMF**.

Built with Python 3.9+ standard library only (no third-party dependencies required).

> **Language note:** CLI flags and architecture are documented in English below. The bundled demo datasets (`data/golden_set.csv`, `data/attacks_ru.csv`), built-in `mock` bot, and generated Markdown report strings currently use Russian examples and column headers (`вопрос`, `эталон`, etc.) matching the parser scripts.

## Quick Start

```bash
cd ai-audit-kit
python3 run_eval.py --runs 3          # run Golden Set evaluation
python3 run_security.py --runs 5      # run security probes
open reports/report.md                # evaluation report (+ reports/results.csv)
open reports/report_security.md       # security report (+ reports/security_results.csv)
```

By default, the target is `mock`: a built-in intentionally flawed support bot that reproduces real-world agent failure modes (fabricating extrapolated expenses when data is missing, ignoring policy edge cases such as defective vs. non-defective returns, and leaking its system prompt). Use it to inspect the full pipeline offline before connecting a real agent.

## Connecting a Real Bot

**HTTP endpoint.** Your bot accepts `POST {"question": "..."}` and returns `{"answer": "...", "trace": "..."}`:

```bash
python3 run_eval.py --target http --url https://bot.example.com/ask --runs 5
python3 run_eval.py --target http --url ... --answer-field text --trace-field steps \
  --header "Authorization: Bearer XXX"
```

The `trace` field captures execution telemetry (which tools were called, which RAG chunks were retrieved). Without `trace`, honesty verification is weaker because numbers in the answer can only be cross-checked against the question and ground-truth reference.

**OpenAI-compatible model** (OpenRouter, local server, or OpenAI directly):

```bash
export OPENROUTER_API_KEY=...
python3 run_eval.py --target openai --model anthropic/claude-haiku-4.5 \
  --system-prompt-file prompts/system.txt --runs 5
```

## Evaluator (`--judge`)

| Mode | When to use |
|---|---|
| `--judge exact` *(default)* | Offline smoke test. Heuristic word-overlap check to verify the pipeline runs; not suitable for client audit reports. |
| `--judge llm` | Real audit evaluation using an LLM rubric (`OPENROUTER_API_KEY` required). |

```bash
python3 run_eval.py --target http --url ... --judge llm --judge-passes 3
```

`--judge-passes 3` runs three judging passes with majority voting. LLM judges have known biases (sensitivity to option ordering, verbosity bias, drift over time); multiple passes paired with a fixed rubric dampen variance. When judge passes disagree, the report records the agreement ratio (e.g., `67%`) so you can review split decisions manually.

## What Gets Measured

| Metric | Definition |
|---|---|
| **Correctness** | Semantic match with the SME ground-truth answer (`CORRECT` verdict in the majority of `--runs`) |
| **Honesty** | Every numeric value in the answer is grounded in the user question, ground-truth reference, or tool execution `trace` |
| **Clarification** | When required input data is missing, the bot asks a clarifying question instead of guessing |
| **Tool Usage** | The expected tool(s) appear in the execution `trace` |

**Correctness and honesty measure different failure modes.** An answer can be simultaneously "correct" and dishonest: a number happens to match by coincidence, but the agent fabricated it without retrieving it from a source.

`--runs N` executes each question `N` times because LLM outputs are stochastic: "worked once" and "works reliably" are very different findings. Questions with split outcomes are surfaced in the **Unstable Questions** section of the report.

## Golden Set Format

`data/golden_set.csv` (current parser expects Russian column headers as listed below):

| Column header | Meaning |
|---|---|
| `id` | Case identifier (`G001`, `G002`, ...) |
| `вопрос` *(question)* | Real user query taken from production logs |
| `эталон` *(reference)* | Ground-truth answer verified by a domain expert |
| `категория` *(category)* | `happy` / `edge` / `adversarial` |
| `сложность` *(difficulty)* | `easy` / `medium` / `hard` |
| `источник` *(source)* | Provenance of the test case |
| `требуемый_инструмент` *(required_tool)* | Expected tool(s): `knowledge_base`, `sql`, `crm`, `calculator`, `email`, or `нет` (none). Comma-separated if multiple |
| `ожидается_уточнение` *(expects_clarification)* | `да` (yes) if information is missing and the bot must ask for clarification |

**Curation rules:**

1. Pull test cases from real production logs rather than inventing synthetic prompts.
2. Explicitly include hard cases: boundary conditions, ambiguous queries, and traps where a plausible-sounding wrong answer is easy to generate.
3. Have a domain SME verify every reference answer. A silently wrong reference label is worse than having no test.
4. Treat the Golden Set as a living, versioned artifact: every new production failure becomes a regression test case.
5. A 100% pass rate is not a reason to celebrate. A Golden Set lies in two ways: either it is too easy or it is stale; both look like all green checks.

The bundled 15-row CSV is a starter e-commerce demo example, not a production client benchmark.

## Security Probes

`data/attacks_ru.csv` contains 20 probes covering direct and indirect prompt injection, system prompt and PII leakage, excessive agency, and memory poisoning. The `маркер_успеха` *(success marker)* column defines the regex pattern indicating probe compromise.

`run_security.py` outputs `reports/report_security.md` and `reports/security_results.csv`, grouping findings by **OWASP LLM Top 10** category with severity ratings, **NIST AI RMF** mappings, and remediation guidance.

- **Larger injection corpus:** 22k-row Russian prompt-injection dataset (`github.com/Dmtr-Dr/prompt-injections`).
- **Deeper automated scanners:** Garak (NVIDIA, 50+ attack classes), PyRIT (Microsoft, multi-turn red-teaming), Promptfoo (CI/CD eval & security gate).

Automated probes cover known patterns only. Indirect prompt injections embedded in RAG documents and multi-step tool-calling exploit chains still require manual review. **Run security probes only against systems for which you have explicit written authorization from the owner.**

## Scope & Limitations

- A 100–150 question Golden Set is an initial screening pass, not a statistically strict benchmark (achieving a ±5% margin of error at 95% confidence requires roughly ~246 samples per slice).
- Heuristic honesty checking catches fabricated numbers; fabricated non-numeric facts require an LLM judge backed by explicit reference assertions.
- Tool usage verification only works when the target exposes execution telemetry via `trace`.

## Next Step: CI/CD Gate

After the initial audit, the Golden Set remains in the client's repository. The natural next step is adding a PR merge gate (running the eval suite on every PR and blocking merges below threshold, typically 95%) alongside a full nightly run with Slack drift alerts, all inside a single CI workflow.
