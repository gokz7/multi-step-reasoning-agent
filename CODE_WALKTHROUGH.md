# Code Walkthrough

A file-by-file explanation of the agent, in the order the program runs.

**Flow:** `config` → `llm_client` → `planner` → `executor` (+ `calculator`) → `verifier` → `agent` loop → output JSON.

---

## 1. `config.py` – settings

Keeps every setting in one place, so no other file has hard-coded values.

- **Load `.env`** – reads the API key and settings from the `.env` file.
- **Provider and model** – which LLM to use (Gemini by default) and which model.
- **Retry settings** – the agent gets 2 retries when an answer fails verification. A failing API call is tried 3 times, 20 seconds apart.
- **Spacing** – at least 4 seconds between calls, so the free tier doesn't block requests.
- **Tolerance** – two numbers count as equal if they differ by less than 0.000001 (so `215` and `215.0` match).
- **Log paths** – where log files are saved.

## 2. `llm_client.py` – talking to the LLM

Gives every provider the same method, `ask(prompt) -> text`. The rest of the code never knows which LLM is behind it.

- **`LLMClient` (base class)** – shared logic. `ask()` waits if needed, calls the model, and retries on errors. After 3 failed tries it raises an error.
- **`GeminiClient` / `OpenAIClient` / `AnthropicClient`** – about 10 lines each; each only knows how to send one prompt to its provider. Gemini is called in JSON mode.
- **`MockClient`** – a fake LLM that returns pre-written replies in order. Used by the offline tests (no key, no internet).
- **`get_client()`** – reads the provider setting and creates the right client.

## 3. `prompts.py` – all prompts

All four prompts live in this one file.

- **`COMPARABLE_VALUE_RULES`** – one strict answer format shared by two prompts. A duration is always total minutes (`"215"`); a slot list is `"09:00-09:45; 13:15-14:00"`. Because both solvers use the same format, plain code can compare their answers.
- **`PLANNER_PROMPT`** – "Write a plan, don't solve." Returns `{"steps": [...]}`. 3 examples.
- **`EXECUTOR_PROMPT`** – "Follow the plan; write every calculation as an expression like `18*60+5`." Returns steps, final answer, comparable value and a short explanation. 4 examples, including one with missing information.
- **`RESOLVER_PROMPT`** – "Solve this from scratch." It never sees the first answer, so agreement is meaningful. Returns `{"solvable", "brief_working", "comparable_value"}`, **reasoning before answer**, because LLMs write left to right and an answer written first is a guess. 4 examples.
- **`VERIFIER_PROMPT`** – "Review this solution; reject only real mistakes." Returns `{"issues": [...], "approved": true/false}`, problems listed before the verdict, for the same reason. One correct example, two wrong ones.
- **`fill_prompt()`** – replaces `<<QUESTION>>`-style placeholders. `<< >>` is used instead of `{ }` because Python's `.format()` would clash with the braces in the JSON examples.

## 4. `calculator.py` – safe math

Computes expressions like `(18*60+5)-(14*60+30)` → `215` without `eval()`, because `eval()` would run any code the LLM writes.

- **Allowed lists** – only `+ - * / // % **`, brackets, and `min max abs round`.
- **`safe_eval()`** – turns the text into a syntax tree, then calls `_evaluate()`.
- **`_evaluate()`** – walks the tree piece by piece. A number is returned as is; `a + b` computes both sides and adds them. Anything else (variable names, text, `import`) raises an error. Powers are capped at 10, so `2**100000` is refused.

## 5. `utils.py` – helpers

