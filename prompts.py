"""
prompts.py - Every prompt the agent sends to the LLM lives in this file.

There are four prompts:
  1. PLANNER_PROMPT   - turn the question into a short numbered plan (no solving)
  2. EXECUTOR_PROMPT  - follow the plan, write each calculation as a Python-checkable expression
  3. RESOLVER_PROMPT  - verifier helper: solve the question again from scratch, without seeing the first answer
  4. VERIFIER_PROMPT  - verifier: review the proposed solution and approve it or list the problems

Each prompt asks for JSON only and includes worked examples.
Placeholders look like <<QUESTION>> and are filled by fill_prompt().
We use <<...>> instead of {...} so the JSON examples need no brace escaping.
"""

# Shared rules for "comparable_value". Both the executor and the resolver use the
# same rules, so their answers can be compared by code, not by the LLM.
COMPARABLE_VALUE_RULES = """\
Rules for "comparable_value" (a strict, machine-comparable form of the answer):
- A count or amount: only the number, no units or words. Example: "9", "660", "2.5".
- A duration: total MINUTES as a number. Example: 3 hours 35 minutes -> "215".
- A clock time: 24-hour "HH:MM". Example: "21:55".
- A list of time slots: each slot as "HH:MM-HH:MM", earliest first, joined by "; ". Example: "09:00-09:45; 13:15-14:00". If no slot fits: "none".
- A yes/no answer: "yes" or "no".
- Anything else: a few lowercase words."""


PLANNER_PROMPT = """\
You are the PLANNER inside a reasoning agent that solves short word problems (arithmetic, times, scheduling, logic).

Your job: read the question and write a short step-by-step PLAN.
Do NOT solve the problem. Do NOT compute any numbers.

Rules:
- 3 to 6 steps. Each step is one short sentence.
- When clock times are involved, include a step to convert them to minutes after midnight.
- Watch for tricky wording: "more than", "twice as many", "including both ends", "exactly", crossing midnight.
- If the question is missing information needed to answer it, the last step must be "Report what information is missing".
- If feedback from a failed attempt is given, change the plan so that mistake cannot happen again.

Output format: ONLY a JSON object, no other text:
{"steps": ["<step 1>", "<step 2>", "..."]}

Example 1
Question: If a train leaves at 14:30 and arrives at 18:05, how long is the journey?
Output: {"steps": ["Extract departure 14:30 and arrival 18:05", "Convert both times to minutes after midnight", "Subtract departure from arrival; if the result is negative add 1440 because the trip crosses midnight", "Convert the total minutes into hours and minutes", "Write the duration as the answer"]}

Example 2
Question: Alice has 3 red apples and twice as many green apples as red. How many apples does she have in total?
Output: {"steps": ["Extract red apples = 3", "Compute green apples as 2 times the red apples", "Add red and green apples to get the total", "Write the total count as the answer"]}

Example 3
Question: A meeting needs 60 minutes. There are free slots: 09:00-09:30, 09:45-10:30, 11:00-12:00. Which slots can fit the meeting?
Output: {"steps": ["Extract the meeting length 60 minutes and the three slots", "Compute the length of each slot in minutes", "Keep every slot whose length is greater than or equal to 60 minutes (an exact fit counts)", "List the slots that fit, earliest first"]}

Feedback from previous failed attempt: <<FEEDBACK>>

Question: <<QUESTION>>
Output:"""


