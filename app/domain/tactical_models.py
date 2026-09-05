from typing import Any

from pydantic import BaseModel, Field


class CanonicalEvent(BaseModel):
    """One traceable fact normalized from a demo event."""

    event_id: str
    tick: int
    event_type: str
    subtype: str | None = None
    actor_steamid: str | None = None
    actor_name: str | None = None
    actor_team: str | None = None
    actor_side: str | None = None
    actor_area: str | None = None
    target_steamid: str | None = None
    target_name: str | None = None
    target_team: str | None = None
    target_side: str | None = None
    target_area: str | None = None
    assister_steamid: str | None = None
    site: str | None = None
    position: list[float | None] | None = None
    origin_position: list[float | None] | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class TacticalLabel(BaseModel):
    """A deterministic or weakly supervised label with explicit provenance."""

    label_id: str
    label_type: str
    team: str | None = None
    site: str | None = None
    start_tick: int
    end_tick: int
    participant_ids: list[str] = Field(default_factory=list)
    evidence_event_ids: list[str] = Field(default_factory=list)
    label_source: str
    rule_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    review_status: str
    details: dict[str, Any] = Field(default_factory=dict)


class RoundAnnotation(BaseModel):
    """Versioned silver annotation for one match round."""

    schema_version: str = "0.1"
    match_id: str
    map_name: str
    round_number: int
    source_demo: str
    source_match_url: str | None = None
    tick_rate: int = 64
    start_tick: int = 0
    freeze_end_tick: int | None = None
    end_tick: int
    winner: str | None = None
    reason: str | None = None
    events: list[CanonicalEvent] = Field(default_factory=list)
    labels: list[TacticalLabel] = Field(default_factory=list)
