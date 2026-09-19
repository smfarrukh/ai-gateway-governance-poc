"""AI Gateway Governance POC - admin helper for Apigee and Model Armor.

Uses your gcloud login (gcloud auth print-access-token) and config/poc.env.

  python tools/poc.py check                     show config and test the Google login
  python tools/poc.py model-armor-template      create/update the Model Armor template
  python tools/poc.py model-armor-test "text"   screen a piece of text with Model Armor
  python tools/poc.py kvm                       store Azure/AWS model keys in Apigee's encrypted KVM
  python tools/poc.py deploy-proxies            build, import and deploy both gateway proxies
  python tools/poc.py setup-agents              create agent products + apps, save their keys to poc.env
  python tools/poc.py show-agents               print each agent's governance profile
  python tools/poc.py set-policy <product> <attribute> <value>   change a policy live
  python tools/poc.py revoke <app> | approve <app>              agent kill switch
  python tools/poc.py observability             BigQuery dataset + log sink for the audit log
  python tools/poc.py create-views              control-tower views in BigQuery
  python tools/poc.py status                    show deployed proxy revisions
"""

import argparse
import io
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import requests

from poc_config import ROOT, load_config, require, save_values

APIGEE_API = "https://apigee.googleapis.com/v1"
PROXIES_DIR = ROOT / "apigee" / "proxies"
AGENTS_FILE = ROOT / "apigee" / "governance" / "agents.json"
KVM_NAME = "ai-gateway-secrets"
KEY_SETTINGS = {"itsm-agent-gcp": "ITSM_AGENT_GCP_KEY", "sales-agent-aws": "SALES_AGENT_AWS_KEY",
                "cx-agent-azure": "CX_AGENT_AZURE_KEY"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def gcloud_token() -> str:
    gcloud = shutil.which("gcloud")
    if not gcloud:
        sys.exit("gcloud CLI not found on PATH")
    out = subprocess.run([gcloud, "auth", "print-access-token"], capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit("Could not get a Google access token. Run: gcloud auth login\n" + out.stderr)
    return out.stdout.strip()


class Api:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers["Authorization"] = f"Bearer {gcloud_token()}"

    def call(self, method, url, ok=(200,), **kw):
        resp = self.s.request(method, url, timeout=120, **kw)
        if resp.status_code not in ok:
            sys.exit(f"{method} {url} failed: {resp.status_code}\n{resp.text}")
        return resp


def org_url(cfg) -> str:
    return f"{APIGEE_API}/organizations/{cfg['APIGEE_ORG']}"


def agents_catalogue() -> dict:
    return json.loads(AGENTS_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_check(cfg, _args):
    secret = re.compile(r"(KEY|SECRET)$")
    for k, v in cfg.items():
        shown = ("*" * 8 + v[-4:]) if (secret.search(k) and v) else v
        print(f"  {k:24} {shown or '-- not set --'}")
    token = gcloud_token()
    info = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": token}, timeout=30).json()
    print(f"\nGoogle login OK as: {info.get('email', 'unknown')}")


def armor_base(cfg) -> str:
    loc = cfg["MODEL_ARMOR_LOCATION"]
    return f"https://modelarmor.{loc}.rep.googleapis.com/v1/projects/{cfg['GCP_PROJECT_ID']}/locations/{loc}/templates"


def cmd_model_armor_template(cfg, _args):
    require(cfg, "GCP_PROJECT_ID", "MODEL_ARMOR_LOCATION", "MODEL_ARMOR_TEMPLATE")
    api = Api()
    confidence = "MEDIUM_AND_ABOVE"
    body = {"filterConfig": {
        "piAndJailbreakFilterSettings": {"filterEnforcement": "ENABLED", "confidenceLevel": "LOW_AND_ABOVE"},
        "maliciousUriFilterSettings": {"filterEnforcement": "ENABLED"},
        "sdpSettings": {"basicConfig": {"filterEnforcement": "ENABLED"}},
        "raiSettings": {"raiFilters": [{"filterType": t, "confidenceLevel": confidence} for t in
                                       ("HATE_SPEECH", "HARASSMENT", "DANGEROUS", "SEXUALLY_EXPLICIT")]},
    }}
    name = cfg["MODEL_ARMOR_TEMPLATE"]
    resp = api.call("POST", armor_base(cfg), ok=(200, 409), params={"templateId": name}, json=body)
    if resp.status_code == 409:
        api.call("PATCH", f"{armor_base(cfg)}/{name}", params={"updateMask": "filterConfig"}, json=body)
        print(f"Updated Model Armor template {name}")
    else:
        print(f"Created Model Armor template {name}")


def cmd_model_armor_test(cfg, args):
    api = Api()
    url = f"{armor_base(cfg)}/{cfg['MODEL_ARMOR_TEMPLATE']}:sanitizeUserPrompt"
    result = api.call("POST", url, json={"userPromptData": {"text": args.text}}).json()["sanitizationResult"]
    print("Verdict:", result.get("filterMatchState"))
    for name, detail in (result.get("filterResults") or {}).items():
        matched = '"MATCH_FOUND"' in json.dumps(detail)
        print(f"  {name:20} {'MATCH' if matched else 'no match'}")


def cmd_kvm(cfg, _args):
    require(cfg, "APIGEE_ENV")
    api = Api()
    base = f"{org_url(cfg)}/environments/{cfg['APIGEE_ENV']}/keyvaluemaps"
    api.call("POST", base, ok=(200, 201, 409), json={"name": KVM_NAME, "encrypted": True})
    for entry, setting in (("azure_openai_key", "AZURE_OPENAI_KEY"), ("bedrock_api_key", "BEDROCK_API_KEY")):
        if not cfg.get(setting):
            print(f"Skipped {entry}: {setting} is empty in config/poc.env (run this command again once it is set)")
            continue
        body = {"name": entry, "value": cfg[setting]}
        resp = api.call("POST", f"{base}/{KVM_NAME}/entries", ok=(200, 201, 409), json=body)
        if resp.status_code == 409:
            api.call("PUT", f"{base}/{KVM_NAME}/entries/{entry}", json=body)
        print(f"Stored {entry} in encrypted KVM {KVM_NAME} ({cfg['APIGEE_ENV']})")


def build_bundle(proxy: str, cfg: dict) -> bytes:
    placeholders = {k: cfg.get(k, "") for k in (
        "GCP_PROJECT_ID", "MODEL_ARMOR_LOCATION", "MODEL_ARMOR_TEMPLATE", "AZURE_OPENAI_BASE_URL",
        "BEDROCK_BASE_URL", "SERVICENOW_URL", "SALESFORCE_URL", "KNOWLEDGE_BASE_URL")}
    buf = io.BytesIO()
    root = PROXIES_DIR / proxy
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted((root / "apiproxy").rglob("*")):
            if path.is_dir():
                continue
            data = path.read_text(encoding="utf-8")
            if path.suffix == ".xml":
                for key, value in placeholders.items():
                    if value:
                        data = data.replace("{{" + key + "}}", value.rstrip("/"))
                left = re.findall(r"\{\{([A-Z_]+)\}\}", data)
                if left:
                    sys.exit(f"{proxy}: set {', '.join(sorted(set(left)))} in config/poc.env first")
            zf.writestr(path.relative_to(root).as_posix(), data)
    return buf.getvalue()


def cmd_deploy_proxies(cfg, args):
    require(cfg, "APIGEE_ENV", "APIGEE_PROXY_SA")
    api = Api()
    for proxy in args.proxies or ["ai-llm-gateway", "ai-tools-gateway"]:
        bundle = build_bundle(proxy, cfg)
        imported = api.call("POST", f"{org_url(cfg)}/apis", params={"name": proxy, "action": "import"},
                            files={"file": (f"{proxy}.zip", bundle, "application/zip")}).json()
        rev = imported["revision"]
        api.call("POST", f"{org_url(cfg)}/environments/{cfg['APIGEE_ENV']}/apis/{proxy}/revisions/{rev}/deployments",
                 params={"override": "true", "serviceAccount": cfg["APIGEE_PROXY_SA"]})
        print(f"Deployed {proxy} revision {rev} to {cfg['APIGEE_ENV']} (runs as {cfg['APIGEE_PROXY_SA']})")
    print("Deployment takes 1-2 minutes to become ready. Check with: python tools/poc.py status")


def upsert_product(api, cfg, agent):
    body = {
        "name": agent["product"],
        "displayName": agent["displayName"],
        "description": agent["description"],
        "approvalType": "auto",
        "environments": [cfg["APIGEE_ENV"]],
        "proxies": ["ai-llm-gateway", "ai-tools-gateway"],
        "apiResources": ["/**"],
        "attributes": [{"name": "access", "value": "private"}] +
                      [{"name": k, "value": v} for k, v in agent["attributes"].items()],
    }
    url = f"{org_url(cfg)}/apiproducts"
    if api.call("POST", url, ok=(200, 201, 409), json=body).status_code == 409:
        api.call("PUT", f"{url}/{agent['product']}", json=body)


def cmd_setup_agents(cfg, _args):
    require(cfg, "APIGEE_ENV")
    api = Api()
    catalogue = agents_catalogue()
    dev = catalogue["developer"]
    api.call("POST", f"{org_url(cfg)}/developers", ok=(200, 201, 409), json=dev)
    keys = {}
    for agent in catalogue["agents"]:
        upsert_product(api, cfg, agent)
        apps_url = f"{org_url(cfg)}/developers/{dev['email']}/apps"
        resp = api.call("GET", f"{apps_url}/{agent['app']}", ok=(200, 404))
        if resp.status_code == 404:
            resp = api.call("POST", apps_url, ok=(200, 201), json={
                "name": agent["app"], "apiProducts": [agent["product"]],
                "attributes": [{"name": "DisplayName", "value": agent["displayName"]},
                               {"name": "agent_cloud", "value": agent["attributes"]["agent_cloud"]}]})
        keys[KEY_SETTINGS[agent["app"]]] = resp.json()["credentials"][0]["consumerKey"]
        print(f"Agent {agent['app']:16} -> product {agent['product']}")
    save_values(keys)
    print("Saved the three agent keys to config/poc.env")


def cmd_show_agents(cfg, _args):
    api = Api()
    for agent in agents_catalogue()["agents"]:
        product = api.call("GET", f"{org_url(cfg)}/apiproducts/{agent['product']}").json()
        attrs = {a["name"]: a["value"] for a in product.get("attributes", []) if a["name"] != "access"}
        print(f"\n{product['displayName']}  [{agent['product']} / app {agent['app']}]")
        for k, v in attrs.items():
            print(f"   {k:22} {v}")


def cmd_set_policy(cfg, args):
    api = Api()
    api.call("POST", f"{org_url(cfg)}/apiproducts/{args.product}/attributes/{args.attribute}",
             json={"name": args.attribute, "value": args.value})
    print(f"{args.product}: {args.attribute} = {args.value}  (the gateway picks this up within a few minutes)")


def set_app_status(cfg, app, action):
    api = Api()
    dev = agents_catalogue()["developer"]["email"]
    api.call("POST", f"{org_url(cfg)}/developers/{dev}/apps/{app}", ok=(200, 204),
             params={"action": action}, headers={"Content-Type": "application/octet-stream"})
    print(f"Agent app {app}: {action}d  (takes effect at the gateway within a few minutes)")


BQ_API = "https://bigquery.googleapis.com/bigquery/v2"
DATASET = "ai_governance"
SINK = "ai-gateway-audit-to-bq"


def cmd_observability(cfg, _args):
    """BigQuery dataset + Cloud Logging sink for the gateway audit log."""
    project = cfg["GCP_PROJECT_ID"]
    api = Api()
    ds_url = f"{BQ_API}/projects/{project}/datasets"
    api.call("POST", ds_url, ok=(200, 409), json={
        "datasetReference": {"projectId": project, "datasetId": DATASET}, "location": "US",
        "description": "AI governance control tower (Apigee AI gateway audit log)"})
    print(f"BigQuery dataset {project}:{DATASET} ready")

    sink_url = f"https://logging.googleapis.com/v2/projects/{project}/sinks"
    resp = api.call("POST", sink_url, ok=(200, 409), params={"uniqueWriterIdentity": "true"}, json={
        "name": SINK,
        "destination": f"bigquery.googleapis.com/projects/{project}/datasets/{DATASET}",
        "filter": f'logName="projects/{project}/logs/ai-gateway-audit"',
        "bigqueryOptions": {"usePartitionedTables": True},
    })
    sink = resp.json() if resp.status_code == 200 else api.call("GET", f"{sink_url}/{SINK}").json()
    writer = sink["writerIdentity"].split(":", 1)[1]
    print(f"Log sink {SINK} ready (writes as {writer})")

    dataset = api.call("GET", f"{ds_url}/{DATASET}").json()
    access = dataset.get("access", [])
    if not any(a.get("userByEmail") == writer for a in access):
        access.append({"role": "WRITER", "userByEmail": writer})
        api.call("PATCH", f"{ds_url}/{DATASET}", json={"access": access})
    print("Sink may write to the dataset. New gateway traffic appears in BigQuery within a few minutes.")


def cmd_create_views(cfg, _args):
    """Creates the control-tower views (run after some gateway traffic has been logged)."""
    project = cfg["GCP_PROJECT_ID"]
    api = Api()
    sql = (ROOT / "observability" / "control_tower_views.sql").read_text(encoding="utf-8")
    sql = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--")).replace("PROJECT_ID", project)
    for statement in filter(None, (s.strip() for s in sql.split(";"))):
        resp = api.call("POST", f"{BQ_API}/projects/{project}/queries", ok=(200, 400, 404), json={
            "query": statement, "useLegacySql": False, "location": "US"})
        name = re.search(r"VIEW `([^`]+)`", statement).group(1)
        if resp.status_code != 200:
            sys.exit(f"Could not create {name}: {resp.json()['error']['message']}\n"
                     "If a column is missing, run the governance demo first so every field has been logged.")
        print(f"Created view {name}")


def cmd_status(cfg, _args):
    api = Api()
    deps = api.call("GET", f"{org_url(cfg)}/environments/{cfg['APIGEE_ENV']}/deployments").json()
    for d in deps.get("deployments", []):
        print(f"  {d['apiProxy']:20} revision {d['revision']:4} {d.get('state', '')}")
    if cfg.get("APIGEE_HOST"):
        print(f"\nGateway base URL: {cfg['APIGEE_HOST']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check")
    sub.add_parser("model-armor-template")
    p = sub.add_parser("model-armor-test")
    p.add_argument("text")
    sub.add_parser("kvm")
    p = sub.add_parser("deploy-proxies")
    p.add_argument("proxies", nargs="*")
    sub.add_parser("setup-agents")
    sub.add_parser("show-agents")
    p = sub.add_parser("set-policy")
    p.add_argument("product")
    p.add_argument("attribute")
    p.add_argument("value")
    for name in ("revoke", "approve"):
        p = sub.add_parser(name)
        p.add_argument("app")
    sub.add_parser("observability")
    sub.add_parser("create-views")
    sub.add_parser("status")
    args = parser.parse_args()
    cfg = load_config()

    if args.command in ("revoke", "approve"):
        set_app_status(cfg, args.app, args.command)
        return
    handler = globals()["cmd_" + args.command.replace("-", "_")]
    handler(cfg, args)


if __name__ == "__main__":
    main()
