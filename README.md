# Multi-Step Reasoning Agent with Self-Checking

A small agent that solves word problems (arithmetic, times, scheduling, logic) in three phases:
**Planner → Executor → Verifier**, retries when verification fails, and shows the user only the
final answer and a short explanation. The full working stays in logs and metadata.

## How it works

```
question
   │
   ▼
PLANNER (LLM) ── numbered plan, no solving
   │
   ▼
EXECUTOR (LLM + Python) ── each calculation written as an expression, then computed by a safe Python calculator
   │
   ▼
VERIFIER ── 1. format_check        (code)  all fields present
            2. arithmetic_check    (code)  Python result == LLM's claimed result, for every step
            3. independent_resolve (LLM)   solve again from scratch, without seeing the answer; must match
            4. llm_review          (LLM)   look for logic, unit and constraint mistakes
   │
   ├── all pass  → status "success"
   ├── any fail  → failed checks become feedback → retry plan + execute (max 2 retries)
   └── still failing after retries → status "failed" with the reason
```

Special case: if the executor says the question is missing information, the independent solver is asked
for a second opinion. If both agree, the agent stops at once with `"failed"` (retrying cannot add missing facts).
If they disagree, it retries.

## Output

```json
{
  "answer": "The journey takes 3 hours 35 minutes.",
  "status": "success",
  "reasoning_visible_to_user": "From 14:30 to 18:05 is 215 minutes, which is 3 hours 35 minutes.",
  "metadata": {
    "plan": "1. Extract departure and arrival | 2. Convert to minutes | ...",
    "checks": [{"check_name": "arithmetic_check", "passed": true, "details": "All 5 expressions match Python's results."}],
    "retries": 0
  }
}
```

The user only needs `answer` and `reasoning_visible_to_user`. The step-by-step working of every attempt
(plans, expressions, all checks) is written to `logs/agent_trace.jsonl`, never to the user.

