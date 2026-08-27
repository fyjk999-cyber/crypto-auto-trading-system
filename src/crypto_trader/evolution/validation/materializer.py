"""Candidate materializer: applies changes within isolated workspace only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MaterializationResult:
    candidate_id: str
    status: str
    reason: str
    changed_files: list
    loc_added: int
    loc_removed: int
    diff_hash: str


class CandidateMaterializer:
    def __init__(self, workspace_manager) -> None:
        self.workspace_manager = workspace_manager

    def apply(
        self, candidate_id: str, edits: list[dict], candidate_commit: str, diff_hash: str
    ) -> MaterializationResult:
        workspace = self.workspace_manager.workspaces.get(candidate_id)
        if workspace is None:
            return MaterializationResult(
                candidate_id, "REJECTED", "WORKSPACE_NOT_FOUND", [], 0, 0, ""
            )
        for edit in edits:
            ok, reason = self.workspace_manager.record_write(
                workspace,
                edit.get("path", ""),
                loc_added=edit.get("loc_added", 1),
                loc_removed=edit.get("loc_removed", 0),
            )
            if not ok:
                workspace.workspace_status = "QUARANTINED"
                return MaterializationResult(
                    candidate_id,
                    "QUARANTINED",
                    reason,
                    workspace.changed_files,
                    workspace.loc_added,
                    workspace.loc_removed,
                    "",
                )
        self.workspace_manager.finalize(workspace, candidate_commit, diff_hash)
        return MaterializationResult(
            candidate_id,
            "MATERIALIZED",
            "OK",
            workspace.changed_files,
            workspace.loc_added,
            workspace.loc_removed,
            diff_hash,
        )
