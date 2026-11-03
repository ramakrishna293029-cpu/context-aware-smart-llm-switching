"""Structured active-constraint ledger with requirement IDs, authority, scope,
version, status, timestamps, and explicit links to superseded requirements.

This ledger tracks all active constraints, their provenance, authority hierarchy,
and supersession relationships to enable proper conflict resolution (Requirement 7).
"""

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field


@dataclass
class RequirementID:
    """Unique identifier for a requirement or constraint."""
    id: str
    authority: str  # e.g. "user", "system", "document", "code", "policy"
    scope: str      # e.g. "global", "session", "query", "model"
    version: str    # Semantic version or timestamp
    status: str     # "active", "superseded", "deferred", "resolved"
    timestamp: str  # ISO format creation time
    supersedes: Optional[str] = None  # ID of requirement this supersedes
    superseded_by: Optional[str] = None  # ID of requirement that supersedes this


@dataclass
class ActiveConstraint:
    """A currently active constraint with full provenance."""
    id: RequirementID
    text: str
    category: str  # "budget", "context_window", "deadline", "capability", "prompt_injection", "safety"
    relevance_score: float = 1.0  # How relevant this constraint is to current query
    last_validated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ConstraintLedger:
    """Manages the active constraint ledger with supersession tracking."""
    requirements: Dict[str, RequirementID] = field(default_factory=dict)
    constraints: Dict[str, ActiveConstraint] = field(default_factory=dict)
    _history: List[ActiveConstraint] = field(default_factory=list)

    def add_requirement(
        self,
        requirement_id: str,
        authority: str,
        scope: str,
        version: str,
        status: str = "active",
        text: Optional[str] = None,
        supersedes: Optional[str] = None,
    ) -> RequirementID:
        """Add a new requirement to the ledger."""
        now = datetime.now(timezone.utc).isoformat()
        req_id = RequirementID(
            id=requirement_id,
            authority=authority,
            scope=scope,
            version=version,
            status=status,
            timestamp=now,
            supersedes=supersedes,
        )
        self.requirements[requirement_id] = req_id

        # Update supersession link if supersedes is provided
        if supersedes and supersedes in self.requirements:
            self.requirements[supersedes].superseded_by = requirement_id

        # Also add as an active constraint if text provided
        if text:
            constraint_key = f"constraint_{requirement_id}"
            constraint = ActiveConstraint(
                id=req_id,
                text=text,
                category=self._category_from_id(requirement_id),
            )
            self.constraints[constraint_key] = constraint
            self._history.append(constraint)

        return req_id

    def supersede(
        self,
        superseded_id: str,
        superseding_id: str,
        override: bool = True,
    ) -> bool:
        """Mark one requirement as superseding another.

        Returns True if the supersession was applied.
        """
        superseded = self.requirements.get(superseded_id)
        superseder = self.requirements.get(superseding_id)

        if not superseded or not superseder:
            return False

        # Only supersede if superseded is still active
        if superseded.status == "active" and override:
            superseded.status = "superseded"
            superseded.superseding_by = superseding_id

            # Also update the constraint status
            for c_key, c in self.constraints.items():
                if c.id.id == superseded_id:
                    c.id.status = "superseded"
                    c.text = f"[superseded by {superseding_id}] {c.text}"
                    break

            return True

        return False

    def _category_from_id(self, req_id: str) -> str:
        """Derive constraint category from requirement ID prefix."""
        prefixes = {
            "budget": "budget",
            "context": "context_window",
            "deadline": "deadline",
            "capability": "capability",
            "prompt": "prompt_injection",
            "safety": "safety",
            "requirement": "general",
        }
        for prefix, category in prefixes.items():
            if req_id.lower().startswith(prefix):
                return category
        return "general"

    def get_active_constraints(self) -> List[ActiveConstraint]:
        """Get all currently active constraints."""
        return [
            c for c in self.constraints.values()
            if c.id.status == "active"
        ]

    def get_superseded_constraints(self) -> List[ActiveConstraint]:
        """Get all superseded constraints."""
        return [
            c for c in self.constraints.values()
            if c.id.status == "superseded"
        ]

    def resolve_conflict(
        self,
        conflicting_ids: List[str],
        strategy: str = "authority_chronology",
    ) -> Optional[ActiveConstraint]:
        """Resolve conflicts between constraints based on authority, scope, supersession, and chronology.

        Strategies:
        - "authority_chronology": Higher authority + newer timestamp wins
        - "supersession_explicit": Explicit supersession takes precedence
        - "scope_narrowest": Most specific scope wins
        """
        if not conflicting_ids:
            return None

        # Check for explicit supersession first
        resolved = None
        for cid in conflicting_ids:
            req = self.requirements.get(cid)
            if not req:
                continue

            # If this requirement is superseded by another in the conflict set, skip
            if req.superseded_by and req.superseded_by in conflicting_ids:
                continue

            # Check if any other conflicting requirement supersedes this one
            superseded_by_conflict = any(
                self.requirements.get(cid) and self.requirements.get(cid).superseded_by == req.id
                for cid in conflicting_ids
            )
            if superseded_by_conflict:
                continue

            # Authority priority: user > system > document > code > policy
            authority_priority = {
                "user": 5,
                "system": 4,
                "document": 3,
                "code": 2,
                "policy": 1,
            }
            req_authority_priority = authority_priority.get(req.authority, 0)

            if resolved is None:
                resolved = {
                    "constraint": self.constraints.get(f"constraint_{cid}"),
                    "requirement": req,
                    "authority_priority": req_authority_priority,
                    "timestamp": req.timestamp,
                }
            else:
                # Compare with current resolver
                existing = resolved["requirement"]
                existing_priority = authority_priority.get(existing.authority, 0)

                # Higher authority wins
                if req_authority_priority > existing_priority:
                    resolved = {
                        "constraint": self.constraints.get(f"constraint_{cid}"),
                        "requirement": req,
                        "authority_priority": req_authority_priority,
                        "timestamp": req.timestamp,
                    }
                elif req_authority_priority == existing_priority:
                    # Chronology: newer wins
                    if req.timestamp > existing.timestamp:
                        resolved = {
                            "constraint": self.constraints.get(f"constraint_{cid}"),
                            "requirement": req,
                            "authority_priority": req_authority_priority,
                            "timestamp": req.timestamp,
                        }
                    elif req.timestamp == existing.timestamp:
                        # Scope: narrower wins
                        # (simplified - would need scope comparison)
                        pass

        return resolved["constraint"] if resolved else None

    def to_dict(self) -> dict:
        """Serialize ledger to dictionary for persistence."""
        return {
            "requirements": {
                rid: {
                    "id": req.id,
                    "authority": req.authority,
                    "scope": req.scope,
                    "version": req.version,
                    "status": req.status,
                    "timestamp": req.timestamp,
                    "supersedes": req.supersedes,
                    "superseded_by": req.superseded_by,
                }
                for rid, req in self.requirements.items()
            },
            "constraints": {
                c_key: {
                    "id": {
                        "id": c.id.id,
                        "authority": c.id.authority,
                        "scope": c.id.scope,
                        "version": c.id.version,
                        "status": c.id.status,
                        "timestamp": c.id.timestamp,
                        "supersedes": c.id.supersedes,
                        "superseded_by": c.id.superseded_by,
                    },
                    "text": c.text,
                    "category": c.category,
                    "relevance_score": c.relevance_score,
                    "last_validated": c.last_validated,
                }
                for c_key, c in self.constraints.items()
            },
            "history_count": len(self._history),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ConstraintLedger":
        """Deserialize ledger from dictionary."""
        ledger = cls()
        for rid, req_data in data.get("requirements", {}).items():
            req = RequirementID(
                id=req_data["id"],
                authority=req_data["authority"],
                scope=req_data["scope"],
                version=req_data["version"],
                status=req_data["status"],
                timestamp=req_data["timestamp"],
                supersedes=req_data.get("supersedes"),
                superseded_by=req_data.get("superseded_by"),
            )
            ledger.requirements[rid] = req

        for c_key, c_data in data.get("constraints", {}).items():
            req_id_data = c_data["id"]
            req_id = RequirementID(
                id=req_id_data["id"],
                authority=req_id_data["authority"],
                scope=req_id_data["scope"],
                version=req_id_data["version"],
                status=req_id_data["status"],
                timestamp=req_id_data["timestamp"],
                supersedes=req_id_data.get("supersedes"),
                superseded_by=req_id_data.get("superseded_by"),
            )
            constraint = ActiveConstraint(
                id=req_id,
                text=c_data["text"],
                category=c_data["category"],
                relevance_score=c_data.get("relevance_score", 1.0),
                last_validated=c_data.get("last_validated", datetime.now(timezone.utc).isoformat()),
            )
            ledger.constraints[c_key] = constraint

        return ledger