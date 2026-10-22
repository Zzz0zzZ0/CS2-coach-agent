"""Conservative team-label normalization for metadata and exclusion, never model inputs."""

import re


def canonical_team(name):
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).casefold()).strip("-")
    return {"navi": "natus-vincere", "pvision": "parivision", "team-falcons": "falcons", "team-spirit": "spirit",
            "team-vitality": "vitality"}.get(slug, slug)