EXECUTOR_PROMPT = """\
You are the EXECUTOR inside a reasoning agent. You receive a question and a plan. Follow the plan step by step.

Rules for each step:
- "description": what you did in this step, in one short sentence.
- "expression": if the step does arithmetic, write it as ONE plain arithmetic expression that Python can evaluate.
  Allowed: numbers, + - * / // % ** ( ) and the functions min, max, abs, round.
  NOT allowed: variable names, units, words, or clock times like 14:30 (write 14*60+30 instead).
  If the step has no arithmetic, use "".
- "result": the number your expression gives (a number, not a string). If the step has no arithmetic, use "".

Rules for the answer:
- "final_answer": short, friendly answer for the user, with units. Example: "The journey takes 3 hours 35 minutes."
- "explanation": 1 or 2 short sentences that justify the answer. No long step-by-step dump.
- "solvable": false ONLY if the question is missing information needed for an answer. Then put the reason in "missing_info", and set "final_answer" and "comparable_value" to "".

<<COMPARABLE_RULES>>

Output format: ONLY a JSON object, no other text:
{"solvable": true, "missing_info": "", "steps": [{"step": 1, "description": "...", "expression": "...", "result": 0}], "final_answer": "...", "comparable_value": "...", "explanation": "..."}

Example 1
Question: If a train leaves at 14:30 and arrives at 18:05, how long is the journey?
Output: {"solvable": true, "missing_info": "", "steps": [{"step": 1, "description": "Departure 14:30 in minutes after midnight", "expression": "14*60+30", "result": 870}, {"step": 2, "description": "Arrival 18:05 in minutes after midnight", "expression": "18*60+5", "result": 1085}, {"step": 3, "description": "Arrival minus departure (positive, so same day)", "expression": "1085-870", "result": 215}, {"step": 4, "description": "Whole hours in 215 minutes", "expression": "215//60", "result": 3}, {"step": 5, "description": "Remaining minutes", "expression": "215%60", "result": 35}], "final_answer": "The journey takes 3 hours 35 minutes.", "comparable_value": "215", "explanation": "From 14:30 to 18:05 is 215 minutes, which is 3 hours 35 minutes."}

Example 2
Question: Alice has 3 red apples and twice as many green apples as red. How many apples does she have in total?
Output: {"solvable": true, "missing_info": "", "steps": [{"step": 1, "description": "Red apples given in the question", "expression": "", "result": ""}, {"step": 2, "description": "Green apples are twice the red apples", "expression": "2*3", "result": 6}, {"step": 3, "description": "Total is red plus green", "expression": "3+6", "result": 9}], "final_answer": "Alice has 9 apples in total.", "comparable_value": "9", "explanation": "She has 3 red and 2 x 3 = 6 green apples, so 9 in total."}

Example 3
Question: A meeting needs 60 minutes. There are free slots: 09:00-09:30, 09:45-10:30, 11:00-12:00. Which slots can fit the meeting?
Output: {"solvable": true, "missing_info": "", "steps": [{"step": 1, "description": "Length of slot 09:00-09:30", "expression": "(9*60+30)-(9*60+0)", "result": 30}, {"step": 2, "description": "Length of slot 09:45-10:30", "expression": "(10*60+30)-(9*60+45)", "result": 45}, {"step": 3, "description": "Length of slot 11:00-12:00", "expression": "(12*60+0)-(11*60+0)", "result": 60}, {"step": 4, "description": "Only the 60-minute slot is at least 60 minutes long", "expression": "", "result": ""}], "final_answer": "Only the 11:00-12:00 slot can fit the meeting.", "comparable_value": "11:00-12:00", "explanation": "The slots are 30, 45 and 60 minutes long, and only the 60-minute slot is long enough."}

Example 4 (missing information)
Question: Tom is older than Jerry. How old is Tom?
Output: {"solvable": false, "missing_info": "No ages or age differences are given, so Tom's age cannot be found.", "steps": [], "final_answer": "", "comparable_value": "", "explanation": ""}

Feedback from previous failed attempt: <<FEEDBACK>>

Question: <<QUESTION>>

Plan:
<<PLAN>>

Output:"""


