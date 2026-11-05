import unittest
from unittest.mock import patch

from app.agent import (
    AgentError, execute_sql, validate_sql, ask,
    _read_only_authorizer, _extract_sql_response,
    _deterministic_group_summary, _deterministic_scalar_summary,
)


class TestDeterministicScalarSummary(unittest.TestCase):
    def test_revenue_uses_rupees(self):
        result = _deterministic_scalar_summary(
            ["total_revenue"], [[19452100.0]]
        )
        self.assertEqual(
            result,
            "The total revenue is ₹19,452,100."
        )

    def test_amount_uses_rupees(self):
        result = _deterministic_scalar_summary(
            ["total_amount"], [[1250.50]]
        )
        self.assertEqual(result, "The total amount is ₹1,250.5.")

    def test_order_count_has_no_currency_symbol(self):
        result = _deterministic_scalar_summary(
            ["order_count"], [[500]]
        )
        self.assertEqual(result, "The order count is 500.")

    def test_unknown_numeric_column_uses_llm_fallback(self):
        self.assertIsNone(
            _deterministic_scalar_summary(["score"], [[92.5]])
        )

    def test_rejects_multiple_rows(self):
        self.assertIsNone(
            _deterministic_scalar_summary(
                ["total_revenue"], [[100], [200]]
            )
        )


class TestDeterministicSummary(unittest.TestCase):
    def test_monthly_revenue_identifies_correct_highest_and_lowest(self):
        columns = ["month", "revenue"]
        rows = [
            ["2026-01", 1390000.0],
            ["2026-03", 369400.0],
            ["2026-08", 214900.0],
            ["2026-10", 500000.0],
        ]

        summary = _deterministic_group_summary(columns, rows)

        self.assertIn("2026-01", summary)
        self.assertIn("1,390,000", summary)
        self.assertIn("2026-08", summary)
        self.assertIn("214,900", summary)
        self.assertIn("Among the returned rows", summary)

    def test_reports_tied_highest_values(self):
        summary = _deterministic_group_summary(
            ["city", "customers"],
            [["Delhi", 2], ["Mumbai", 2], ["Agra", 1]],
        )
        self.assertIn("Delhi, Mumbai", summary)

    def test_returns_none_for_single_row(self):
        self.assertIsNone(
            _deterministic_group_summary(["month", "revenue"], [["2026-01", 100]])
        )

    def test_returns_none_for_two_numeric_columns(self):
        self.assertIsNone(
            _deterministic_group_summary(
                ["actual", "forecast"], [[100, 110], [120, 115]]
            )
        )


class TestSQLSafety(unittest.TestCase):
    def test_allows_select(self):
        self.assertEqual(
            validate_sql("SELECT COUNT(*) FROM orders"),
            "SELECT COUNT(*) FROM orders",
        )

    def test_allows_with_query(self):
        sql = "WITH totals AS (SELECT COUNT(*) AS n FROM orders) SELECT n FROM totals"
        self.assertEqual(validate_sql(sql), sql)

    def test_rejects_delete(self):
        with self.assertRaises(AgentError):
            validate_sql("DELETE FROM orders")

    def test_rejects_drop(self):
        with self.assertRaises(AgentError):
            validate_sql("DROP TABLE orders")

    def test_rejects_multiple_statements(self):
        with self.assertRaises(AgentError):
            validate_sql("SELECT 1; DROP TABLE orders")

    def test_rejects_pragma(self):
        with self.assertRaises(AgentError):
            validate_sql("PRAGMA table_info(orders)")


