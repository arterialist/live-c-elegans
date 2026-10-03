"""Input regressions that must not reach the simulation command queue."""

import unittest

from celegans_live_demo.server import _food_command_coordinates, _parse_client_message


class DemoCommandTests(unittest.TestCase):
    def test_non_object_json_is_rejected(self) -> None:
        for raw in ("[]", "null", "1", '"hello"'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                _parse_client_message(raw)

    def test_valid_food_coordinates_are_preserved(self) -> None:
        message = _parse_client_message('{"p":3,"t":"a","x":1.25,"y":-2}')
        self.assertEqual(_food_command_coordinates(message), (1.25, -2.0))

    def test_nonfinite_food_coordinates_are_rejected(self) -> None:
        for value in ("nan", "inf", "-inf", float("nan"), float("inf")):
            for axis in ("x", "y"):
                message = {"x": 1.0, "y": 2.0, axis: value}
                with self.subTest(axis=axis, value=value), self.assertRaises(ValueError):
                    _food_command_coordinates(message)
