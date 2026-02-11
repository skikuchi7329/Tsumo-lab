"""機種名エイリアス (名寄せ) ユーティリティ.

config/machine_alias.yaml に定義された別名マッピングを読み込み、
DB 上の表記揺れを正規名称に統一する。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_ALIAS_PATH = Path(__file__).resolve().parent.parent / "config" / "machine_alias.yaml"


class MachineAliasResolver:
    """機種名の表記揺れを統一名称に解決する.

    使い方::

        resolver = MachineAliasResolver()
        canonical = resolver.resolve("スマスロ北斗")
        # => "L北斗の拳"
    """

    def __init__(self, alias_path: Path | str | None = None) -> None:
        path = Path(alias_path) if alias_path else _DEFAULT_ALIAS_PATH
        self._lookup: dict[str, str] = {}
        self._load(path)

    def _load(self, path: Path) -> None:
        if not path.exists():
            logger.warning("Alias file not found: %s", path)
            return

        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}

        aliases_section = data.get("aliases", {})
        for canonical_name, alt_names in aliases_section.items():
            # 正規名称自体も登録
            self._lookup[canonical_name] = canonical_name
            if alt_names:
                for alt in alt_names:
                    self._lookup[alt] = canonical_name

        logger.debug(
            "Loaded %d alias entries (%d canonical names)",
            len(self._lookup),
            len(aliases_section),
        )

    def resolve(self, machine_name: str) -> str:
        """機種名を正規名称に解決する.

        エイリアスに登録されていない場合はそのまま返す。
        """
        return self._lookup.get(machine_name, machine_name)

    def resolve_list(self, names: list[str]) -> list[str]:
        """機種名リストを一括で正規名称に解決する."""
        return [self.resolve(n) for n in names]

    @property
    def canonical_names(self) -> list[str]:
        """登録されている正規名称のリストを返す."""
        return sorted(set(self._lookup.values()))