class TestDatabaseResults(unittest.TestCase):
    def test_order_count_is_500(self):
        columns, rows = execute_sql("SELECT COUNT(*) AS n FROM orders")
        self.assertEqual(columns, ["n"])
        self.assertEqual(rows, [[500]])

    def test_order_status_counts(self):
        _, rows = execute_sql(
            "SELECT status, COUNT(*) FROM orders GROUP BY status ORDER BY status"
        )
        self.assertEqual(
            rows,
            [
                ["cancelled", 102],
                ["completed", 235],
                ["processing", 85],
                ["shipped", 78],
            ],
        )

    def test_top_completed_products(self):
        _, rows = execute_sql("""
            SELECT p.product_name, SUM(oi.quantity * oi.unit_price) AS revenue
            FROM order_items oi
            JOIN products p ON p.product_id = oi.product_id
            JOIN orders o ON o.order_id = oi.order_id
            WHERE o.status = 'completed'
            GROUP BY p.product_name
            ORDER BY revenue DESC
            LIMIT 5
        """)
        self.assertEqual(
            rows,
            [
                ["Laptop Pro", 8925000.0],
                ["Standing Desk", 3220000.0],
                ["Monitor 27 inch", 3102000.0],
                ["Office Chair", 1500000.0],
                ["Headphones", 739500.0],
            ],
        )

    def test_top_three_cities_returns_three_rows(self):
        _, rows = execute_sql("""
            SELECT city, COUNT(*) AS customer_count
            FROM customers
            GROUP BY city
            ORDER BY customer_count DESC, city ASC
            LIMIT 3
        """)
        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {row[0]: row[1] for row in rows},
            {"Delhi": 2, "Mumbai": 2, "Ahmedabad": 1},
        )


class TestAgentBehavior(unittest.TestCase):
    def test_rejects_empty_question(self):
        with self.assertRaises(AgentError):
            ask("   ")

    def test_rejects_question_over_limit(self):
        with self.assertRaises(AgentError):
            ask("x" * 2001)

    @patch("app.agent.explain_results", return_value="Test explanation.")
    @patch("app.agent.generate_sql", return_value="SELECT COUNT(*) AS n FROM orders")
    def test_ask_returns_expected_fields(self, mock_sql, mock_explain):
        result = ask("How many orders are there?")
        self.assertEqual(result["rows"], [[500]])
        self.assertEqual(result["columns"], ["n"])
        self.assertEqual(result["row_count"], 1)
        self.assertEqual(result["explanation"], "Test explanation.")
        self.assertIn("elapsed_seconds", result)
        self.assertIn("sql", result)
        mock_explain.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestEdgeCases(unittest.TestCase):
    def test_empty_query_result(self):
        columns, rows = execute_sql(
            "SELECT customer_id FROM customers WHERE customer_id = -999999"
        )
        self.assertEqual(columns, ["customer_id"])
        self.assertEqual(rows, [])

    def test_row_limit_rejects_more_than_200(self):
        with self.assertRaises(AgentError):
            execute_sql("""
                WITH numbers(n) AS (
                    SELECT 1
                    UNION ALL
                    SELECT n + 1 FROM numbers WHERE n < 201
                )
                SELECT n FROM numbers
            """)

    def test_invalid_sql_raises_agent_error(self):
        with self.assertRaises(AgentError):
            execute_sql("SELECT column_that_does_not_exist FROM customers")

    @patch("app.agent.explain_results", return_value="Results retrieved successfully, but the explanation service failed.")
    @patch("app.agent.generate_sql", return_value="SELECT COUNT(*) AS n FROM orders")
    def test_explanation_failure_message_does_not_break_query(
        self, mock_sql, mock_explain
    ):
        result = ask("How many orders are there?")
        self.assertEqual(result["rows"], [[500]])
        self.assertIn("explanation service failed", result["explanation"])

    @patch("app.agent.explain_results", return_value="No rows matched this question.")
    @patch(
        "app.agent.generate_sql",
        return_value="SELECT customer_id FROM customers WHERE customer_id = -999999",
    )
    def test_agent_handles_no_matching_rows(self, mock_sql, mock_explain):
        result = ask("Find a customer with a nonexistent ID.")
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["row_count"], 0)
        self.assertEqual(result["explanation"], "No rows matched this question.")



