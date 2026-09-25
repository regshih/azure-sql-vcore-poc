from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.experiments.common import ROOT


class Phase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    fraction: float = Field(gt=0, le=1)
    multiplier: float = Field(ge=0, le=10)


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    users: int = Field(default=10, ge=1, le=1000)
    spawn_rate: float = Field(default=5, gt=0, le=1000)
    duration: float = Field(default=300, ge=1, le=86400)
    rate: float = Field(default=10, gt=0, le=10000)
    write_ratio: float = Field(default=0.05, ge=0, lt=1)
    seed: int = 41
    product_count: int = Field(default=100, ge=1)
    request_timeout: float = Field(default=30, gt=0, le=900)
    equivalent_period_seconds: float = Field(default=86400, gt=0)
    target_daily_reads: int = Field(default=50000, gt=0)
    hot_fraction: float = Field(default=0.1, gt=0, le=1)
    hot_probability: float = Field(default=0.8, ge=0, le=1)
    scenario: Literal["normal", "idle", "storm", "slow", "cache", "failover"] = "normal"
    connection_mode: Literal["pooled", "no-reuse"] = "pooled"
    phases: tuple[Phase, ...] = (Phase(fraction=1, multiplier=1),)

    @model_validator(mode="after")
    def validate_profile(self) -> Profile:
        if abs(sum(p.fraction for p in self.phases) - 1) > 1e-8:
            raise ValueError("Phase fractions must sum to one")
        peak_rate = self.rate * max(p.multiplier for p in self.phases)
        if self.scenario in {"storm", "slow"}:
            if self.users > 20 or peak_rate > 20 or self.duration > 900:
                raise ValueError("Unsafe profiles are bounded to 20 users, 20 RPS, 900 seconds")
            if self.write_ratio:
                raise ValueError("Unsafe profiles must be read-only")
        return self

    @property
    def profile_hash(self) -> str:
        encoded = json.dumps(self.model_dump(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    def rate_at(self, elapsed: float) -> float:
        if elapsed >= self.duration:
            return 0
        boundary = 0.0
        for phase in self.phases:
            boundary += phase.fraction * self.duration
            if elapsed < boundary:
                return self.rate * phase.multiplier
        return 0

    @property
    def scheduled_requests(self) -> float:
        return self.duration * self.rate * sum(p.fraction * p.multiplier for p in self.phases)

    def volume_model(self) -> dict[str, float | str]:
        reads = self.scheduled_requests * (1 - self.write_ratio)
        return {
            "target_daily_reads": self.target_daily_reads,
            "equivalent_period_seconds": self.equivalent_period_seconds,
            "acceleration_factor": self.equivalent_period_seconds / self.duration,
            "scheduled_http_requests": self.scheduled_requests,
            "scheduled_read_requests": reads,
            "modeled_daily_read_requests": reads,
            "volume_fraction_of_target": reads / self.target_daily_reads,
            "sql_read_queries": "Not inferred from HTTP request count; use dependency telemetry.",
            "assumption": "POC assumption, not a confirmed customer requirement.",
        }


def load_profile(name: str, **overrides: object) -> Profile:
    path = Path(name)
    if not path.is_file():
        path = ROOT / "load-tests" / "profiles" / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Profile must be a YAML mapping")
    data.update({key: value for key, value in overrides.items() if value is not None})
    return Profile.model_validate(data)