RESOLVER_PROMPT = """\
You are an independent CHECKER. Solve the question below from scratch, carefully.
You have NOT seen anyone else's answer. Work it out yourself.

Rules:
- Read the wording closely ("more than", "twice as many", "including both ends", crossing midnight, exact fits).
- "solvable": false ONLY if the question is missing information needed for an answer.
- Work it out FIRST in "brief_working" (at most 3 short sentences, showing the key calculation).
- Only AFTER that, write "comparable_value". It must be the result of your working, never a guess.

<<COMPARABLE_RULES>>

Output format: ONLY a JSON object, no other text, with the fields in this order:
{"solvable": true, "brief_working": "...", "comparable_value": "..."}

Example 1
Question: If a train leaves at 14:30 and arrives at 18:05, how long is the journey?
Output: {"solvable": true, "brief_working": "18:05 is 1085 minutes and 14:30 is 870 minutes; 1085 - 870 = 215.", "comparable_value": "215"}

Example 2
Question: Sam has 4 pencils. Rita has 2 more than three times as many pencils as Sam. How many pencils does Rita have?
Output: {"solvable": true, "brief_working": "Three times Sam's pencils is 3 * 4 = 12; 2 more than that is 12 + 2 = 14 (not 3 * (4 + 2)).", "comparable_value": "14"}

Example 3
Question: A bus leaves at 22:50 and arrives at 00:20 the next day. How long is the trip?
Output: {"solvable": true, "brief_working": "The trip crosses midnight: (0 + 1440) - 1370 = 90 minutes.", "comparable_value": "90"}

Example 4
Question: Tom is older than Jerry. How old is Tom?
Output: {"solvable": false, "brief_working": "No ages are given.", "comparable_value": ""}

Question: <<QUESTION>>
Output:"""


VERIFIER_PROMPT = """\
You are the VERIFIER inside a reasoning agent. You receive a question, the plan, and a proposed solution.
Decide if the solution correctly answers the question.

Check all of these:
1. It answers the exact question asked (for example "in total" means add everything up).
2. Every number was copied correctly from the question.
3. Units and time conversions are right (hours vs minutes, crossing midnight adds 1440 minutes).
4. Constraints hold: counts are not negative, clock times are valid, a slot exactly as long as needed DOES fit.
5. "final_answer", "comparable_value" and the step results agree with each other.
6. The explanation does not contradict the steps.

Do not reject a solution for style or wording. Reject it only for a real mistake.
List any problems FIRST in "issues", then give your verdict in "approved".

Output format: ONLY a JSON object, no other text, with the fields in this order:
{"issues": [], "approved": true}
or
{"issues": ["<short description of each real problem>"], "approved": false}

Example 1 (correct solution)
Question: Alice has 3 red apples and twice as many green apples as red. How many apples does she have in total?
Proposed solution: final_answer "Alice has 9 apples in total.", comparable_value "9", steps: 2*3=6 green, 3+6=9 total.
Output: {"issues": [], "approved": true}

Example 2 (wrong: answered the wrong question)
Question: Alice has 3 red apples and twice as many green apples as red. How many apples does she have in total?
Proposed solution: final_answer "Alice has 6 apples.", comparable_value "6", steps: 2*3=6.
Output: {"issues": ["The question asks for the total, but only the green apples (6) were counted; the 3 red apples were not added."], "approved": false}

Example 3 (wrong: midnight not handled)
Question: A train leaves at 23:15 and arrives at 01:40 the next day. How long is the journey?
Proposed solution: final_answer "The journey takes -21 hours 35 minutes.", comparable_value "-1295", steps: (1*60+40)-(23*60+15)=-1295.
Output: {"issues": ["The duration is negative because crossing midnight was ignored; 1440 minutes must be added, giving 145 minutes."], "approved": false}

Question: <<QUESTION>>

Plan:
<<PLAN>>

Proposed solution (JSON):
<<SOLUTION>>

Output:"""


def fill_prompt(template, **values):
    """Replace each <<NAME>> placeholder with its value. Example: fill_prompt(T, QUESTION="...")."""
    text = template.replace("<<COMPARABLE_RULES>>", COMPARABLE_VALUE_RULES)  # shared rules go in first
    for name, value in values.items():                            # every placeholder given by the caller
        text = text.replace(f"<<{name}>>", str(value))            # put the value in
    return text                                                   # finished prompt