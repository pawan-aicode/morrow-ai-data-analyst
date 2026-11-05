import io
import sqlite3

import pandas as pd

from app.dashboard_builder import read_upload, read_sqlite_readonly


class FakeUpload(io.BytesIO):
    def __init__(self, content, name):
        super().__init__(content)
        self.name = name
        self.size = len(content)


def make_dataframe():
    return pd.DataFrame({
        "order_id": range(1, 6002),
        "sales": [100] * 6001,
        "order_date": ["2025-01-01"] * 6001,
    })


def test_csv_loader_reads_all_rows():
    df = make_dataframe()
    upload = FakeUpload(df.to_csv(index=False).encode(), "orders.csv")

    result = read_upload(upload)

    assert len(result) == 6001
    assert result.attrs["source_rows"] == 6001
    assert result.attrs["is_sampled"] is False


def test_excel_loader_reads_all_rows():
    df = make_dataframe()
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    upload = FakeUpload(buffer.getvalue(), "orders.xlsx")

    result = read_upload(upload)

    assert len(result) == 6001
    assert result.attrs["source_rows"] == 6001
    assert result.attrs["is_sampled"] is False


def test_sqlite_loader_reads_all_rows(tmp_path):
    db_path = tmp_path / "orders.db"
    df = make_dataframe()

    with sqlite3.connect(db_path) as conn:
        df.to_sql("orders", conn, index=False)

    result = read_sqlite_readonly(db_path, "orders")

    assert len(result) == 6001
    assert result.attrs["source_rows"] == 6001
    assert result.attrs["is_sampled"] is False
