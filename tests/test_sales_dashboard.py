import unittest

from app.sales_dashboard import load_sales_data


class TestSalesDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = load_sales_data()

    def test_joined_sales_rows_exist(self):
        self.assertGreater(len(self.df), 0)

    def test_expected_order_count(self):
        self.assertEqual(self.df["order_id"].nunique(), 500)

    def test_revenue_matches_quantity_times_price(self):
        expected = self.df["quantity"] * self.df["unit_price"]
        for actual, wanted in zip(self.df["revenue"], expected):
            self.assertAlmostEqual(float(actual), float(wanted), places=6)

    def test_required_statuses_exist(self):
        self.assertTrue({
            "completed", "cancelled", "processing", "shipped"
        }.issubset(set(self.df["status"].unique())))

    def test_completed_revenue_is_not_greater_than_all_status_revenue(self):
        all_revenue = self.df["revenue"].sum()
        completed_revenue = self.df.loc[
            self.df["status"] == "completed", "revenue"
        ].sum()
        self.assertGreaterEqual(all_revenue, completed_revenue)
        self.assertGreaterEqual(completed_revenue, 0)

    def test_revenue_is_finite(self):
        self.assertTrue(self.df["revenue"].notna().all())


if __name__ == "__main__":
    unittest.main()
