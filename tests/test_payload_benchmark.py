"""Benchmark frames must describe the protocol they actually encode."""

import base64
import importlib.util
import json
from pathlib import Path
import unittest

from celegans_live_demo.server import PROTOCOL_VERSION

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark_ws_payload.py"
spec = importlib.util.spec_from_file_location("payload_benchmark", SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class PayloadBenchmarkTests(unittest.TestCase):
    def test_compact_frame_preserves_geometry_neural_values_and_fired_bits(self):
        raw = benchmark._synthetic_v2_snapshot()
        before = json.dumps(raw)
        legacy, compact = map(json.loads, benchmark.payloads(raw))
        self.assertEqual(legacy["p"], 2)
        self.assertEqual(compact["p"], PROTOCOL_VERSION)
        self.assertEqual(json.dumps(raw), before)
        self.assertEqual(len(compact["sm"]), 26)
        self.assertEqual(len(compact["fm"]), 34)
        self.assertEqual(compact["Si"], [round(x * 10_000) for x in legacy["S"]])
        self.assertEqual(compact["Ri"], [round(x * 10_000) for x in legacy["R"]])
        packed = base64.b64decode(compact["Fb"])
        self.assertEqual([(packed[i >> 3] >> (i & 7)) & 1 for i in range(302)], raw["F"])

    def test_invalid_capture_is_rejected(self):
        for raw in ([], {"t": "h"}, {"t": "s"}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                benchmark.payloads(raw)
