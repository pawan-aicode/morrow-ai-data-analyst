import argparse
import hashlib
import json
import math
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import (
    DB_PATH,
    MODEL,
    MAX_ROWS,
    AgentError,
    get_schema,
    generate_sql,
    validate_sql,
    execute_sql,
)

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "benchmarks" / "sql_cases.json"
REPORT_DIR = ROOT / "benchmarks" / "reports"
NUMERIC_REL_TOL = 1e-9
NUMERIC_ABS_TOL = 1e-6


def load_cases():
    with CASES_PATH.open(encoding="utf-8") as file:
        cases = json.load(file)

    if not isinstance(cases, list) or not cases:
        raise ValueError("Benchmark case file must contain a non-empty list.")

    required = {
        "id", "category", "name", "question", "reference_sql", "ordered"
    }
    seen = set()

    for case in cases:
        missing = required - case.keys()
        if missing:
            raise ValueError(
                f"Case {case.get('id', '?')} is missing fields: {sorted(missing)}"
            )
        if case["id"] in seen:
            raise ValueError(f"Duplicate benchmark ID: {case['id']}")
        if not isinstance(case["ordered"], bool):
            raise ValueError(f"{case['id']}: ordered must be boolean")
        seen.add(case["id"])

    return cases


def database_fingerprint():
    digest = hashlib.sha256()
    with DB_PATH.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_reference(sql):
    import sqlite3

    uri = DB_PATH.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only = ON")
        cursor = conn.execute(sql)
        columns = [item[0] for item in cursor.description or []]
        rows = cursor.fetchmany(MAX_ROWS + 1)

        if len(rows) > MAX_ROWS:
            raise ValueError(
                f"Reference query exceeded the {MAX_ROWS}-row production limit."
            )

        return columns, [list(row) for row in rows]


def values_equal(expected, actual):
    if expected is None or actual is None:
        return expected is actual

    if (
        isinstance(expected, (int, float))
        and not isinstance(expected, bool)
        and isinstance(actual, (int, float))
        and not isinstance(actual, bool)
    ):
        return math.isclose(
            expected,
            actual,
            rel_tol=NUMERIC_REL_TOL,
            abs_tol=NUMERIC_ABS_TOL,
        )

    return type(expected) is type(actual) and expected == actual


def rows_equal(expected_rows, actual_rows, ordered):
    if len(expected_rows) != len(actual_rows):
        return False

    def row_equal(left, right):
        return (
            len(left) == len(right)
            and all(values_equal(a, b) for a, b in zip(left, right))
        )

    if ordered:
        return all(
            row_equal(expected, actual)
            for expected, actual in zip(expected_rows, actual_rows)
        )

    unmatched = list(actual_rows)
    for expected in expected_rows:
        match_index = next(
            (
                index for index, actual in enumerate(unmatched)
                if row_equal(expected, actual)
            ),
            None,
        )
        if match_index is None:
            return False
        unmatched.pop(match_index)

    return not unmatched


def percentile(values, percentile_value):
    if not values:
        return None

    ordered = sorted(values)
    index = math.ceil((percentile_value / 100) * len(ordered)) - 1
    return round(ordered[max(0, index)], 3)


def evaluate_case(case, schema):
    result = {
        "id": case["id"],
        "category": case["category"],
        "name": case["name"],
        "question": case["question"],
        "status": "not_started",
        "generation_seconds": None,
        "execution_seconds": None,
        "sql": None,
        "expected_columns": None,
        "actual_columns": None,
        "expected_row_count": None,
        "actual_row_count": None,
        "column_match": False,
        "rows_match": False,
        "answer_correct": False,
        "error": None,
    }

    try:
        expected_columns, expected_rows = fetch_reference(
            case["reference_sql"]
        )
        result["expected_columns"] = expected_columns
        result["expected_row_count"] = len(expected_rows)
    except Exception as exc:
        result["status"] = "reference_error"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    generation_start = time.perf_counter()

    try:
        sql = generate_sql(case["question"], schema)
        result["generation_seconds"] = round(
            time.perf_counter() - generation_start, 3
        )
        result["sql"] = sql
    except Exception as exc:
        result["generation_seconds"] = round(
            time.perf_counter() - generation_start, 3
        )
        result["status"] = "generation_failure"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    try:
        validate_sql(sql)
    except AgentError as exc:
        result["status"] = "safety_rejection"
        result["error"] = str(exc)
        return result

    execution_start = time.perf_counter()

    try:
        actual_columns, actual_rows = execute_sql(sql)
        result["execution_seconds"] = round(
            time.perf_counter() - execution_start, 3
        )
    except Exception as exc:
        result["execution_seconds"] = round(
            time.perf_counter() - execution_start, 3
        )
        result["status"] = "execution_failure"
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result

    result["actual_columns"] = actual_columns
    result["actual_row_count"] = len(actual_rows)

    result["column_match"] = actual_columns == expected_columns
    result["rows_match"] = rows_equal(
        expected_rows, actual_rows, case["ordered"]
    )
    result["answer_correct"] = (
        result["column_match"] and result["rows_match"]
    )
    result["status"] = (
        "correct" if result["answer_correct"] else "incorrect_answer"
    )

    return result


