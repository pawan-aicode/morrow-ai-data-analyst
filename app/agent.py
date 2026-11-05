import json
import numbers
import re
import time
import urllib.request
import urllib.error
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sales.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen3.5:4b-q4_K_M"

MAX_ROWS = 200
REQUEST_TIMEOUT = 180
MAX_QUERY_SECONDS = 5


class AgentError(Exception):
    """Expected, user-facing agent error."""


def get_schema():
    """Read table and column information from the actual database."""
    if not DB_PATH.is_file():
        raise AgentError(f"Database not found: {DB_PATH}")

    uri = DB_PATH.as_uri() + "?mode=ro"

    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            conn.execute("PRAGMA query_only = ON")
            tables = conn.execute("""
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """).fetchall()

            parts = []
            for (table,) in tables:
                columns = conn.execute(
                    f'PRAGMA table_info("{table}")'
                ).fetchall()

                description = ", ".join(
                    f"{column[1]} ({column[2]})"
                    for column in columns
                )
                parts.append(f"{table}({description})")

            foreign_keys = []
            for (table,) in tables:
                rows = conn.execute(
                    f'PRAGMA foreign_key_list("{table}")'
                ).fetchall()
                for row in rows:
                    foreign_keys.append(
                        f"{table}.{row[3]} -> {row[2]}.{row[4]}"
                    )

            result = "Tables:\n" + "\n".join(parts)
            if foreign_keys:
                result += "\nForeign keys:\n" + "\n".join(foreign_keys)
            return result

    except sqlite3.Error as exc:
        raise AgentError(f"Could not inspect database schema: {exc}") from exc



def _extract_sql_response(raw_response):
    """Extract and syntax-check exactly one complete SQLite query."""
    if not isinstance(raw_response, str) or not raw_response.strip():
        raise AgentError("The model returned an empty or invalid SQL response.")

    response = raw_response.strip()

    if response.startswith("```"):
        fenced = re.fullmatch(
            r"```(?:sql)?[ \t]*\r?\n(.*?)\r?\n```",
            response,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not fenced:
            raise AgentError("The model returned malformed SQL formatting.")
        sql = fenced.group(1).strip()
    else:
        if "```" in response:
            raise AgentError("The model returned malformed SQL formatting.")
        sql = response

    if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.IGNORECASE):
        raise AgentError("The model must return SQL only, starting with SELECT or WITH.")

    # Compile without executing the query, using the actual database schema.
    uri = DB_PATH.as_uri() + "?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            conn.execute("PRAGMA query_only = ON")
            conn.execute("EXPLAIN " + sql)
    except sqlite3.Error as exc:
        raise AgentError(
            f"The model returned invalid or incomplete SQL: {exc}"
        ) from exc

    return sql



def generate_sql(question, schema):
    """Ask the local Ollama model to generate one SQLite query."""
    system_prompt = f"""
You are a careful business data analyst that writes SQLite SQL.

Use only tables and columns in this schema:
{schema}

Rules:
- Return exactly one read-only SELECT query, optionally using WITH.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
  REPLACE, ATTACH, DETACH, PRAGMA, or multiple statements.
- Do not guess column names.
- Treat requested output column names as an exact output contract.
- If the question specifies a name for a result column, use that exact name as its SQL alias with AS.
- Do not replace requested output names with synonyms or alternative aliases.
- For example, if the question asks for "revenue", write the expression as AS revenue, not AS total_revenue.
- For revenue from orders, use order_items.quantity * order_items.unit_price.
- If the question is ambiguous, make a reasonable assumption and state it
  separately only if asked. For now return SQL only.
- Return only SQL, without Markdown fences or explanations.
""".strip()

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
        ],
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0,
            "num_predict": 400,
        },
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT
        ) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise AgentError(
            "Could not reach Ollama. Check that the Ollama service is running."
        ) from exc
    except (TimeoutError, json.JSONDecodeError) as exc:
        raise AgentError(f"Model request failed: {exc}") from exc

    if not isinstance(data, dict):
        raise AgentError("Ollama returned an invalid response.")

    message = data.get("message")
    if not isinstance(message, dict):
        raise AgentError("Ollama response is missing its message.")

    return _extract_sql_response(message.get("content"))


