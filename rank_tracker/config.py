from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    sync_exports_dir: Path
    vault_dir: Path
    vault_subfolder: str = "Amazon/Rank Tracker"
    state_dir: Path = Path("state")
    marketplace_id: str = "A1F83G8C2ARO7P"
    se_domain: str = "amazon.co.uk"
    location_code: int = 2826
    language_code: str = "en_GB"
    spapi_endpoint: str = "https://sellingpartnerapi-eu.amazon.com"
    sqp_weeks: int = 4
    keywords_per_asin: int = 5
    max_keywords: int = 150
    serp_depth: int = 100
    exclude_terms: list = field(default_factory=lambda: ["assisi"])
    poll_interval_s: int = 60
    poll_timeout_s: int = 3600

    # Secrets come from the environment only, never the config file.
    @property
    def dataforseo_login(self) -> str:
        return _env("DATAFORSEO_LOGIN")

    @property
    def dataforseo_password(self) -> str:
        return _env("DATAFORSEO_PASSWORD")

    @property
    def lwa_client_id(self) -> str:
        return _env("SPAPI_LWA_CLIENT_ID")

    @property
    def lwa_client_secret(self) -> str:
        return _env("SPAPI_LWA_CLIENT_SECRET")

    @property
    def spapi_refresh_token(self) -> str:
        return _env("SPAPI_REFRESH_TOKEN")

    @property
    def rank_dir(self) -> Path:
        return self.vault_dir / self.vault_subfolder


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"Missing environment variable {name} (see README, .env setup)")
    return value


def load(path: str | Path) -> Config:
    raw = json.loads(Path(path).read_text())
    for key in ("sync_exports_dir", "vault_dir", "state_dir"):
        if key in raw:
            raw[key] = Path(os.path.expanduser(raw[key]))
    return Config(**raw)
