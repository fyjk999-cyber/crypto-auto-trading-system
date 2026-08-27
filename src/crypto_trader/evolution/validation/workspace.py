"""Isolated candidate workspace with strict path policy."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime

from crypto_trader.evolution.foundation.policy import EvolutionMutationPolicy


@dataclass
class CandidateWorkspace:
    candidate_id: str
    parent_commit: str
    parent_version: str
    workspace_path: str
    allowed_paths: tuple[str, ...]
    protected_paths: tuple[str, ...]
    created_at_utc: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    workspace_status: str = "CREATED"
    candidate_commit: str = ""
    diff_hash: str = ""
    changed_files: list = field(default_factory=list)
    loc_added: int = 0
    loc_removed: int = 0
    budget: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"candidate_id": self.candidate_id, "parent_commit": self.parent_commit,
                "parent_version": self.parent_version,
                "workspace_path": self.workspace_path,
                "allowed_paths": list(self.allowed_paths),
                "protected_paths": list(self.protected_paths),
                "created_at_utc": self.created_at_utc,
                "workspace_status": self.workspace_status,
                "candidate_commit": self.candidate_commit,
                "diff_hash": self.diff_hash,
                "changed_files": list(self.changed_files),
                "loc_added": self.loc_added, "loc_removed": self.loc_removed,
                "budget": dict(self.budget)}


class CandidateWorkspaceManager:
    def __init__(self, base_dir: str = "/tmp/evolution_candidates",
                 policy: EvolutionMutationPolicy | None = None) -> None:
        self.base_dir = base_dir
        self.policy = policy or EvolutionMutationPolicy()
        self.workspaces: dict[str, CandidateWorkspace] = {}

    def create(self, *, candidate_id: str, parent_commit: str,
               parent_version: str, allowed_paths: list[str],
               budget: dict | None = None) -> CandidateWorkspace:
        workspace_path = os.path.join(self.base_dir, f"candidate-{candidate_id}")
        workspace = CandidateWorkspace(
            candidate_id=candidate_id, parent_commit=parent_commit,
            parent_version=parent_version, workspace_path=workspace_path,
            allowed_paths=tuple(allowed_paths),
            protected_paths=self.policy.protected_path_prefixes,
            budget=budget or {"max_files_changed": 5, "max_loc_added": 200,
                              "max_loc_removed": 100, "max_new_parameters": 10,
                              "max_new_factors": 3},
        )
        self.workspaces[candidate_id] = workspace
        return workspace

    def resolve_path(self, workspace: CandidateWorkspace, path: str) -> tuple[bool, str, str]:
        if os.path.isabs(path):
            return False, "ABSOLUTE_PATH_ESCAPE", ""
        candidate_root = os.path.realpath(workspace.workspace_path)
        target = os.path.realpath(os.path.join(candidate_root, path))
        if not target.startswith(candidate_root + os.sep):
            return False, "PATH_ESCAPE", ""
        for protected in workspace.protected_paths:
            if path == protected or path.startswith(protected):
                return False, "PROTECTED_PATH", ""
        if not any(path.startswith(p) or path == p for p in workspace.allowed_paths):
            return False, "PATH_NOT_ALLOWED", ""
        return True, "OK", target

    def record_write(self, workspace: CandidateWorkspace, path: str,
                     loc_added: int = 1, loc_removed: int = 0) -> tuple[bool, str]:
        ok, reason, target = self.resolve_path(workspace, path)
        if not ok:
            workspace.workspace_status = "QUARANTINED"
            return False, reason
        if path not in workspace.changed_files:
            workspace.changed_files.append(path)
        workspace.loc_added += loc_added
        workspace.loc_removed += loc_removed
        if len(workspace.changed_files) > workspace.budget["max_files_changed"]:
            workspace.workspace_status = "QUARANTINED"
            return False, "CHANGE_BUDGET_EXCEEDED_FILES"
        if workspace.loc_added > workspace.budget["max_loc_added"]:
            workspace.workspace_status = "QUARANTINED"
            return False, "CHANGE_BUDGET_EXCEEDED_LOC_ADDED"
        if workspace.loc_removed > workspace.budget["max_loc_removed"]:
            workspace.workspace_status = "QUARANTINED"
            return False, "CHANGE_BUDGET_EXCEEDED_LOC_REMOVED"
        return True, "OK"

    def finalize(self, workspace: CandidateWorkspace, candidate_commit: str,
                 diff_hash: str) -> None:
        workspace.candidate_commit = candidate_commit
        workspace.diff_hash = diff_hash
        workspace.workspace_status = "MATERIALIZED"

    def destroy(self, candidate_id: str) -> None:
        workspace = self.workspaces.pop(candidate_id, None)
        if workspace is not None:
            workspace.workspace_status = "DESTROYED"
