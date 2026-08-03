# -*- coding: utf-8 -*-
"""NpcFSM — extracted from npc_test_client for free_stage reuse."""
from __future__ import annotations

DETACH_T, DETACH_A, DETACH_V = 20, 80, 3


class NpcFSM:
    def __init__(self, trust: int = 55, intimacy: int = 30, alert: int = 20, state: str = "open"):
        self.trust = trust
        self.intimacy = intimacy
        self.alert = alert
        self.state = state
        self.violations = 0

    def apply(self, d_trust: int = 0, d_int: int = 0, d_alert: int = 0, violation: bool = False) -> str:
        clamp = lambda v: max(0, min(100, v))
        self.trust = clamp(self.trust + d_trust)
        self.intimacy = clamp(self.intimacy + d_int)
        self.alert = clamp(self.alert + d_alert)
        if violation:
            self.violations += 1
        self.state = self._transition()
        return self.state

    def _transition(self) -> str:
        s, t, i, a, v = self.state, self.trust, self.intimacy, self.alert, self.violations
        if s == "detached":
            return "detached"
        if t < DETACH_T and a > DETACH_A and v >= DETACH_V:
            return "detached"
        if s == "guarded":
            return "probing" if (t >= 50 and a < 50) else "guarded"
        if s == "probing":
            if a > 60:
                return "guarded"
            if a < 20 and t > 40:
                return "open"
            return "probing"
        if s == "open":
            return "probing" if a > 30 else "open"
        return s

    def as_dict(self) -> dict:
        return {
            "trust": self.trust,
            "intimacy": self.intimacy,
            "alert": self.alert,
            "state": self.state,
            "violations": self.violations,
        }
