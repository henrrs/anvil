from __future__ import annotations

import base64
import tempfile
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

try:
    import pyarrow as pa
    import pyarrow.ipc as ipc
    import pyarrow.parquet as pq
except ImportError:
    pa = ipc = pq = None

try:
    import duckdb  # noqa: F401
except ImportError:
    duckdb = None

from scripts.analytics.planner import QueryPlan
from scripts.analytics.query import DuckDBLocalEngine
from scripts.analytics.transfer import PyArrowChunkCodec


@unittest.skipUnless(pa is not None and duckdb is not None,
                     "Analytics type certification requires the pinned PyArrow and DuckDB dependencies")
class AnalyticsArrowParquetTypeTests(unittest.TestCase):
    def test_arrow_ipc_parquet_and_duckdb_preserve_the_certified_type_matrix(self) -> None:
        schema = pa.schema([
            pa.field("string_value", pa.string()),
            pa.field("boolean_value", pa.bool_()),
            pa.field("int8_value", pa.int8()),
            pa.field("int16_value", pa.int16()),
            pa.field("int32_value", pa.int32()),
            pa.field("int64_value", pa.int64()),
            pa.field("float32_value", pa.float32()),
            pa.field("float64_value", pa.float64()),
            pa.field("decimal_value", pa.decimal128(18, 4)),
            pa.field("date_value", pa.date32()),
            pa.field("timestamp_value", pa.timestamp("us")),
            pa.field("timestamp_tz_value", pa.timestamp("us", tz="UTC")),
            pa.field("binary_value", pa.binary()),
            pa.field("null_value", pa.null()),
            pa.field("list_value", pa.list_(pa.int32())),
            pa.field("map_value", pa.map_(pa.string(), pa.int32())),
            pa.field("struct_value", pa.struct([
                pa.field("code", pa.string()), pa.field("quantity", pa.int64()),
            ])),
            pa.field("nested_value", pa.struct([
                pa.field("samples", pa.list_(pa.struct([
                    pa.field("value", pa.float64()),
                ]))),
                pa.field("tags", pa.map_(pa.string(), pa.string())),
            ])),
        ])
        table = pa.Table.from_arrays([
            pa.array(["alpha", None], type=pa.string()),
            pa.array([True, None], type=pa.bool_()),
            pa.array([-8, None], type=pa.int8()),
            pa.array([-1600, None], type=pa.int16()),
            pa.array([-32000, None], type=pa.int32()),
            pa.array([2**40, None], type=pa.int64()),
            pa.array([1.25, None], type=pa.float32()),
            pa.array([2.5, None], type=pa.float64()),
            pa.array([Decimal("12345678901234.5678"), None], type=pa.decimal128(18, 4)),
            pa.array([date(2026, 11, 2), None], type=pa.date32()),
            pa.array([datetime(2026, 11, 2, 12, 30), None], type=pa.timestamp("us")),
            pa.array([datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc), None],
                     type=pa.timestamp("us", tz="UTC")),
            pa.array([b"\x00\xfe", None], type=pa.binary()),
            pa.array([None, None], type=pa.null()),
            pa.array([[1, 2], None], type=pa.list_(pa.int32())),
            pa.array([[("region", 7)], None], type=pa.map_(pa.string(), pa.int32())),
            pa.array([{"code": "A", "quantity": 7}, None], type=schema.field("struct_value").type),
            pa.array([{"samples": [{"value": 1.5}, {"value": None}],
                       "tags": [("region", "west")]}, None],
                     type=schema.field("nested_value").type),
        ], schema=schema)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            arrow_path = root / "chunk.arrow"
            parquet_path = root / "part-00000.parquet"
            sink = pa.OSFile(str(arrow_path), "wb")
            with ipc.new_stream(sink, table.schema) as writer:
                writer.write_table(table)
            sink.close()

            stats = PyArrowChunkCodec().write_parquet(arrow_path, parquet_path)
            self.assertEqual(stats.row_count, 2)
            self.assertEqual(stats.columns, tuple(schema.names))
            restored_schema = pq.read_schema(parquet_path)
            self.assertTrue(schema.equals(restored_schema, check_metadata=False),
                            f"Arrow schema changed across Parquet: {restored_schema}")
            restored = pq.read_table(parquet_path)
            self.assertEqual(restored.column("decimal_value")[0].as_py(), Decimal("12345678901234.5678"))
            self.assertEqual(restored.column("timestamp_tz_value")[0].as_py(),
                             datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc))
            self.assertEqual(restored.column("map_value")[0].as_py(), [("region", 7)])
            self.assertEqual(restored.column("nested_value")[0].as_py()["samples"][0]["value"], 1.5)

            result = DuckDBLocalEngine().query(
                QueryPlan("", "main.silver.type_matrix", ("*",)),
                {"files": [parquet_path]}, max_rows=10, max_bytes=1024 * 1024)
            self.assertEqual(result["columns"], schema.names)
            self.assertEqual(result["row_count"], 2)
            self.assertFalse(result["truncated"])
            self.assertEqual(result["rows"][0][0], "alpha")
            self.assertEqual(result["rows"][0][1], True)
            self.assertEqual(result["rows"][0][8], "12345678901234.5678")
            self.assertEqual(result["rows"][0][9], "2026-11-02")
            self.assertEqual(result["rows"][0][10], "2026-11-02T12:30:00")
            self.assertEqual(datetime.fromisoformat(result["rows"][0][11]).astimezone(timezone.utc),
                             datetime(2026, 11, 2, 12, 30, tzinfo=timezone.utc))
            self.assertEqual(result["rows"][0][12], base64.b64encode(b"\x00\xfe").decode("ascii"))
            self.assertIsNone(result["rows"][0][13])
            self.assertEqual(result["rows"][0][14], [1, 2])
            self.assertEqual(result["rows"][0][15], [["region", 7]])
            self.assertEqual(result["rows"][0][16], {"code": "A", "quantity": 7})
            self.assertEqual(result["rows"][0][17]["samples"], [{"value": 1.5}, {"value": None}])
            self.assertEqual(result["rows"][0][17]["tags"], [["region", "west"]])
            self.assertIsNone(result["rows"][1][0])


if __name__ == "__main__":
    unittest.main()