## How to run

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # Windows   (Mac/Linux: cp .env.example .env)
# put your Gemini key in .env  (free key: https://aistudio.google.com)
```

| What | Command |
|---|---|
| CLI (type questions) | `python agent.py` |
| Notebook / import | `from agent import solve` then `solve("A box holds 12 eggs...")` |
| Evaluation suite (real LLM, 14 questions) | `python run_tests.py` |
| Offline logic tests (no key, no internet) | `python -m unittest discover -s tests -v` |

Switch provider without touching code: set `LLM_PROVIDER=openai` or `anthropic` in `.env`
and install that package (`pip install openai` / `pip install anthropic`).

## Project structure

See [CODE_WALKTHROUGH.md](CODE_WALKTHROUGH.md) for a file-by-file explanation of the code.

| File | Role |
|---|---|
| `prompts.py` | **All prompts live here**: planner, executor, resolver, verifier, plus shared answer-format rules |
| `planner.py` | Phase 1 – plan |
| `executor.py` | Phase 2 – follow the plan; Python computes every expression |
| `verifier.py` | Phase 3 – the four checks |
| `agent.py` | The loop (retries, failure handling), `solve()` and the CLI |
| `llm_client.py` | One `ask(prompt)` interface for Gemini / OpenAI / Anthropic, plus `MockClient` for tests |
| `calculator.py` | Safe arithmetic evaluator (no `eval()`) |
| `utils.py` | JSON parsing, answer comparison, plan formatting |
| `config.py` | All settings (provider, model, retries, rate-limit spacing) |
| `run_tests.py` | 8 easy + 6 tricky questions, writes `logs/test_results.md` and `.json` |
| `tests/test_agent_logic.py` | 12 offline tests of the loop using scripted LLM replies |

## Assumptions

- Times are 24-hour `HH:MM`. A journey whose arrival is earlier than departure crosses midnight (+1440 minutes).
- A free slot that is **exactly** as long as the meeting fits it.
- Durations are compared in minutes; the user-facing answer uses hours and minutes.
- A question that is missing information should end as `"failed"` with the reason, not a guess.
- Questions are short, self-contained word problems; no outside knowledge or web lookup is needed.
- Default model is `gemini-3.1-flash-lite` (stable, available on the free tier). `gemini-flash-latest` was tried first but returned `503 UNAVAILABLE` (high demand) during testing. Any model can be set with `LLM_MODEL` in `.env`.

## Prompt design

**Why the prompts look this way**

- **JSON-only output, with the exact shape shown.** Every phase is parsed by code, so free text would break the loop. Gemini is also called in JSON mode.
- **The planner is told not to compute.** Keeping planning and calculation apart means the plan is a checklist the executor must follow, and it makes mistakes easier to locate.
- **The executor writes arithmetic as expressions, not just answers.** LLMs are good at setting up a calculation and unreliable at doing it. Python computes every expression, so arithmetic slips are caught by code, not by another LLM opinion.
- **Times are written as `14*60+30`, not `14:30`.** This forces the conversion into minutes to be explicit and checkable.
- **A shared `comparable_value` format.** The executor and the independent resolver both give their answer in the same strict form (minutes for durations, `HH:MM-HH:MM; ...` for slot lists). That lets plain code decide whether two independent solves agree, instead of asking an LLM "are these the same?".
- **The resolver never sees the first solution.** If it did, it would tend to agree with it. Independence is what makes the comparison meaningful.
- **The reviewer is told to reject only real mistakes, not style.** Without this line, reviewers tend to raise wording complaints and cause needless retries.
- **Each prompt has 3–4 worked examples**, including failure cases (missing information, a negative midnight duration, counting only part of a total), so the model sees what a rejection looks like.
- **Feedback from failed checks is passed into the next plan and execution**, so a retry is a correction, not a re-roll.
- **Placeholders use `<<QUESTION>>` instead of `{question}`**, because Python's `.format()` would break on the `{ }` braces in the JSON examples.
- **Cheap checks run first.** If Python already found an arithmetic error, the two LLM checks are skipped and the agent retries straight away. This saves API calls on the free tier.

**What didn't work well**

All of these came up in real runs with `gemini-3.1-flash-lite`.

- **Answer-before-reasoning in the resolver prompt caused a false rejection.** The first version asked for `{"comparable_value": ..., "brief_working": ...}`, in that order. On T3 ("3 more than twice as many as Bob's 5"), the resolver wrote `16`, which is the naive reading 2 × (5 + 3), and *then* worked it out correctly to 18 in `brief_working`. The executor's correct 18 was rejected three times and the run ended `failed`. Because LLMs generate left to right, the answer field must come after the reasoning field. The resolver now outputs `brief_working` first, and the verifier outputs `issues` before `approved`. The good part: the agent refused rather than returning a wrong answer, which is the safe failure mode.
- **Hidden library retries made the agent look frozen.** `gemini-flash-latest` returned `503 UNAVAILABLE` (high demand). The Gemini SDK retried silently with growing back-off, so a single call hung with no output. Fix: SDK retries turned off (`attempts=1`), a 60-second timeout per call, and our own retry loop prints every failure (`[LLM] call failed ...`). The default model was also switched to `gemini-3.1-flash-lite`.
- **An old API key in a Windows environment variable silently overrode `.env`**, which gave `401 API key not valid`. `python-dotenv` doesn't overwrite existing variables by default, so `.env` is now loaded with `override=True`.
- **The free tier is unreliable under load.** Several calls in the evaluation run returned `503` or `504`. The retry loop recovered every time, but a long outage would end a question as `failed` for infrastructure reasons, not reasoning ones. A paid tier, or a fallback model, would fix this.
- **The LLM checks can disagree with each other.** On T3 the reviewer approved the answer while the resolver rejected it. The agent requires *all* checks to pass, which favours safety (no wrong answers) over coverage (some correct answers get refused).

**What I would improve with more time**

- Run the independent resolver 2–3 times and take a majority vote, instead of one comparison.
- Let the executor emit small structured operations (e.g. "slot length", "add minutes to time") with dedicated, tested Python functions, so even logic like "which slots fit" is computed by code, not only arithmetic.
- Add a check that every number used in the expressions actually appears in the question (catches copied-wrong numbers).
- A bigger, harder test set, measured over several runs, since LLM output varies between runs.
- Use the provider's structured-output / JSON-schema feature to guarantee field types, not just JSON.

## Results

Model: `gemini-3.1-flash-lite`, 8 easy + 6 tricky questions.

| Run | Correct | Verifier passed | Retried | Notes |
|---|---|---|---|---|
| Run 1 – [`logs/run1_before_fix.md`](logs/run1_before_fix.md) | 13/14 | 13/14 | 1 | T3 refused after 2 retries: the resolver wrote its answer before its reasoning (see "What didn't work well") |
| Run 2 – [`logs/test_results.md`](logs/test_results.md) | **14/14** | 14/14 | 0 | After putting reasoning before the answer in the resolver and verifier prompts |

Retry behaviour on real LLM output is shown in run 1 (T3). It is also covered deterministically by the offline tests (`tests/test_agent_logic.py`): an arithmetic slip caught by Python and fixed on retry, an answer that never verifies ending as `failed`, and bad JSON being retried.

14 questions on one run is a small sample: it shows the design works, not that it is robust. See "What I would improve".

## Example run logs

- `logs/test_results.md` – readable report: each question, final JSON, verifier result, retries, correct or not
- `logs/run1_before_fix.md` / `.json` – the first run, before the prompt fix (includes the T3 refusal)
- `logs/test_results.json` – the same, machine-readable
- `logs/agent_trace.jsonl` – full internal trace (plans, steps, every attempt's checks) for each run