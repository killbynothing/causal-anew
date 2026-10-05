# -*- coding: utf-8 -*-
"""P6b orchestration-only turn engine.

The engine knows only stage order and injected ports. It does not know scenes,
cards, policies, actors, persistence, or runtime authority owners.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

TURN_STAGE_ORDER: tuple[str, ...] = (
    "input",
    "observe",
    "deliberate",
    "floor",
    "enact",
    "resolve",
    "commit",
    "exit",
    "project",
)

_CONTINUE = "continue"
_PROJECT = "project"
_VALID_DIRECTIVES = frozenset({_CONTINUE, _PROJECT})


@dataclass(frozen=True)
class TurnStageReceipt:
    stage: str
    directive: str = _CONTINUE
    note: str = ""
    artifact_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.stage not in TURN_STAGE_ORDER:
            raise ValueError(f"unknown turn stage: {self.stage}")
        if self.directive not in _VALID_DIRECTIVES:
            raise ValueError(f"unknown turn directive: {self.directive}")

    @classmethod
    def continue_(
        cls,
        stage: str,
        *,
        note: str = "",
        artifact_keys: tuple[str, ...] = (),
    ) -> "TurnStageReceipt":
        return cls(
            stage=stage,
            directive=_CONTINUE,
            note=str(note or ""),
            artifact_keys=tuple(str(item) for item in artifact_keys),
        )

    @classmethod
    def project(
        cls,
        stage: str,
        *,
        note: str = "",
        artifact_keys: tuple[str, ...] = (),
    ) -> "TurnStageReceipt":
        return cls(
            stage=stage,
            directive=_PROJECT,
            note=str(note or ""),
            artifact_keys=tuple(str(item) for item in artifact_keys),
        )


@dataclass(frozen=True)
class TurnFrame:
    request_id: str
    receipts: tuple[TurnStageReceipt, ...] = ()
    short_circuit_reason: str = ""

    @property
    def stages(self) -> tuple[str, ...]:
        return tuple(item.stage for item in self.receipts)

    @property
    def short_circuited(self) -> bool:
        return bool(self.short_circuit_reason)

    def append(self, receipt: TurnStageReceipt) -> "TurnFrame":
        if receipt.stage in self.stages:
            raise ValueError(f"turn stage executed twice: {receipt.stage}")
        return TurnFrame(
            request_id=self.request_id,
            receipts=(*self.receipts, receipt),
            short_circuit_reason=(
                self.short_circuit_reason
                or (receipt.note if receipt.directive == _PROJECT else "")
                or (receipt.stage if receipt.directive == _PROJECT else "")
            ),
        )


class TurnStagePort(Protocol):
    def __call__(self, frame: TurnFrame) -> TurnStageReceipt:
        ...


@dataclass(frozen=True)
class TurnPorts:
    input: TurnStagePort
    observe: TurnStagePort
    deliberate: TurnStagePort
    floor: TurnStagePort
    enact: TurnStagePort
    resolve: TurnStagePort
    commit: TurnStagePort
    exit: TurnStagePort
    project: TurnStagePort

    def for_stage(self, stage: str) -> TurnStagePort:
        if stage not in TURN_STAGE_ORDER:
            raise ValueError(f"unknown turn stage: {stage}")
        return getattr(self, stage)


class TurnEngine:
    """Execute injected turn ports in one fixed dependency order."""

    def __init__(self, ports: TurnPorts):
        self._ports = ports

    def run_turn(self, *, request_id: str) -> TurnFrame:
        request = str(request_id or "").strip()
        if not request:
            raise ValueError("turn engine requires request_id")

        frame = TurnFrame(request_id=request)
        project_only = False
        for stage in TURN_STAGE_ORDER:
            if project_only and stage != "project":
                continue
            receipt = self._ports.for_stage(stage)(frame)
            if not isinstance(receipt, TurnStageReceipt):
                raise TypeError(f"{stage} port must return TurnStageReceipt")
            if receipt.stage != stage:
                raise ValueError(
                    f"turn port stage mismatch: expected {stage}, got {receipt.stage}"
                )
            frame = frame.append(receipt)
            if receipt.directive == _PROJECT and stage != "project":
                project_only = True
        if not frame.receipts or frame.receipts[-1].stage != "project":
            raise RuntimeError("turn engine must finish at project")
        return frame
