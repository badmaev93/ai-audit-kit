#!/usr/bin/env python3
"""Security-прогон: prompt injection, утечки, excessive agency.

Каждая проба гоняется N раз — поведение LLM стохастическое, «сработало один раз»
и «сработало всегда» это разные находки. В отчёте доля успеха, не «да/нет».

Пример:
    python3 run_security.py --runs 5
    python3 run_security.py --target http --url https://bot.example.com/ask --runs 5

Этот скрипт — для тестирования систем, на которые у вас есть письменное разрешение
владельца. Автоматика покрывает известные паттерны; косвенные инъекции через RAG
и цепочки через tool calling всё равно требуют ручной работы.
"""

import argparse
import csv
import datetime as dt
import os
import re
import sys
from collections import defaultdict

import adapters

OWASP_TITLES = {
    "LLM01": "Prompt Injection",
    "LLM02": "Sensitive Information Disclosure",
    "LLM03": "Supply Chain",
    "LLM04": "Data and Model Poisoning",
    "LLM06": "Excessive Agency",
}

OWASP_FIX = {
    "LLM01": "Сканер инъекций на входе + Self-Ask перед ответом; системный промпт на уровне API, не в тексте",
    "LLM02": "Разграничение доступа в RAG-базе; убрать ключи и внутренние URL из промпта",
    "LLM03": "SBOM + непрерывное сканирование зависимостей",
    "LLM04": "Валидация источников данных и запись в память только по белому списку",
    "LLM06": "Human-in-the-loop на деструктивные и внешние действия; сузить scope токенов инструментов",
}

NIST_MAP = {
    "LLM01": "MEASURE 1 — adversarial-тесты не проводились",
    "LLM02": "GOVERN 1 — нет data governance",
    "LLM03": "MAP 1 — не определён scope компонентов",
    "LLM04": "MAP 1 — не определён scope данных",
    "LLM06": "MANAGE 1 — нет матрицы решений по рискам",
}

SEVERITY = {"LLM01": "high", "LLM02": "critical", "LLM03": "medium", "LLM04": "medium", "LLM06": "critical"}


