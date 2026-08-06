"""Verification and resolution rules (DOCUMENT 04 - section 14)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import VerificationStatus


@dataclass(slots=True)
class CheckResult:
    name: str
    status: VerificationStatus
    critical: bool = True
    expected: Any = None
    actual: Any = None
    detail: str = ""
    asset_urn: str | None = None

    def to_public(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": str(self.status),
            "critical": self.critical,
            "expected": self.expected,
            "actual": self.actual,
            "detail": self.detail,
            "asset_urn": self.asset_urn,
        }


@dataclass(slots=True)
class VerificationOutcome:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.checks if c.status is VerificationStatus.PASS)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def status(self) -> VerificationStatus:
        if not self.checks:
            return VerificationStatus.FAIL
        critical_failed = any(
            c.critical and c.status is not VerificationStatus.PASS for c in self.checks
        )
        if critical_failed:
            return VerificationStatus.FAIL
        if self.passed == self.total:
            return VerificationStatus.PASS
        return VerificationStatus.PARTIAL

    def to_public(self) -> dict[str, Any]:
        return {
            "status": str(self.status),
            "passed": self.passed,
            "total": self.total,
            "summary": f"{self.passed} / {self.total} checks PASS",
            "checks": [c.to_public() for c in self.checks],
        }


def can_resolve(outcome: VerificationOutcome) -> bool:
    """RESOLVED requires a real, passing, independent verification."""
    return outcome.total > 0 and outcome.status is VerificationStatus.PASS
