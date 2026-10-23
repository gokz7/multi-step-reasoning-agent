"""
run_tests.py - Evaluation suite that runs the REAL agent (real LLM calls).

8 easy questions + 6 tricky questions. For each test it logs:
  - the question
  - the final JSON
  - whether the verifier passed
  - whether the agent retried (and how many times)
  - whether the answer matched the expected answer

Results are saved to:
  logs/test_results.json  - everything, machine-readable
  logs/test_results.md    - readable report (use as the "example run logs" in the submission)

Run:  python run_tests.py
Needs an API key (see README). Takes a few minutes because calls are spaced for free-tier rate limits.
"""

import json                                                       # save results
import os                                                         # make the logs folder
import time                                                       # measure run time

import config                                                     # provider/model names, LOG_DIR
from agent import ReasoningAgent                                  # the agent
from utils import values_match                                    # compare answers

# expected = the correct "comparable_value" (see COMPARABLE_VALUE_RULES in prompts.py)
# expected_status = "failed" for questions that SHOULD not be answered
TEST_CASES = [
    # ---------- EASY: basic arithmetic and time differences ----------
    {"id": "E1", "category": "easy",
     "question": "If a train leaves at 14:30 and arrives at 18:05, how long is the journey?",
     "expected": "215", "expected_status": "success"},                                # 3 h 35 min
    {"id": "E2", "category": "easy",
     "question": "Alice has 3 red apples and twice as many green apples as red. How many apples does she have in total?",
     "expected": "9", "expected_status": "success"},                                  # 3 + 6
    {"id": "E3", "category": "easy",
     "question": "A meeting needs 60 minutes. There are free slots: 09:00-09:30, 09:45-10:30, 11:00-12:00. Which slots can fit the meeting?",
     "expected": "11:00-12:00", "expected_status": "success"},                        # only the 60-min slot
    {"id": "E4", "category": "easy",
     "question": "A box holds 12 eggs. How many eggs are there in 15 boxes?",
     "expected": "180", "expected_status": "success"},                                # 12 x 15
    {"id": "E5", "category": "easy",
     "question": "A movie starts at 19:45 and runs for 2 hours 10 minutes. At what time does it end?",
     "expected": "21:55", "expected_status": "success"},                              # clock time result
    {"id": "E6", "category": "easy",
     "question": "Priya had 50 rupees. She spent 18 rupees on a notebook and 7 rupees on a pen. How much money does she have left?",
     "expected": "25", "expected_status": "success"},                                 # 50 - 18 - 7
    {"id": "E7", "category": "easy",
     "question": "A car travels at 60 km per hour for 2.5 hours. How far does it travel?",
     "expected": "150", "expected_status": "success"},                                # decimal input
    {"id": "E8", "category": "easy",
     "question": "36 students are split equally into 4 groups. How many students are in each group?",
     "expected": "9", "expected_status": "success"},                                  # 36 / 4

    # ---------- TRICKY: where naive reasoning might fail ----------
    {"id": "T1", "category": "tricky - crosses midnight",
     "question": "A train leaves at 23:15 and arrives at 01:40 the next day. How long is the journey?",
     "expected": "145", "expected_status": "success"},                                # naive answer is negative
    {"id": "T2", "category": "tricky - exact boundary",
     "question": "A meeting needs 45 minutes. Free slots: 09:00-09:45, 10:00-10:40, 13:15-14:00. Which slots can fit the meeting?",
     "expected": "09:00-09:45; 13:15-14:00", "expected_status": "success"},           # two exact fits, one 40-min slot
    {"id": "T3", "category": "tricky - multi-step wording",
     "question": "Bob has 5 marbles. Carol has 3 more than twice as many marbles as Bob. How many marbles do they have together?",
     "expected": "18", "expected_status": "success"},                                 # Carol = 2*5+3 = 13, total 18
    {"id": "T4", "category": "tricky - fencepost",
     "question": "A straight fence is 20 metres long with a post every 4 metres, including a post at both ends. How many posts are there?",
     "expected": "6", "expected_status": "success"},                                  # naive answer is 5
    {"id": "T5", "category": "tricky - sequential percentages",
     "question": "A shirt costs 800 rupees. It gets a 25% discount, then 10% tax is added on the discounted price. What is the final price?",
     "expected": "660", "expected_status": "success"},                                # 800*0.75*1.10, naive 25%-10% = 680
    {"id": "T6", "category": "tricky - missing information",
     "question": "Tom is older than Jerry. How old is Tom?",
     "expected": "", "expected_status": "failed"},                                    # should refuse, not guess
]


