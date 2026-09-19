"""Reads and updates config/poc.env (simple KEY=VALUE lines)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "config" / "poc.env"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise SystemExit(f"Missing {CONFIG_FILE}. Copy config/poc.env.example to config/poc.env first.")
    values = {}
    for line in CONFIG_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    values["APIGEE_HOST"] = values.get("APIGEE_HOST", "").rstrip("/")
    values["APIGEE_ORG"] = values.get("APIGEE_ORG") or values.get("GCP_PROJECT_ID", "")
    return values


def require(cfg: dict, *keys: str) -> None:
    missing = [k for k in keys if not cfg.get(k)]
    if missing:
        raise SystemExit(f"Set these in config/poc.env first: {', '.join(missing)}")


def save_values(updates: dict) -> None:
    """Replaces KEY=... lines in place (appends keys that are not there yet)."""
    lines = CONFIG_FILE.read_text(encoding="utf-8-sig").splitlines()
    pending = dict(updates)
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if "=" in line and not line.lstrip().startswith("#") and key in pending:
            lines[i] = f"{key}={pending.pop(key)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
