import unittest

from app.services.metrics_service import calculate_metrics


class MetricsServiceTest(unittest.TestCase):
    def test_calculates_facts_from_parser_rounds(self):
        metrics = calculate_metrics(
            [
                {
                    "round_number": 1,
                    "winner": "T",
                    "kills": [
                        {"tick": 10, "killer": "T_A", "victim": "CT_A", "is_first_kill": True},
                        {"tick": 20, "killer": "T_B", "victim": "CT_B", "is_first_kill": False},
                    ],
                },
                {"round_number": 2, "winner": "CT", "events": [{"type": "kill", "killer": "CT_A", "victim": "T_A"}]},
            ]
        )

        self.assertEqual(metrics["rounds_total"], 2)
        self.assertEqual(metrics["rounds_won"], {"T": 1, "CT": 1})
        self.assertEqual(metrics["kills_total"], 3)
        self.assertEqual(metrics["first_kills_total"], 2)
        self.assertEqual(metrics["players"]["T_A"], {"kills": 1, "deaths": 1, "first_kills": 1})


if __name__ == "__main__":
    unittest.main()
