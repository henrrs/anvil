"""Canonical storage types accepted by local Parquet verification."""

from __future__ import annotations

import unittest

from scripts.analytics.schema import canonical_type


class CanonicalTypeTests(unittest.TestCase):
    def test_duckdb_type_aliases_and_nested_shapes(self) -> None:
        cases = {
            "VARCHAR": "string", "BOOLEAN": "boolean", "TINYINT": "int8",
            "INTEGER": "int32", "BIGINT": "int64", "FLOAT": "float",
            "DOUBLE": "double", "DECIMAL(18, 4)": "decimal(18,4)",
            "DATE": "date", "TIMESTAMP": "timestamp", "TIMESTAMPTZ": "timestamp_tz",
            "BLOB": "binary", "INTEGER[]": "array<int32>",
            "MAP(VARCHAR, INTEGER)": "map<string,int32>",
            "STRUCT(a INTEGER, b VARCHAR)": "struct<a:int32,b:string>",
        }
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(canonical_type(source), expected)

    def test_arrow_native_types(self) -> None:
        try:
            import pyarrow as pa
        except ImportError:
            self.skipTest("PyArrow is required for native type certification")
        cases = {
            pa.string(): "string", pa.bool_(): "boolean", pa.int32(): "int32",
            pa.float64(): "double", pa.decimal128(18, 4): "decimal(18,4)",
            pa.date32(): "date", pa.timestamp("us"): "timestamp",
            pa.timestamp("us", tz="UTC"): "timestamp_tz", pa.binary(): "binary",
            pa.list_(pa.int32()): "array<int32>",
            pa.map_(pa.string(), pa.int64()): "map<string,int64>",
            pa.struct([pa.field("a", pa.int32())]): "struct<a:int32>",
        }
        for source, expected in cases.items():
            with self.subTest(source=str(source)):
                self.assertEqual(canonical_type(source), expected)
