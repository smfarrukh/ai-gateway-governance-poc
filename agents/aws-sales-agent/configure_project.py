"""Wires a freshly created AgentCore project (agentcore create) to the AI gateway POC.

  python agents/aws-sales-agent/configure_project.py --project-dir <path to salesagent> \
      --account 123456789012 --region us-east-1

Reads AI_GATEWAY_URL / BEDROCK_MODEL from config/poc.env, then:
  1. copies the governed agent code over app/salesagent/
  2. sets the runtime environment variables in agentcore/agentcore.json
  3. writes the deployment target in agentcore/aws-targets.json
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools"))
from poc_config import load_config  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True, help="Folder created by agentcore create (contains agentcore/)")
    parser.add_argument("--account", required=True, help="12-digit AWS account id")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--agent-name", default="salesagent")
    args = parser.parse_args()

    cfg = load_config()
    project = Path(args.project_dir).resolve()
    app_dir = project / "app" / args.agent_name
    spec_file = project / "agentcore" / "agentcore.json"
    if not spec_file.exists() or not app_dir.exists():
        sys.exit(f"{project} does not look like an AgentCore project for agent '{args.agent_name}'")

    shutil.copytree(HERE / "app", app_dir, dirs_exist_ok=True)
    print(f"Copied governed agent code into {app_dir}")

    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    runtime = next(r for r in spec["runtimes"] if r["name"] == args.agent_name)
    runtime["envVars"] = [
        {"name": "AI_GATEWAY_URL", "value": cfg["APIGEE_HOST"]},
        {"name": "LLM_MODEL", "value": cfg["BEDROCK_MODEL"]},
    ]
    runtime["description"] = "Sales Account agent governed by the Apigee AI gateway"
    spec_file.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")
    print(f"Set AI_GATEWAY_URL and LLM_MODEL in {spec_file}")

    targets_file = project / "agentcore" / "aws-targets.json"
    targets_file.write_text(json.dumps([{
        "name": "default",
        "description": "AI gateway governance POC",
        "account": args.account,
        "region": args.region,
    }], indent=2) + "\n", encoding="utf-8")
    print(f"Wrote deployment target {args.account}/{args.region} to {targets_file}")


if __name__ == "__main__":
    main()