class TestReadOnlyAuthorizer(unittest.TestCase):
    def test_allows_read_operations(self):
        import sqlite3

        allowed = [
            sqlite3.SQLITE_SELECT,
            sqlite3.SQLITE_READ,
            sqlite3.SQLITE_FUNCTION,
            sqlite3.SQLITE_RECURSIVE,
        ]

        for action in allowed:
            with self.subTest(action=action):
                self.assertEqual(
                    _read_only_authorizer(action, None, None, "main", None),
                    sqlite3.SQLITE_OK,
                )

    def test_denies_write_and_schema_operations(self):
        import sqlite3

        denied = [
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_DETACH,
            sqlite3.SQLITE_PRAGMA,
        ]

        for action in denied:
            with self.subTest(action=action):
                self.assertEqual(
                    _read_only_authorizer(action, None, None, "main", None),
                    sqlite3.SQLITE_DENY,
                )

    def test_denies_reads_from_attached_databases(self):
        import sqlite3

        self.assertEqual(
            _read_only_authorizer(
                sqlite3.SQLITE_READ, "customers", "customer_id",
                "attached_db", None
            ),
            sqlite3.SQLITE_DENY,
        )

    def test_denies_dangerous_file_functions(self):
        import sqlite3

        for function in ("load_extension", "readfile", "writefile"):
            with self.subTest(function=function):
                self.assertEqual(
                    _read_only_authorizer(
                        sqlite3.SQLITE_FUNCTION, None, function, None, None
                    ),
                    sqlite3.SQLITE_DENY,
                )

    def test_allows_normal_aggregate_functions(self):
        import sqlite3

        for function in ("count", "sum", "avg", "min", "max"):
            with self.subTest(function=function):
                self.assertEqual(
                    _read_only_authorizer(
                        sqlite3.SQLITE_FUNCTION, None, function, None, None
                    ),
                    sqlite3.SQLITE_OK,
                )


class TestQueryDeadline(unittest.TestCase):
    @patch("app.agent.MAX_QUERY_SECONDS", 0.001)
    def test_interrupts_long_running_query(self):
        query = """
            WITH RECURSIVE numbers(n) AS (
                SELECT 1
                UNION ALL
                SELECT n + 1 FROM numbers WHERE n < 10000000
            )
            SELECT SUM(n) FROM numbers
        """

        with self.assertRaisesRegex(AgentError, "interrupted"):
            execute_sql(query)


class TestSQLResponseExtraction(unittest.TestCase):
    def test_accepts_plain_select(self):
        sql = "SELECT COUNT(*) FROM customers"
        self.assertEqual(_extract_sql_response(sql), sql)

    def test_accepts_plain_cte(self):
        sql = "WITH totals AS (SELECT COUNT(*) AS n FROM orders) SELECT n FROM totals"
        self.assertEqual(_extract_sql_response(sql), sql)

    def test_accepts_one_sql_code_fence(self):
        response = "```sql\nSELECT * FROM customers\n```"
        self.assertEqual(_extract_sql_response(response), "SELECT * FROM customers")

    def test_rejects_explanation_before_sql(self):
        with self.assertRaises(AgentError):
            _extract_sql_response("Here is your query:\nSELECT * FROM customers")

    def test_rejects_explanation_after_sql(self):
        with self.assertRaises(AgentError):
            _extract_sql_response("SELECT * FROM customers\nThis returns customers.")

    def test_rejects_multiple_code_fences(self):
        with self.assertRaises(AgentError):
            _extract_sql_response("```sql\nSELECT 1\n```\n```sql\nSELECT 2\n```")

    def test_rejects_malformed_code_fence(self):
        with self.assertRaises(AgentError):
            _extract_sql_response("```sql\nSELECT 1")

    def test_rejects_non_select_response(self):
        with self.assertRaises(AgentError):
            _extract_sql_response("DELETE FROM customers")

    def test_rejects_empty_and_non_string_responses(self):
        for response in ("", "   ", None, 123):
            with self.subTest(response=response):
                with self.assertRaises(AgentError):
                    _extract_sql_response(response)
