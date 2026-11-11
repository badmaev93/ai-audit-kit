## 2024-11-11 - [Title]
**Learning:** [Insight]
**Action:** [How to apply next time]

## 2024-11-11 - Fast path in check_honesty
**Learning:** `check_honesty` frequently extracts numbers from large context strings (`question` + `expected` + `trace`). For responses without numbers, doing the expensive extraction on the context is unnecessary.
**Action:** Extract numbers from the `answer` first. If the `answer` has no numbers, we can immediately return `True, []` and avoid concatenating and extracting from the `context`.

## 2024-11-11 - Compiled Regex for tokenization
**Learning:** The `HeuristicJudge._tokens` method re-compiles its regular expression (`r"[а-яёa-z0-9]+"`) on every call. In a run with 500 stochastic passes, this compiles the regex 15,000 times unnecessarily, creating a small but avoidable bottleneck.
**Action:** Extract the compiled regex to a class attribute or module-level constant to speed up execution slightly for heuristic checks.
