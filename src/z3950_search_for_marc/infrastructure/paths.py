"""Application-owned data locations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_path, user_log_path


@dataclass(frozen=True, slots=True)
class AppDataPaths:
    root: Path
    logs: Path

    @classmethod
    def default(cls) -> AppDataPaths:
        return cls(
            root=user_data_path("Z3950MarcSearch", appauthor=False, roaming=False),
            logs=user_log_path("Z3950MarcSearch", appauthor=False),
        )

    @property
    def settings(self) -> Path:
        return self.root / "settings.json"

    @property
    def cached_catalog(self) -> Path:
        return self.root / "catalog" / "servers.v2.json"

    @property
    def custom_servers(self) -> Path:
        return self.root / "catalog" / "custom-servers.v2.json"

    @property
    def disabled_servers(self) -> Path:
        return self.root / "catalog" / "disabled-server-ids.json"

    @property
    def health_state(self) -> Path:
        return self.root / "catalog" / "health-state.json"