- **`parse_json_response()`** – strips ```` ```json ```` fences and keeps only the `{...}` part of an LLM reply.
- **`to_number()`** – `"1,200"` → `1200.0`; returns `None` for non-numbers.
- **`normalize_text()`** – lowercase, no spaces, any dash becomes `-`, list items sorted.
- **`values_match()`** – numbers are compared with tolerance; text is compared after cleaning. So `"09:00 - 09:45; 13:15–14:00"` matches `"13:15-14:00; 09:00-09:45"`.
- **`format_plan()`** – `["a", "b"]` → `"1. a\n2. b"`.

## 6. `planner.py` – Phase 1: Planner

Fills the planner prompt with the question (plus feedback from a failed attempt, if any), sends it, and reads back the list of steps. An empty plan raises an error, and the agent retries.

## 7. `executor.py` – Phase 2: Executor

Asks the LLM to solve the question by following the plan, then **re-does every calculation in Python**.

- **LLM call** – gets the solution as JSON.
- **Loop over steps** – each step with an expression is computed by `safe_eval` and saved as `python_result`. A broken expression (e.g. `14:30`) saves the error instead. Nothing is judged here; the verifier compares.

## 8. `verifier.py` – Phase 3: Verifier

Runs four checks, cheapest first. Each returns `{check_name, passed, details}`.

| Check | Type | What it catches |
|---|---|---|
| `format_check` | code | Missing answer, comparable value, explanation or steps |
| `arithmetic_check` | code | LLM says `3+6 = 10`; Python says 9 → fail |
| `independent_resolve` | LLM | A fresh solve, without seeing the answer, gets a different result |
| `llm_review` | LLM | Logic, unit and constraint mistakes (negative counts, midnight, exact-fit slots) |

- **`verify()`** – runs the two code checks first. If either fails, the two LLM checks are skipped (saves 2 API calls), since a retry is needed anyway.
- **`confirm_unsolvable()`** – when the executor says "information is missing", gets a second opinion from the resolver.

## 9. `agent.py` – the loop

Connects the three phases and decides success, retry or failure.

**`run()` – up to 3 attempts (1 + 2 retries):**
1. Plan, then execute. If that crashes (bad JSON, API down), record a `pipeline_error` and retry.
2. If the executor says information is missing **and** the resolver agrees → stop with `failed` (retrying can't add facts). If they disagree → retry.
3. Verify. All checks pass → `success`. Any fail → turn the failed checks into feedback and retry.
4. After the last failed attempt → `failed` with the reason.

Other parts:
- **`_build_feedback()`** – writes the failure message passed to the next attempt.
- **`_result()`** – builds the output JSON in exactly the required schema.
- **`_finish()`** – saves the full working of every attempt to `logs/agent_trace.jsonl`. This is where the hidden chain-of-thought goes; the user never sees it.
- **`solve()`** – notebook interface; returns only the user-facing JSON.
- **`main()`** – CLI; asks for questions until you type `exit`.

## 10. `run_tests.py` – evaluation suite (real LLM)

- **`TEST_CASES`** – 8 easy and 6 tricky questions, each with the expected answer.

| Tricky test | Trap | Correct | Naive answer |
|---|---|---|---|
| T1 crosses midnight | 23:15 → 01:40 | 145 min | negative |
| T2 exact boundary | 45-min meeting, 45-min slots | 2 slots fit | exact fits excluded |
| T3 wording | "3 more than twice" Bob's 5 | 18 total | wrong order of steps |
| T4 fencepost | 20 m, post every 4 m, both ends | 6 | 5 |
| T5 percentages | 25% off, then 10% tax on 800 | 660 | 680 (25% − 10%) |
| T6 missing info | "Tom is older than Jerry. How old is Tom?" | `failed` | a guessed age |

- **`is_correct()`** – compares the agent's answer with the expected one. For T6, "correct" means status `failed`.
- **`main()`** – runs every test and records what the brief asks for: question, final JSON, verifier passed, retried. Saves `logs/test_results.json` and `logs/test_results.md`.

## 11. `tests/test_agent_logic.py` – offline tests (fake LLM)

Proves the loop works using `MockClient`, with no key needed.

- **Loop tests** – success on the first try; an arithmetic slip caught and fixed on retry; never verified → `failed` after 2 retries; missing information stops early; a bad JSON reply is retried; working never leaks to the user.
- **Calculator tests** – time math is right; unsafe code is rejected; divide-by-zero raises an error.
- **Helper tests** – answer matching ignores order, spaces and dash style; JSON is pulled out of code fences.