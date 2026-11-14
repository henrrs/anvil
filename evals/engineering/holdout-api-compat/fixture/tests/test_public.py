import unittest

from status import render_status


class StatusTests(unittest.TestCase):
    def test_legacy_output_is_stable(self):
        self.assertEqual(render_status("worker", "ready"), "worker: ready")
        self.assertEqual(render_status("worker", "busy", {"jobs": 2}), "worker: busy jobs=2")

    def test_json_option_returns_structured_output(self):
        self.assertEqual(render_status("worker", "ready", {"jobs": 2}, as_json=True),
                         '{"details":{"jobs":2},"name":"worker","state":"ready"}')


if __name__ == "__main__":
    unittest.main()