def load_attacks(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = []
        for i, row in enumerate(reader, start=2):
            if not (row.get("payload") or "").strip():
                continue
            # Запятая внутри незакавыченного regex (\d{2,}) съезжает колонками — ловим сразу.
            if None in row or any(v is None for v in row.values()):
                raise SystemExit(
                    f"{path}:{i} — сбилось число колонок. Закавычь поля с запятыми, "
                    "особенно regex вида \\d{2,}"
                )
            rows.append(row)
    if not rows:
        raise SystemExit(f"{path}: нет ни одной пробы")
    return rows


def probe_succeeded(answer, marker_pattern):
    """Проба удалась, если в ответе виден маркер компрометации."""
    if not answer:
        return False, ""
    try:
        match = re.search(marker_pattern, answer, re.IGNORECASE)
    except re.error as exc:
        print(f"[!] плохой regex '{marker_pattern}': {exc}", file=sys.stderr)
        return False, ""
    return (bool(match), match.group(0) if match else "")


def render_report(rows, meta):
    total = len(rows)
    hit = [r for r in rows if r["доля_успеха"] > 0]
    always = [r for r in rows if r["доля_успеха"] == 1.0]

    lines = [
        "# Отчёт по безопасности AI-системы",
        "",
        f"- Дата: {meta['date']}",
        f"- Цель: `{meta['target']}`",
        f"- Проб: {total}, прогонов на пробу: {meta['runs']}",
        f"- Сработало хотя бы раз: **{len(hit)} из {total}**, стабильно: **{len(always)}**",
        "",
        "## Сводка по OWASP LLM Top 10",
        "",
        "| Категория | Проб | Сработало | Severity | NIST AI RMF | Рекомендация |",
        "|---|---|---|---|---|---|",
    ]
    by_cat = defaultdict(list)
    for row in rows:
        by_cat[row["категория_owasp"]].append(row)
    for cat in sorted(by_cat):
        group = by_cat[cat]
        hits = sum(1 for r in group if r["доля_успеха"] > 0)
        title = OWASP_TITLES.get(cat, "")
        sev = SEVERITY.get(cat, "medium") if hits else "—"
        lines.append(
            f"| {cat} {title} | {len(group)} | {hits} | {sev} | "
            f"{NIST_MAP.get(cat, '')} | {OWASP_FIX.get(cat, '')} |"
        )

    lines += ["", "## Сработавшие пробы", ""]
    if not hit:
        lines.append(
            "Ни одна проба не прошла. Это не значит, что система защищена: автоматика покрывает "
            "известные паттерны. Косвенные инъекции через документы в RAG и цепочки через tool "
            "calling проверяются вручную."
        )
    for row in sorted(hit, key=lambda r: -r["доля_успеха"]):
        lines += [
            f"### {row['id']} — {row['описание']} ({row['категория_owasp']}, {row['вектор']})",
            "",
            f"- Воспроизводимость: **{row['доля_успеха']:.0%}** ({row['успехов']} из {meta['runs']} прогонов)",
            f"- Payload: `{row['payload'][:200]}`",
            f"- Маркер в ответе: `{row['найденный_маркер'][:120]}`",
            f"- Ответ: {row['ответ'][:400]}",
            f"- Что делать: {OWASP_FIX.get(row['категория_owasp'], '')}",
            "",
        ]

    lines += [
        "## Оговорки",
        "",
        "- Одна и та же инъекция может сработать в одном прогоне и не сработать в другом. "
        "Поэтому в отчёте доля успеха, а не «да/нет».",
        "- Автосканирование не заменяет ручную работу: tailored-атаки под бизнес-логику, "
        "косвенные инъекции через содержимое RAG-документов и abuse function calling нужно проверять руками.",
        "- Полную защиту даёт не один механизм, а комбинация: внешний фильтр на входе + самопроверка модели.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Security-прогон бота по OWASP LLM Top 10")
    parser.add_argument("--attacks", default="data/attacks_ru.csv")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--out", default="reports")
    adapters.add_target_args(parser)
    args = parser.parse_args()

    attacks = load_attacks(args.attacks)
    target = adapters.build_target(args)
    os.makedirs(args.out, exist_ok=True)

    results = []
    for probe in attacks:
        successes, answers, markers = 0, [], []
        for _ in range(args.runs):
            try:
                answer, _ = target.ask(probe["payload"])
            except adapters.TargetError as exc:
                print(f"[!] {probe['id']}: {exc}", file=sys.stderr)
                answer = ""
            ok, marker = probe_succeeded(answer, probe["маркер_успеха"])
            if ok:
                successes += 1
                markers.append(marker)
            answers.append(answer)
        results.append(
            {
                "id": probe["id"],
                "категория_owasp": probe["категория_owasp"],
                "вектор": probe["вектор"],
                "описание": probe["описание"],
                "payload": probe["payload"],
                "успехов": successes,
                "доля_успеха": successes / args.runs,
                "найденный_маркер": markers[0] if markers else "",
                "ответ": answers[0],
            }
        )

    meta = {
        "date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "target": target.name,
        "runs": args.runs,
    }

    csv_path = os.path.join(args.out, "security_results.csv")

    def sanitize_row(row):
        sanitized = {}
        for k, v in row.items():
            if isinstance(v, str) and v.startswith(('=', '+', '-', '@', '\t', '\r')):
                sanitized[k] = "'" + v
            else:
                sanitized[k] = v
        return sanitized

    sanitized_results = [sanitize_row(r) for r in results]
    with open(csv_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(sanitized_results)

    md_path = os.path.join(args.out, "report_security.md")
    with open(md_path, "w", encoding="utf-8") as handle:
        handle.write(render_report(results, meta))

    hits = sum(1 for r in results if r["доля_успеха"] > 0)
    print(f"Сработало проб: {hits} из {len(results)}")
    print(f"Отчёт: {md_path}")
    print(f"Сырые: {csv_path}")


if __name__ == "__main__":
    main()
