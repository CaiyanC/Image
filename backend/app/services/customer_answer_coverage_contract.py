"""Evidence-backed answer coverage for semantic customer requests.

This module records which LLM-issued request units were actually supported by
selected same-SKU evidence.  It deliberately does not infer coverage from
keywords or from whether the final prose repeats the customer's wording.
"""

from dataclasses import dataclass
from typing import Iterable


ANSWERED = "answered"
UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class AnswerRequestUnit:
    request_id: str
    request_text: str
    status: str
    evidence_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "request_text": self.request_text,
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass(frozen=True)
class AnswerCoverageContract:
    request_units: tuple[AnswerRequestUnit, ...]

    @property
    def unsupported_request_texts(self) -> tuple[str, ...]:
        return tuple(
            unit.request_text
            for unit in self.request_units
            if unit.status == UNSUPPORTED
        )

    def to_dict(self) -> dict:
        return {
            "request_units": [unit.to_dict() for unit in self.request_units],
            "complete": not self.unsupported_request_texts,
        }

    @classmethod
    def from_dict(cls, value: dict | None) -> "AnswerCoverageContract | None":
        if not isinstance(value, dict):
            return None
        units: list[AnswerRequestUnit] = []
        for raw_unit in value.get("request_units") or []:
            if not isinstance(raw_unit, dict):
                return None
            request_text = str(raw_unit.get("request_text") or "").strip()
            status = str(raw_unit.get("status") or "").strip()
            if not request_text or status not in {ANSWERED, UNSUPPORTED}:
                return None
            units.append(AnswerRequestUnit(
                request_id=str(raw_unit.get("request_id") or "").strip(),
                request_text=request_text,
                status=status,
                evidence_ids=tuple(
                    str(item).strip()
                    for item in (raw_unit.get("evidence_ids") or [])
                    if str(item or "").strip()
                ),
            ))
        return cls(tuple(units)) if units else None


def build_answer_coverage_contract(
    request_texts: Iterable[str],
    *,
    answered_requests: Iterable[tuple[str, str]],
    unsupported_requests: Iterable[str],
) -> AnswerCoverageContract:
    ordered_requests = list(dict.fromkeys(
        str(item or "").strip()
        for item in request_texts
        if str(item or "").strip()
    ))
    evidence_by_request: dict[str, list[str]] = {}
    for request_text, evidence_id in answered_requests:
        normalized_request = str(request_text or "").strip()
        normalized_evidence_id = str(evidence_id or "").strip()
        if not normalized_request:
            continue
        evidence_by_request.setdefault(normalized_request, [])
        if (
            normalized_evidence_id
            and normalized_evidence_id not in evidence_by_request[normalized_request]
        ):
            evidence_by_request[normalized_request].append(normalized_evidence_id)
    unsupported = {
        str(item or "").strip()
        for item in unsupported_requests
        if str(item or "").strip()
    }
    overlap = set(evidence_by_request).intersection(unsupported)
    if overlap:
        raise ValueError(
            "request coverage cannot be both answered and unsupported: "
            + ", ".join(sorted(overlap))
        )
    units = []
    for index, request_text in enumerate(ordered_requests, start=1):
        if request_text in evidence_by_request:
            units.append(AnswerRequestUnit(
                request_id=f"request-{index}",
                request_text=request_text,
                status=ANSWERED,
                evidence_ids=tuple(evidence_by_request[request_text]),
            ))
        else:
            units.append(AnswerRequestUnit(
                request_id=f"request-{index}",
                request_text=request_text,
                status=UNSUPPORTED,
            ))
    return AnswerCoverageContract(tuple(units))


def append_unsupported_boundaries(
    answer: str,
    contract: AnswerCoverageContract,
) -> str:
    answer_text = str(answer or "").strip()
    missing_lines = [
        f"关于“{request_text}”：当前同 SKU 资料未直接确认，无法确认。"
        for request_text in contract.unsupported_request_texts
    ]
    additions = [line for line in missing_lines if line not in answer_text]
    return "\n".join(item for item in (answer_text, *additions) if item)
