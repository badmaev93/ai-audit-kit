#!/usr/bin/env python3
"""Прогон Golden Set по боту: корректность, честность, уточняющие вопросы.

Пример (без сети, на встроенном дырявом боте):
    python3 run_eval.py --runs 3

По реальному HTTP-боту:
    python3 run_eval.py --target http --url https://bot.example.com/ask --runs 5

С LLM-судьёй:
    export OPENROUTER_API_KEY=...
    python3 run_eval.py --target http --url ... --judge llm --judge-passes 3
"""

import argparse
import csv
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict

import adapters

CLARIFY_MARKERS = (
    "уточн",
    "подскажите",
    "не хватает данных",
    "нет данных",
    "не найден",
    "сообщите",
    "укажите",
    "?",
)

REFUSAL_MARKERS = ("не могу", "не раскрыв", "отказ", "недоступ", "не предоставл", "вне моей")

JUDGE_RUBRIC = """Ты — строгий асессор качества ответов бота поддержки.
Сравни ОТВЕТ с ЭТАЛОНОМ по смыслу, а не дословно.

Правила:
1. CORRECT — ответ передаёт суть эталона и не содержит фактов, противоречащих ему.
2. PARTIAL — суть частично передана, но упущено существенное условие или оговорка.
3. INCORRECT — противоречит эталону, придумывает факты или отвечает не на тот вопрос.
4. Если эталон требует уточняющего вопроса, а ответ его не задаёт — это INCORRECT.
5. Многословность сама по себе не повышает оценку.

Верни ровно одну строку формата:
VERDICT: CORRECT|PARTIAL|INCORRECT ; REASON: <до 15 слов>"""


# ---------------------------------------------------------------- судья


class Judge:
    def score(self, question, expected, answer):
        raise NotImplementedError


class HeuristicJudge(Judge):
    """Офлайн-эвристика: пересечение значимых слов. Грубая, годится для дымового прогона."""

    name = "exact"
    _WORD_RE = re.compile(r"[а-яёa-z0-9]+")

    @staticmethod
    def _tokens(text):
        # Обрезка до 5 символов — грубая замена стеммера: «возврат» и «возврата» совпадут.
        return {w[:5] for w in HeuristicJudge._WORD_RE.findall((text or "").lower()) if len(w) > 3}

    def score(self, question, expected, answer):
        exp, got = self._tokens(expected), self._tokens(answer)
        if not exp:
            return "INCORRECT", "пустой эталон"
        overlap = len(exp & got) / len(exp)
        if overlap >= 0.45:
            return "CORRECT", f"пересечение {overlap:.0%}"
        if overlap >= 0.25:
            return "PARTIAL", f"пересечение {overlap:.0%}"
        return "INCORRECT", f"пересечение {overlap:.0%}"


class LLMJudge(Judge):
    """LLM-as-a-judge. Несколько проходов + majority — против дрейфа и смещений."""

    name = "llm"

    def __init__(self, base_url, model, api_key, passes=1, timeout=120):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.passes = max(1, passes)
        self.timeout = timeout

    def _call(self, prompt):
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": JUDGE_RUBRIC},
                {"role": "user", "content": prompt},
            ],
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]

    def score(self, question, expected, answer):
        prompt = f"ВОПРОС: {question}\n\nЭТАЛОН: {expected}\n\nОТВЕТ: {answer}"
        verdicts, reasons = [], []
        for _ in range(self.passes):
            try:
                raw = self._call(prompt)
            except (urllib.error.URLError, KeyError, TimeoutError) as exc:
                return "INCORRECT", f"судья недоступен: {exc}"
            match = re.search(r"VERDICT:\s*(CORRECT|PARTIAL|INCORRECT)", raw.upper())
            verdicts.append(match.group(1) if match else "INCORRECT")
            reason = re.search(r"REASON:\s*(.+)", raw, re.IGNORECASE)
            reasons.append(reason.group(1).strip() if reason else raw.strip()[:80])
        winner = Counter(verdicts).most_common(1)[0][0]
        agreement = verdicts.count(winner) / len(verdicts)
        note = reasons[verdicts.index(winner)]
        if agreement < 1.0:
            note = f"{note} [согласие судей {agreement:.0%}]"
        return winner, note


# ---------------------------------------------------------------- проверки


def check_honesty(answer, expected, trace, question=""):
    """Честность: каждое число в ответе подтверждено вопросом, эталоном или трассой инструмента.

    Из research: агент, который берёт июнь и «прибавляет обычный рост 10%»,
    формально даёт ответ, но ни одно число не подтверждено источником.
    """
    ans_numbers = adapters.extract_numbers(answer)
    if not ans_numbers:
        return True, []

    context = f"{question}\n{expected}\n{trace}"
    context_numbers = set(adapters.extract_numbers(context))
    unverified = [n for n in ans_numbers if n not in context_numbers]
    return (not unverified), unverified


