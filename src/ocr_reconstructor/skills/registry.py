from __future__ import annotations

from pathlib import Path

from ocr_reconstructor.skills.loader import Skill, load_skill


class SkillRegistry:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._cache: dict[str, Skill] = {}

    def list_names(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name for entry in self.root.iterdir() if (entry / "SKILL.md").is_file()
        )

    def get(self, name: str) -> Skill:
        skill = self._cache.get(name)
        if skill is not None:
            return skill
        directory = self.root / name
        if not directory.is_dir():
            available = self.list_names()
            from ocr_reconstructor.core.exceptions import SkillNotFoundError

            raise SkillNotFoundError(
                f"Skill '{name}' not found in {self.root}.",
                f"Available skills: {', '.join(available) or '(none)'}. "
                "Check the skill name and the skills directory path "
                "(skills_dir in config.yml).",
            )
        skill = load_skill(directory)
        self._cache[name] = skill
        return skill