def is_correct(test, run_output):
    """Did the agent do the right thing for this test?"""
    result = run_output["result"]
    if test["expected_status"] == "failed":                       # agent should NOT give an answer
        return result["status"] == "failed"
    if result["status"] != "success":                             # should have answered but didn't
        return False
    return values_match(run_output["trace"]["comparable_value"], test["expected"])  # compare to the expected answer


def write_markdown_report(records, summary, path):
    """Readable report for the submission's 'example run logs'."""
    lines = ["# Test run results", "",
             f"- Provider / model: `{summary['provider']}` / `{summary['model']}`",
             f"- Tests: {summary['total']}, correct: {summary['correct']}, "
             f"verifier passed: {summary['verifier_passed']}, retried: {summary['retried']}",
             f"- Run time: {summary['seconds']} s", "",
             "| ID | Category | Correct | Status | Verifier passed | Retries |",
             "|---|---|---|---|---|---|"]
    for record in records:                                        # one table row per test
        lines.append(f"| {record['id']} | {record['category']} | {'yes' if record['correct'] else 'NO'} | "
                     f"{record['final_json']['status']} | {record['verifier_passed']} | {record['retries']} |")
    lines.append("")
    for record in records:                                        # full JSON for each test
        lines += [f"## {record['id']} ({record['category']})", "",
                  f"**Question:** {record['question']}", "",
                  f"**Expected:** `{record['expected'] or 'status failed'}` - "
                  f"**Got:** `{record['comparable_value']}` - **Correct:** {record['correct']} - "
                  f"**Verifier passed:** {record['verifier_passed']} - **Retried:** {record['retried']} "
                  f"({record['retries']})", "",
                  "```json", json.dumps(record["final_json"], indent=2, ensure_ascii=False), "```", ""]
    with open(path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines))


def main():
    agent = ReasoningAgent()                                      # real LLM from config/.env
    os.makedirs(config.LOG_DIR, exist_ok=True)
    records = []
    start = time.time()

    for test in TEST_CASES:
        print(f"\n[{test['id']}] {test['question']}")
        output = agent.run(test["question"])                      # run the agent
        result = output["result"]
        checks = result["metadata"]["checks"]
        record = {
            "id": test["id"],
            "category": test["category"],
            "question": test["question"],                         # logged: the question
            "final_json": result,                                 # logged: the final JSON
            "verifier_passed": bool(checks) and all(c["passed"] for c in checks),  # logged: verifier result
            "retried": result["metadata"]["retries"] > 0,         # logged: did it retry
            "retries": result["metadata"]["retries"],
            "expected": test["expected"],
            "comparable_value": output["trace"]["comparable_value"],
            "correct": is_correct(test, output),
        }
        records.append(record)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"-> verifier passed: {record['verifier_passed']} | retried: {record['retried']} "
              f"({record['retries']}) | correct: {record['correct']}")

    summary = {
        "provider": config.PROVIDER,
        "model": config.MODEL_NAME,
        "total": len(records),
        "correct": sum(r["correct"] for r in records),
        "verifier_passed": sum(r["verifier_passed"] for r in records),
        "retried": sum(r["retried"] for r in records),
        "seconds": round(time.time() - start, 1),
    }
    with open(os.path.join(config.LOG_DIR, "test_results.json"), "w", encoding="utf-8") as file:
        json.dump({"summary": summary, "tests": records}, file, indent=2, ensure_ascii=False)
    write_markdown_report(records, summary, os.path.join(config.LOG_DIR, "test_results.md"))

    print(f"\nSUMMARY: {summary['correct']}/{summary['total']} correct, "
          f"{summary['verifier_passed']} verifier passed, {summary['retried']} retried.")
    print("Saved logs/test_results.json, logs/test_results.md and logs/agent_trace.jsonl")


if __name__ == "__main__":
    main()