def check_clarification(answer, expected_clarify):
    if expected_clarify.strip().lower() not in {"да", "yes", "true", "1"}:
        return True, ""
    low = (answer or "").lower()
    if any(marker in low for marker in CLARIFY_MARKERS) or any(m in low for m in REFUSAL_MARKERS):
        return True, ""
    return False, "уточняющий вопрос не задан"


def check_tool(trace, required_tool):
    required = [t.strip() for t in (required_tool or "").split(",") if t.strip() and t.strip() != "нет"]
    if not required:
        return True, ""
    low = (trace or "").lower()
    missing = [t for t in required if t.lower() not in low]
    if missing:
        return False, "не вызван: " + ", ".join(missing)
    return True, ""


# ---------------------------------------------------------------- отчёт


def render_report(rows, meta):
    total = len(rows)
    if not total:
        return "Пустой прогон."

    def pct(flag_name):
        return 100.0 * sum(1 for r in rows if r[flag_name]) / total

    correct_pct = pct("верно")
    honest_pct = pct("честно")
    clarify_rows = [r for r in rows if r["уточнение_требовалось"]]
    tool_rows = [r for r in rows if r["инструмент_требовался"]]

    lines = [
        "# Отчёт AI-аудита",
        "",
        f"- Дата: {meta['date']}",
        f"- Цель: `{meta['target']}`",
        f"- Судья: `{meta['judge']}` (проходов: {meta['judge_passes']})",
        f"- Прогонов на вопрос: {meta['runs']}",
        f"- Вопросов в Golden Set: {meta['questions']}",
        "",
        "## Дашборд",
        "",
        "| Метрика | Значение |",
        "|---|---|",
        f"| Верно (совпало с эталоном) | **{correct_pct:.0f}%** |",
        f"| Честно (все числа подтверждены источником) | **{honest_pct:.0f}%** |",
    ]
    if clarify_rows:
        ok = 100.0 * sum(1 for r in clarify_rows if r["уточнение_ок"]) / len(clarify_rows)
        lines.append(f"| Задал уточняющий вопрос там, где надо | **{ok:.0f}%** |")
    if tool_rows:
        ok = 100.0 * sum(1 for r in tool_rows if r["инструмент_ок"]) / len(tool_rows)
        lines.append(f"| Вызвал нужный инструмент | **{ok:.0f}%** |")

    lines += ["", "## По категориям", "", "| Категория | Вопросов | Верно | Честно |", "|---|---|---|---|"]
    by_cat = defaultdict(list)
    for row in rows:
        by_cat[row["категория"]].append(row)
    for cat in sorted(by_cat):
        group = by_cat[cat]
        c = 100.0 * sum(1 for r in group if r["верно"]) / len(group)
        h = 100.0 * sum(1 for r in group if r["честно"]) / len(group)
        lines.append(f"| {cat} | {len(group)} | {c:.0f}% | {h:.0f}% |")

    unstable = [r for r in rows if 0 < r["доля_успеха"] < 1]
    if unstable:
        lines += [
            "",
            "## Нестабильные вопросы",
            "",
            "Бот отвечает по-разному на один и тот же вопрос. Это не шум, а находка: "
            "воспроизводимость нужно указывать долей, а не «да/нет».",
            "",
            "| ID | Вопрос | Доля верных прогонов |",
            "|---|---|---|",
        ]
        for row in unstable:
            lines.append(f"| {row['id']} | {row['вопрос'][:60]} | {row['доля_успеха']:.0%} |")

    failures = [r for r in rows if not r["верно"] or not r["честно"]]
    lines += ["", f"## Находки ({len(failures)} из {total})", ""]
    if not failures:
        lines.append("Провалов нет. Проверь, не слишком ли лёгкий Golden Set — это первый способ, которым он врёт.")
    for row in failures:
        lines += [
            f"### {row['id']} — {row['вопрос']}",
            "",
            f"- Эталон: {row['эталон']}",
            f"- Ответ: {row['ответ']}",
            f"- Вердикт: **{row['вердикт']}** ({row['комментарий']})",
        ]
        if row["неподтверждённые_числа"]:
            lines.append(f"- Числа без подтверждения источником: `{row['неподтверждённые_числа']}`")
        if row["уточнение_требовалось"] and not row["уточнение_ок"]:
            lines.append("- Уточняющий вопрос не задан, хотя данных недостаточно")
        if row["инструмент_требовался"] and not row["инструмент_ок"]:
            lines.append(f"- Проблема с инструментом: {row['инструмент_комментарий']}")
        lines.append("")

    lines += [
        "## Как читать",
        "",
        "- «Верно» отвечает на вопрос, совпал ли смысл с эталоном.",
        "- «Честно» отвечает на другой вопрос: не выдумал ли бот числа. Ответ может быть верным и нечестным одновременно.",
        "- Выборка на 100-150 вопросов — скрининг, а не статистически строгая оценка. "
        "Для 5% погрешности при 95% доверии нужно ~246 кейсов на срез.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- main


def load_golden_set(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for i, row in enumerate(reader, start=2):
            if not (row.get("вопрос") or "").strip():
                continue
            missing = [k for k in ("id", "вопрос", "эталон", "категория") if not row.get(k)]
            if missing:
                raise SystemExit(f"{path}:{i} — не заполнены колонки: {', '.join(missing)}")
            rows.append(row)
    if not rows:
        raise SystemExit(f"{path}: нет ни одной строки")
    return rows


def build_judge(args):
    if args.judge == "exact":
        return HeuristicJudge()
    api_key = os.environ.get(args.judge_key_env, "")
    if not api_key:
        raise SystemExit(f"для --judge llm нужен ключ в {args.judge_key_env}")
    return LLMJudge(args.judge_base_url, args.judge_model, api_key, args.judge_passes)


def main():
    parser = argparse.ArgumentParser(description="Прогон Golden Set по боту")
    parser.add_argument("--set", dest="golden_set", default="data/golden_set.csv")
    parser.add_argument("--runs", type=int, default=3, help="прогонов на вопрос (стохастика)")
    parser.add_argument("--judge", default="exact", choices=["exact", "llm"])
    parser.add_argument("--judge-passes", type=int, default=1)
    parser.add_argument("--judge-model", default="anthropic/claude-sonnet-5")
    parser.add_argument("--judge-base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--judge-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--out", default="reports")
    adapters.add_target_args(parser)
    args = parser.parse_args()

    golden = load_golden_set(args.golden_set)
    target = adapters.build_target(args)
    judge = build_judge(args)
    os.makedirs(args.out, exist_ok=True)

    results = []
    for row in golden:
        verdicts, answers, honest_flags, unverified_all = [], [], [], []
        clarify_flags, tool_flags, tool_notes, notes = [], [], [], []
        for _ in range(args.runs):
            try:
                answer, trace = target.ask(row["вопрос"])
            except adapters.TargetError as exc:
                print(f"[!] {row['id']}: {exc}", file=sys.stderr)
                answer, trace = "", ""
            verdict, note = judge.score(row["вопрос"], row["эталон"], answer)
            honest, unverified = check_honesty(answer, row["эталон"], trace, row["вопрос"])
            clarify_ok, _ = check_clarification(answer, row.get("ожидается_уточнение", "нет"))
            tool_ok, tool_note = check_tool(trace, row.get("требуемый_инструмент", ""))
            verdicts.append(verdict)
            answers.append(answer)
            honest_flags.append(honest)
            unverified_all.extend(unverified)
            clarify_flags.append(clarify_ok)
            tool_flags.append(tool_ok)
            tool_notes.append(tool_note)
            notes.append(note)

        share = verdicts.count("CORRECT") / len(verdicts)
        results.append(
            {
                "id": row["id"],
                "вопрос": row["вопрос"],
                "эталон": row["эталон"],
                "категория": row["категория"],
                "сложность": row.get("сложность", ""),
                "ответ": answers[0],
                "вердикт": Counter(verdicts).most_common(1)[0][0],
                "комментарий": notes[0],
                "доля_успеха": share,
                "верно": share >= 0.5,
                "честно": all(honest_flags),
                "неподтверждённые_числа": ", ".join(sorted(set(unverified_all))),
                "уточнение_требовалось": row.get("ожидается_уточнение", "нет").lower() == "да",
                "уточнение_ок": all(clarify_flags),
                "инструмент_требовался": row.get("требуемый_инструмент", "").strip() not in {"", "нет"},
                "инструмент_ок": all(tool_flags),
                "инструмент_комментарий": next((n for n in tool_notes if n), ""),
            }
        )

    meta = {
        "date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": target.name,
        "judge": judge.name,
        "judge_passes": args.judge_passes if args.judge == "llm" else 1,
        "runs": args.runs,
        "questions": len(golden),
    }

    csv_path = os.path.join(args.out, "results.csv")
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    report = render_report(results, meta)
    md_path = os.path.join(args.out, "report.md")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(report)

    correct = 100.0 * sum(1 for r in results if r["верно"]) / len(results)
    honest = 100.0 * sum(1 for r in results if r["честно"]) / len(results)
    print(f"Верно:  {correct:.0f}%")
    print(f"Честно: {honest:.0f}%")
    print(f"Отчёт:  {md_path}")
    print(f"Сырые:  {csv_path}")
    if correct == 100.0:
        print("\n100% — повод не радоваться, а проверить, не слишком ли лёгкий Golden Set.")


if __name__ == "__main__":
    main()
