"""Canonical MemoryGateway above existing memory providers."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MemoryGateway:
    lessons: list[dict] = field(default_factory=list)
    episodes: list[dict] = field(default_factory=list)
    patterns: list[dict] = field(default_factory=list)

    def store_episode(self, episode: dict) -> None:
        self.episodes.append(episode)

    def store_lesson(self, lesson: dict) -> None:
        self.lessons.append(lesson)

    def store_pattern(self, pattern: dict) -> None:
        self.patterns.append(pattern)

    def search_similar(self, query: str, top_k: int = 5) -> list[dict]:
        scored = [p for p in self.episodes if query.lower() in str(p).lower()]
        return scored[:top_k]

    def confirm_lesson(self, lesson_id: str) -> None:
        for lesson in self.lessons:
            if lesson.get("id") == lesson_id:
                lesson["status"] = "CONFIRMED"

    def retire_lesson(self, lesson_id: str) -> None:
        for lesson in self.lessons:
            if lesson.get("id") == lesson_id:
                lesson["status"] = "RETIRED"

    def link_candidate(self, candidate_id: str, lesson_id: str) -> None:
        for lesson in self.lessons:
            if lesson.get("id") == lesson_id:
                lesson.setdefault("candidates", []).append(candidate_id)

    def get_lineage(self, lesson_id: str) -> list[dict]:
        out = []
        for lesson in self.lessons:
            if lesson.get("id") == lesson_id:
                out.append(lesson)
                for candidate_id in lesson.get("candidates", []):
                    out.append({"candidate_id": candidate_id})
        return out
