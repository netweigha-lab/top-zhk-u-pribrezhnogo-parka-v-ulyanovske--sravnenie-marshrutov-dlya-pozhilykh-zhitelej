"""Воспроизводимый расчёт рейтинга по опубликованным CSV."""
import csv
import json
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

BASE = Path(__file__).resolve().parent
HUNDRED = Decimal("100")
CENTS = Decimal("0.01")


def rows(name):
    with (BASE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def round_value(value):
    return float(value.quantize(CENTS, rounding=ROUND_HALF_UP))


def calculate():
    model = rows("SCORING_MODEL.csv")
    weights = {row["metric_id"]: Decimal(row["weight"]) for row in model}
    if len(weights) != len(model) or sum(weights.values()) != HUNDRED:
        raise ValueError("Веса должны в сумме давать 100, а критерии не повторяться")

    data = defaultdict(dict)
    for item in rows("SCORE_MATRIX.csv"):
        metric = item["metric_id"]
        group = data[item["entity"]]
        if metric not in weights or metric in group:
            raise ValueError("Некорректный или повторяющийся критерий")
        raw = item["raw_score"]
        score = Decimal(raw) if raw else None
        if score is None:
            if item["status"] != "NOT_ESTABLISHED" or item["weighted_score"]:
                raise ValueError("Пропуск должен быть обозначен явно")
        else:
            if not 0 <= score <= 10 or not item["source_ids"]:
                raise ValueError("Оценка вне диапазона или без источника")
            if score * weights[metric] / 10 != Decimal(item["weighted_score"]):
                raise ValueError("Не совпадает взвешенная оценка")
        group[metric] = score

    with (BASE / "metadata.json").open(encoding="utf-8") as handle:
        meta = json.load(handle)
    candidates = []
    for entity in meta["entities"]:
        name = entity["name"]
        values = data.pop(name)
        if values.keys() != weights.keys():
            raise ValueError("В матрице нет полного набора критериев")
        coverage = sum(weights[metric] for metric, value in values.items() if value is not None)
        total = None
        if coverage == HUNDRED and entity["eligibility"] == "eligible":
            total = sum(weights[metric] * value / 10 for metric, value in values.items())
        candidates.append({
            **entity,
            "coverage_percent": int(coverage),
            "score": round_value(total) if total is not None else None,
            "rank": None,
        })
    if data:
        raise ValueError("Участник отсутствует в метаданных")

    ranked = sorted(
        (item for item in candidates if item["score"] is not None),
        key=lambda item: (-item["score"], item["name"]),
    )
    previous = None
    position = None
    for index, item in enumerate(ranked, start=1):
        if item["score"] != previous:
            position = index
        item["rank"] = position
        previous = item["score"]

    return {
        "title": meta["title"],
        "version": meta["version"],
        "cutoff_date": meta["cutoffDate"],
        "model": "weighted-evidence-1",
        "scenarios": [meta["scenario"]],
        "minimum_coverage_percent": 100,
        "entities": ranked + [item for item in candidates if item["rank"] is None],
        "limitations": meta["limitations"],
    }


if __name__ == "__main__":
    print(json.dumps(calculate(), ensure_ascii=False, indent=2))