def validate_sql(sql):
    """Apply conservative checks before SQLite sees model-generated SQL."""
    cleaned = sql.strip()

    if not cleaned:
        raise AgentError("The model returned an empty SQL query.")

    # Permit one optional trailing semicolon, but no statement chaining.
    without_trailing_semicolon = cleaned[:-1] if cleaned.endswith(";") else cleaned
    if ";" in without_trailing_semicolon:
        raise AgentError("Multiple SQL statements are not allowed.")

    if not re.match(r"^(SELECT|WITH)\b", without_trailing_semicolon, re.I):
        raise AgentError("Only SELECT queries and read-only CTEs are allowed.")

    # Conservative keyword denylist. This supplements, not replaces,
    # SQLite's read-only connection.
    forbidden = re.compile(
        r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|"
        r"ATTACH|DETACH|PRAGMA|VACUUM|REINDEX|ANALYZE)\b",
        re.IGNORECASE,
    )
    if forbidden.search(without_trailing_semicolon):
        raise AgentError("The query contains a disallowed SQL keyword.")

    return without_trailing_semicolon

def _format_summary_value(value):
    """Format numeric values without unnecessary decimal places."""
    if isinstance(value, numbers.Integral):
        return f"{value:,}"
    if isinstance(value, numbers.Real):
        if float(value).is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def _deterministic_group_summary(columns, rows):
    """Summarize extrema for simple categorical-versus-numeric results."""
    if len(columns) != 2 or len(rows) < 2:
        return None

    numeric_indexes = []
    for index in range(2):
        values = [row[index] for row in rows]
        if all(
            isinstance(value, numbers.Real) and not isinstance(value, bool)
            for value in values
        ):
            numeric_indexes.append(index)

    if len(numeric_indexes) != 1:
        return None

    measure_index = numeric_indexes[0]
    label_index = 1 - measure_index
    measure_name = columns[measure_index]
    label_name = columns[label_index]

    values = [row[measure_index] for row in rows]
    highest = max(values)
    lowest = min(values)

    highest_labels = [
        str(row[label_index]) for row in rows
        if row[measure_index] == highest
    ]
    lowest_labels = [
        str(row[label_index]) for row in rows
        if row[measure_index] == lowest
    ]

    highest_text = ", ".join(highest_labels)
    lowest_text = ", ".join(lowest_labels)

    return (
        f"Among the returned rows, the highest {measure_name} was "
        f"{_format_summary_value(highest)} for {highest_text}. "
        f"The lowest was {_format_summary_value(lowest)} for {lowest_text}."
    )


def _deterministic_scalar_summary(columns, rows):
    """Explain recognized single-value monetary and count results."""
    if len(columns) != 1 or len(rows) != 1 or len(rows[0]) != 1:
        return None

    value = rows[0][0]
    if not isinstance(value, numbers.Real) or isinstance(value, bool):
        return None

    column = str(columns[0]).strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", column).strip("_")

    monetary_terms = (
        "revenue", "amount", "price", "sales", "total_value",
        "order_value", "average_order_value", "avg_order_value",
    )
    count_terms = (
        "count", "quantity", "units", "number_of_orders",
    )

    if any(term in normalized for term in monetary_terms):
        label = normalized.replace("_", " ").capitalize()
        return f"The {label.lower()} is ₹{_format_summary_value(value)}."

    if any(term in normalized for term in count_terms):
        label = normalized.replace("_", " ").capitalize()
        return f"The {label.lower()} is {_format_summary_value(value)}."

    return None


