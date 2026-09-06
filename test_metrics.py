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

    def test_filters_non_combat_deaths_and_exposes_tactical_metrics(self):
        metrics = calculate_metrics([
            {
                "round_number": 1,
                "winner": "CT",
                "kills": [
                    {
                        "tick": 1, "killer": "sh1ro", "victim": "sh1ro",
                        "killer_team": "Spirit", "victim_team": "Spirit",
                        "killer_side": "CT", "victim_side": "CT", "weapon": "world",
                        "is_first_kill": True,
                    },
                    {
                        "tick": 10, "killer": "NiKo", "victim": "zont1x",
                        "killer_team": "Falcons", "victim_team": "Spirit",
                        "killer_side": "TERRORIST", "victim_side": "CT", "weapon": "ak47",
                    },
                ],
                "grenades": [
                    {"type": "Smoke", "thrower_team": "Falcons", "thrower_side": "TERRORIST"},
                    {"type": "Flash", "thrower_team": "Spirit", "thrower_side": "CT"},
                ],
                "plants": [{"planter_team": "Falcons", "planter_side": "TERRORIST", "site": "BombsiteA"}],
                "flash_blinds": [{
                    "victim": "zont1x", "victim_team": "Spirit",
                    "attacker": "NiKo", "attacker_team": "Falcons",
                    "blind_duration": 2.5,
                }],
                "reason": "bomb_defused",
            }
        ])

        self.assertEqual(metrics["kills_total"], 1)
        self.assertEqual(metrics["first_kills_total"], 1)
        self.assertEqual(metrics["players"]["NiKo"]["first_kills"], 1)
        self.assertNotIn("sh1ro", metrics["players"])
        self.assertEqual(metrics["rounds_won_by_team"], {"Spirit": 1})
        self.assertEqual(metrics["rounds_won_by_team_and_side"], {"Spirit": {"CT": 1}})
        self.assertEqual(metrics["grenades_total"], 2)
        self.assertEqual(metrics["grenades_by_type"], {"Flash": 1, "Smoke": 1})
        self.assertEqual(metrics["plants_total"], 1)
        self.assertEqual(metrics["post_plant_by_team"]["Falcons"], {
            "attempts": 1, "round_wins": 0, "conversion_pct": 0.0,
        })
        self.assertEqual(metrics["defuses_by_team"], {"Spirit": 1})
        self.assertEqual(
            metrics["round_summaries"][0]["plant_outcome"],
            "Falcons planted; Spirit defused",
        )
        self.assertEqual(metrics["flash_blinds_total"], 1)
        self.assertEqual(metrics["flash_blinds_by_team"], {"Falcons": 1})
        self.assertEqual(metrics["enemy_flash_blinds_by_team"], {"Falcons": 1})
        self.assertEqual(metrics["team_flash_blinds_by_team"], {})
        self.assertEqual(metrics["opening_duels_by_team"]["Falcons"], {
            "attempts": 1, "round_wins": 0, "conversion_pct": 0.0,
        })


if __name__ == "__main__":
    unittest.main()
