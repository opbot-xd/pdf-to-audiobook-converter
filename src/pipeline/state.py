from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class SectionStatus(str, Enum):
    PENDING = "pending"
    EXTRACTING = "extracting"
    EXTRACTED = "extracted"
    CLEANING = "cleaning"
    CLEANED = "cleaned"
    SYNTHESIZING = "synthesizing"
    AUDIO_READY = "audio_ready"
    FAILED = "failed"


# Statuses from which a stage can be considered already satisfied.
_DONE_EXTRACT = {SectionStatus.EXTRACTED, SectionStatus.CLEANING, SectionStatus.CLEANED,
                 SectionStatus.SYNTHESIZING, SectionStatus.AUDIO_READY}
_DONE_CLEAN = {SectionStatus.CLEANED, SectionStatus.SYNTHESIZING, SectionStatus.AUDIO_READY}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SectionState:
    id: str
    title: str = ""
    type: str = "section"
    start_page: int = 0
    end_page: int = 0
    include: bool = True
    status: str = SectionStatus.PENDING.value
    error: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    outputs: Dict[str, str] = field(default_factory=dict)
    hashes: Dict[str, str] = field(default_factory=dict)
    chunk_count: int = 0
    duration_seconds: Optional[float] = None
    updated_at: str = field(default_factory=_now)

    # -- status helpers ----------------------------------------------------

    def is_extracted(self) -> bool:
        return SectionStatus(self.status) in _DONE_EXTRACT

    def is_cleaned(self) -> bool:
        return SectionStatus(self.status) in _DONE_CLEAN

    def is_audio_ready(self) -> bool:
        return SectionStatus(self.status) == SectionStatus.AUDIO_READY

    def is_failed(self) -> bool:
        return SectionStatus(self.status) == SectionStatus.FAILED


@dataclass
class RunState:
    schema_version: str = "1.0"
    book_title: str = ""
    pdf_path: str = ""
    manifest_path: str = ""
    pdf_hash: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)
    sections: Dict[str, SectionState] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)


class StateStore:
    """Reads/writes the run state JSON that drives resume behaviour."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.state = RunState()
        self.load()

    # -- persistence -------------------------------------------------------

    def load(self) -> RunState:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Could not parse state file %s: %s", self.path, e)
                return self.state
            self.state = RunState(
                schema_version=data.get("schema_version", "1.0"),
                book_title=data.get("book_title", ""),
                pdf_path=data.get("pdf_path", ""),
                manifest_path=data.get("manifest_path", ""),
                pdf_hash=data.get("pdf_hash", ""),
                settings=data.get("settings", {}),
                sections={k: SectionState(**v) for k, v in data.get("sections", {}).items()},
                order=data.get("order", []),
                created_at=data.get("created_at", _now()),
                updated_at=data.get("updated_at", _now()),
            )
        return self.state

    def save(self) -> None:
        self.state.updated_at = _now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = asdict(self.state)
        payload["sections"] = {k: asdict(v) for k, v in self.state.sections.items()}
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    # -- mutation ----------------------------------------------------------

    def ensure_section(self, section_id: str, **kwargs: Any) -> SectionState:
        if section_id not in self.state.sections:
            self.state.sections[section_id] = SectionState(id=section_id, **kwargs)
            if section_id not in self.state.order:
                self.state.order.append(section_id)
        return self.state.sections[section_id]

    def update(self, section_id: str, **fields: Any) -> SectionState:
        sec = self.state.sections[section_id]
        for key, value in fields.items():
            if key == "hashes" and isinstance(value, dict):
                sec.hashes.update(value)
            elif key == "outputs" and isinstance(value, dict):
                sec.outputs.update(value)
            elif key == "warnings":
                sec.warnings = list(value)
            else:
                setattr(sec, key, value)
        sec.updated_at = _now()
        self.save()
        return sec

    def set_status(self, section_id: str, status: SectionStatus, error: Optional[str] = None) -> SectionState:
        return self.update(section_id, status=status.value, error=error)

    def mark_failed(self, section_id: str, error: str) -> SectionState:
        logger.error("Section %s failed: %s", section_id, error)
        sec = self.update(section_id, status=SectionStatus.FAILED.value, error=error)
        return sec

    def add_warning(self, section_id: str, message: str) -> None:
        sec = self.state.sections.get(section_id)
        if sec is None:
            return
        if message not in sec.warnings:
            sec.warnings.append(message)
            self.save()

    # -- queries -----------------------------------------------------------

    def failed_sections(self) -> List[str]:
        return [sid for sid in self.state.order if self.state.sections[sid].is_failed()]

    def incomplete_sections(self) -> List[str]:
        return [
            sid
            for sid in self.state.order
            if not self.state.sections[sid].is_audio_ready()
        ]

    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for sec in self.state.sections.values():
            counts[sec.status] = counts.get(sec.status, 0) + 1
        return counts


def build_report(store: StateStore, output_dir: Path, started_at: str, finished_at: str,
                 extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Assemble the final processing report."""
    sections = []
    for sid in store.state.order:
        sec = store.state.sections[sid]
        sections.append(
            {
                "id": sec.id,
                "title": sec.title,
                "type": sec.type,
                "pages": [sec.start_page, sec.end_page],
                "include": sec.include,
                "status": sec.status,
                "error": sec.error,
                "warnings": sec.warnings,
                "chunk_count": sec.chunk_count,
                "duration_seconds": sec.duration_seconds,
                "outputs": sec.outputs,
            }
        )

    completed = [s["id"] for s in sections if s["status"] == SectionStatus.AUDIO_READY.value]
    failed = [s["id"] for s in sections if s["status"] == SectionStatus.FAILED.value]
    skipped = [s["id"] for s in sections if not s["include"]]
    all_warnings: List[str] = []
    for s in sections:
        all_warnings.extend(f"{s['id']}: {w}" for w in s["warnings"])

    report: Dict[str, Any] = {
        "book_title": store.state.book_title,
        "pdf_path": store.state.pdf_path,
        "pdf_hash": store.state.pdf_hash,
        "manifest_path": store.state.manifest_path,
        "output_dir": str(output_dir),
        "started_at": started_at,
        "finished_at": finished_at,
        "totals": {
            "sections": len(sections),
            "completed": len(completed),
            "failed": len(failed),
            "skipped": len(skipped),
        },
        "completed_sections": completed,
        "failed_sections": failed,
        "skipped_sections": skipped,
        "extraction_warnings": all_warnings,
        "sections": sections,
    }
    if extra:
        report.update(extra)
    return report


def write_report(report: Dict[str, Any], path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