def explain_results(question, columns, rows):
    """Explain query results using only the returned data."""
    if not rows:
        return "No rows matched this question."

    scalar_summary = _deterministic_scalar_summary(columns, rows)
    if scalar_summary:
        return scalar_summary

    deterministic_summary = _deterministic_group_summary(columns, rows)
    if deterministic_summary:
        return deterministic_summary

    preview = rows[:20]
    data_context = {
        "question": question,
        "columns": columns,
        "row_count": len(rows),
        "rows_preview": preview,
        "note": (
            "These are the complete rows returned by the SQL query, not a "
            "truncated preview. The SQL query has already applied any LIMIT. "
            "Answer the user's question directly using these rows. "
            "Do not add unnecessary uncertainty about unseen rows."
        ),
    }

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a concise business data analyst. Explain the "
                    "provided query results in plain English. Use only "
                    "numbers and facts present in the supplied data. Do not "
                    "invent causes, trends, or business explanations. "
                    "Treat the supplied rows as the complete SQL query result. "
                    "If the query asks for the top N and returns N rows, answer "
                    "directly from those rows without claiming more data is needed. "
                    "Do not generate SQL. Keep the answer to 2-4 sentences."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(data_context, ensure_ascii=False),
            },
        ],
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "num_predict": 180},
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request, timeout=REQUEST_TIMEOUT
        ) as response:
            data = json.loads(response.read().decode("utf-8"))

        explanation = data.get("message", {}).get("content", "").strip()
        if not explanation:
            return "Results retrieved successfully; no explanation was generated."
        return explanation

    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return "Results retrieved successfully, but the explanation service failed."

def _read_only_authorizer(action, arg1, arg2, database, source):
    """Allow only read-oriented SQLite operations."""
    allowed_actions = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_RECURSIVE,
    }

    if action not in allowed_actions:
        return sqlite3.SQLITE_DENY

    if action == sqlite3.SQLITE_READ:
        if database not in (None, "main"):
            return sqlite3.SQLITE_DENY

    if action == sqlite3.SQLITE_FUNCTION:
        function_name = (arg2 or "").lower()
        if function_name in {"load_extension", "readfile", "writefile"}:
            return sqlite3.SQLITE_DENY

    return sqlite3.SQLITE_OK



def execute_sql(sql):
    """Execute one query with SQLite read-only mode and a row cap."""
    safe_sql = validate_sql(sql)
    uri = DB_PATH.as_uri() + "?mode=ro"

    try:
        with sqlite3.connect(uri, uri=True, timeout=5) as conn:
            conn.execute("PRAGMA query_only = ON")
            conn.set_authorizer(_read_only_authorizer)

            deadline = time.monotonic() + MAX_QUERY_SECONDS

            def query_deadline():
                return int(time.monotonic() >= deadline)

            conn.set_progress_handler(query_deadline, 1000)

            cursor = conn.execute(safe_sql)
            columns = [item[0] for item in cursor.description or []]
            rows = cursor.fetchmany(MAX_ROWS + 1)

            if len(rows) > MAX_ROWS:
                raise AgentError(
                    f"Query returned more than {MAX_ROWS} rows. "
                    "Please narrow the question."
                )

            return columns, [list(row) for row in rows]

    except sqlite3.Error as exc:
        raise AgentError(f"SQLite rejected the generated query: {exc}") from exc


def ask(question):
    """Run the end-to-end natural-language-to-SQL pipeline."""
    if not isinstance(question, str) or not question.strip():
        raise AgentError("Please enter a business question.")

    if len(question) > 2000:
        raise AgentError("Question is too long; keep it under 2,000 characters.")

    start = time.perf_counter()
    schema = get_schema()
    sql = generate_sql(question.strip(), schema)
    columns, rows = execute_sql(sql)
    explanation = explain_results(question.strip(), columns, rows)
    elapsed = time.perf_counter() - start

    return {
        "question": question.strip(),
        "model": MODEL,
        "sql": sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "elapsed_seconds": round(elapsed, 2),
        "explanation": explanation,
    }


if __name__ == "__main__":
    print("Local AI Data Analyst")
    print("Type a business question, or 'exit' to quit.\n")

    while True:
        try:
            question = input("Question> ").strip()
            if question.lower() in {"exit", "quit"}:
                break

            result = ask(question)
            print("\nGenerated SQL:\n" + result["sql"])
            print(f"\nRows returned: {result['row_count']}")
            print(f"Time: {result['elapsed_seconds']} seconds")
            print("\nAnalysis:\n" + result["explanation"])

            if result["columns"]:
                print("\n" + " | ".join(result["columns"]))
                print("-" * 70)
                for row in result["rows"]:
                    print(" | ".join(str(value) for value in row))

            print()

        except (AgentError, KeyboardInterrupt) as exc:
            if isinstance(exc, KeyboardInterrupt):
                print("\nExiting.")
                break
            print(f"\nAgent error: {exc}\n")
