import os
from dataclasses import dataclass

import yaml


@dataclass
class Config:
    waha_base_url: str
    waha_api_key: str
    waha_session: str
    mcp_url: str
    mcp_api_key: str | None
    llm_provider: str
    llm_model: str
    llm_api_key: str
    default_inactivity_minutes: int
    max_thread_lifetime_minutes: int
    db_path: str
    tickets_dir: str
    kappa_base_url: str | None
    kappa_api_key: str | None


def load_config(path: str) -> Config:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return Config(
        waha_base_url=raw["waha"]["base_url"],
        waha_api_key=raw["waha"]["api_key"],
        waha_session=raw["waha"].get("session", "default"),
        mcp_url=raw["mcp"]["url"],
        mcp_api_key=raw["mcp"].get("api_key"),
        llm_provider=raw["llm"]["provider"],
        llm_model=raw["llm"]["model"],
        llm_api_key=raw["llm"]["api_key"],
        default_inactivity_minutes=raw["behavior"]["default_inactivity_minutes"],
        max_thread_lifetime_minutes=raw["behavior"]["max_thread_lifetime_minutes"],
        db_path=raw["storage"]["db_path"],
        tickets_dir=raw["storage"]["tickets_dir"],
        kappa_base_url=raw.get("kappa", {}).get("base_url"),
        kappa_api_key=raw.get("kappa", {}).get("api_key"),
    )
