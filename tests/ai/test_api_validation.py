import unittest
from unittest.mock import patch

import app as api


class JsonValidationTests(unittest.TestCase):
    def test_invalid_json_never_reaches_training_operations(self):
        client = api.app.test_client()
        routes = [
            ("PUT", "/training/images/" + "a" * 32),
            ("POST", "/training/jobs"),
            ("POST", "/training/models/activate"),
            ("POST", "/training/models/delete"),
        ]
        with patch.object(api, "training_manager") as manager:
            for method, route in routes:
                for body in ('[1]', '[]', 'true', '1', '"text"', 'null', '{bad json', ''):
                    with self.subTest(route=route, body=body):
                        response = client.open(
                            route, method=method, data=body,
                            content_type="application/json",
                        )
                        self.assertEqual(response.status_code, 400)
                        self.assertFalse(response.json["success"])
            self.assertEqual(manager.mock_calls, [])


if __name__ == "__main__":
    unittest.main()