def build_summary(results, cases):
    total = len(results)
    counts = Counter(result["status"] for result in results)

    generated = sum(
        result["status"] not in {
            "reference_error",
            "generation_failure",
            "safety_rejection",
        }
        for result in results
    )
    executed = sum(
        result["execution_seconds"] is not None for result in results
    )
    correct = counts["correct"]

    generation_times = [
        result["generation_seconds"]
        for result in results
        if result["generation_seconds"] is not None
    ]
    execution_times = [
        result["execution_seconds"]
        for result in results
        if result["execution_seconds"] is not None
    ]

    category_results = defaultdict(list)
    for result in results:
        category_results[result["category"]].append(result)

    categories = {}
    for category, items in sorted(category_results.items()):
        categories[category] = {
            "total": len(items),
            "correct": sum(item["answer_correct"] for item in items),
            "accuracy_pct": round(
                100 * sum(item["answer_correct"] for item in items)
                / len(items),
                2,
            ),
            "execution_success": sum(
                item["execution_seconds"] is not None for item in items
            ),
        }

    return {
        "total_cases": total,
        "generation_success": generated,
        "generation_success_rate_pct": round(100 * generated / total, 2),
        "execution_success": executed,
        "execution_success_rate_pct": round(100 * executed / total, 2),
        "correct_answers": correct,
        "answer_accuracy_pct": round(100 * correct / total, 2),
        "accuracy_among_executed_pct": round(
            100 * correct / executed, 2
        ) if executed else 0.0,
        "column_schema_matches": sum(
            result["column_match"] for result in results
        ),
        "status_counts": dict(counts),
        "generation_latency_seconds": {
            "mean": round(statistics.mean(generation_times), 3)
            if generation_times else None,
            "median": round(statistics.median(generation_times), 3)
            if generation_times else None,
            "p95": percentile(generation_times, 95),
        },
        "execution_latency_seconds": {
            "mean": round(statistics.mean(execution_times), 3)
            if execution_times else None,
            "median": round(statistics.median(execution_times), 3)
            if execution_times else None,
            "p95": percentile(execution_times, 95),
        },
        "categories": categories,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate the production natural-language-to-SQL pipeline."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run only the first N cases (useful for a smoke test).",
    )
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")

    if not DB_PATH.is_file():
        raise FileNotFoundError(f"Database not found: {DB_PATH}")

    cases = load_cases()
    if args.limit:
        cases = cases[:args.limit]

    schema = get_schema()
    db_hash = database_fingerprint()

    print("=" * 72)
    print("AI DATA ANALYST — SQL BENCHMARK")
    print("=" * 72)
    print(f"Model: {MODEL}")
    print(f"Database: {DB_PATH}")
    print(f"Database SHA256: {db_hash}")
    print(f"Cases: {len(cases)}")
    print("Execution: production validation and read-only execution")
    print()

    results = []

    for index, case in enumerate(cases, 1):
        print(
            f"[{index:02d}/{len(cases):02d}] "
            f"{case['id']} | {case['category']} | {case['name']}"
        )

        result = evaluate_case(case, schema)
        results.append(result)

        generation = result["generation_seconds"]
        execution = result["execution_seconds"]

        generation_text = (
            f"{generation:.2f}s" if generation is not None else "N/A"
        )
        execution_text = (
            f"{execution:.3f}s" if execution is not None else "N/A"
        )

        print(
            f"  {result['status'].upper()} | "
            f"generation={generation_text} | execution={execution_text}"
        )

        if result["error"]:
            print(f"  Error: {result['error']}")
        elif result["status"] == "incorrect_answer":
            print(
                f"  Columns match: {result['column_match']} | "
                f"Rows match: {result['rows_match']}"
            )

    summary = build_summary(results, cases)

    report = {
        "benchmark": "AI Data Analyst SQL Evaluation",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "database_path": str(DB_PATH),
        "database_sha256": db_hash,
        "case_file": str(CASES_PATH),
        "case_count": len(cases),
        "row_limit": MAX_ROWS,
        "numeric_tolerance": {
            "relative": NUMERIC_REL_TOL,
            "absolute": NUMERIC_ABS_TOL,
        },
        "summary": summary,
        "results": results,
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORT_DIR / f"sql_benchmark_{timestamp}.json"

    with report_path.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    print("\n" + "=" * 72)
    print("FINAL SUMMARY")
    print("=" * 72)
    print(f"Cases: {summary['total_cases']}")
    print(
        f"Generation success: {summary['generation_success']}/"
        f"{summary['total_cases']} "
        f"({summary['generation_success_rate_pct']}%)"
    )
    print(
        f"Execution success: {summary['execution_success']}/"
        f"{summary['total_cases']} "
        f"({summary['execution_success_rate_pct']}%)"
    )
    print(
        f"Correct answers: {summary['correct_answers']}/"
        f"{summary['total_cases']} "
        f"({summary['answer_accuracy_pct']}%)"
    )
    print("Status counts:", summary["status_counts"])
    print("Generation latency:", summary["generation_latency_seconds"])
    print("Execution latency:", summary["execution_latency_seconds"])

    print("\nCategory results:")
    for category, metrics in summary["categories"].items():
        print(
            f"  {category:12} "
            f"{metrics['correct']}/{metrics['total']} correct "
            f"({metrics['accuracy_pct']}%)"
        )

    print(f"\nJSON report saved: {report_path}")


if __name__ == "__main__":
    main()
