"""Mock ServiceNow (ITSM) system of record.

Exposes the same data two ways:
  * REST API shaped like the ServiceNow Table API  -> /api/now/table/incident
  * MCP server (streamable HTTP, stateless, JSON)  -> /mcp/servicenow

Data is held in memory and resets whenever the container restarts, which is
what we want for a repeatable demo. Access control is NOT done here: the
service is private on Cloud Run and only the Apigee AI gateway may call it.
"""

import contextlib
import copy
import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mock-servicenow")

SEED_INCIDENTS = [
    {
        "number": "INC0010001",
        "short_description": "VPN disconnects every 10 minutes",
        "description": "Remote staff in Sydney report the corporate VPN dropping every 10 minutes since Monday.",
        "priority": "3 - Moderate",
        "state": "In Progress",
        "category": "Network",
        "assignment_group": "Network Operations",
        "assigned_to": "Priya Nair",
        "caller": {"name": "Tom Baker", "email": "tom.baker@contoso.example", "phone": "+61 400 111 222"},
        "company": "Contoso Internal",
        "opened_at": "2026-09-14T09:12:00Z",
        "work_notes": ["Firewall logs collected, suspect idle-timeout setting."],
    },
    {
        "number": "INC0010002",
        "short_description": "Order portal outage for Acme Corp",
        "description": "Acme Corp users receive HTTP 503 when submitting orders on the B2B portal.",
        "priority": "1 - Critical",
        "state": "In Progress",
        "category": "Application",
        "assignment_group": "B2B Platform Team",
        "assigned_to": "Liam Chen",
        "caller": {"name": "Sarah Mitchell", "email": "sarah.mitchell@acme.example", "phone": "+1 415 555 0142"},
        "company": "Acme Corp",
        "opened_at": "2026-09-15T22:40:00Z",
        "work_notes": ["Database connection pool exhausted; scaling in progress.", "Workaround: KB0010003."],
    },
    {
        "number": "INC0010003",
        "short_description": "Password reset link expired",
        "description": "User cannot reset password; link says expired immediately.",
        "priority": "4 - Low",
        "state": "New",
        "category": "Access",
        "assignment_group": "Service Desk",
        "assigned_to": "",
        "caller": {"name": "Aisha Rahman", "email": "aisha.rahman@contoso.example", "phone": "+61 400 333 444"},
        "company": "Contoso Internal",
        "opened_at": "2026-09-16T01:05:00Z",
        "work_notes": [],
    },
    {
        "number": "INC0010004",
        "short_description": "Invoice PDF generation failing for Globex",
        "description": "Globex finance team cannot download invoice PDFs; spinner never completes.",
        "priority": "2 - High",
        "state": "On Hold",
        "category": "Application",
        "assignment_group": "Billing Platform Team",
        "assigned_to": "Marco Rossi",
        "caller": {"name": "Hank Scorpio", "email": "hank.scorpio@globex.example", "phone": "+1 212 555 0199"},
        "company": "Globex",
        "opened_at": "2026-09-12T15:30:00Z",
        "work_notes": ["Waiting on vendor patch for PDF library."],
    },
    {
        "number": "INC0010005",
        "short_description": "Laptop battery swelling",
        "description": "Hardware safety issue reported on a 2023 laptop.",
        "priority": "2 - High",
        "state": "Resolved",
        "category": "Hardware",
        "assignment_group": "Desktop Support",
        "assigned_to": "Grace Lee",
        "caller": {"name": "Ben Ortiz", "email": "ben.ortiz@contoso.example", "phone": "+61 400 555 666"},
        "company": "Contoso Internal",
        "opened_at": "2026-09-10T08:00:00Z",
        "work_notes": ["Device replaced."],
    },
]

VALID_STATES = ["New", "In Progress", "On Hold", "Resolved", "Closed"]

INCIDENTS: dict[str, dict] = {}


def reset_data() -> None:
    INCIDENTS.clear()
    for incident in SEED_INCIDENTS:
        INCIDENTS[incident["number"]] = copy.deepcopy(incident)


reset_data()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _summary(incident: dict) -> dict:
    return {k: incident[k] for k in ("number", "short_description", "priority", "state", "company", "assigned_to")}


# ---------------------------------------------------------------------------
# Business logic shared by REST and MCP
# ---------------------------------------------------------------------------

def list_incidents(state: str | None = None, company: str | None = None, limit: int = 10) -> list[dict]:
    rows = list(INCIDENTS.values())
    if state:
        rows = [r for r in rows if r["state"].lower() == state.lower()]
    if company:
        rows = [r for r in rows if company.lower() in r["company"].lower()]
    return [_summary(r) for r in rows[: max(1, min(limit, 50))]]


def get_incident(number: str) -> dict:
    incident = INCIDENTS.get(number.upper())
    if not incident:
        raise KeyError(f"Incident {number} not found")
    return incident


def create_incident(short_description: str, description: str, priority: str, caller_email: str, company: str) -> dict:
    number = f"INC{max(int(n[3:]) for n in INCIDENTS) + 1:07d}"
    incident = {
        "number": number,
        "short_description": short_description,
        "description": description,
        "priority": priority,
        "state": "New",
        "category": "General",
        "assignment_group": "Service Desk",
        "assigned_to": "",
        "caller": {"name": "", "email": caller_email, "phone": ""},
        "company": company,
        "opened_at": _now(),
        "work_notes": [],
    }
    INCIDENTS[number] = incident
    return incident


def update_incident(number: str, state: str | None = None, work_note: str | None = None) -> dict:
    incident = get_incident(number)
    if state:
        if state not in VALID_STATES:
            raise ValueError(f"state must be one of {VALID_STATES}")
        incident["state"] = state
    if work_note:
        incident["work_notes"].append(f"[{_now()}] {work_note}")
    return incident


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "servicenow",
    instructions="Mock ServiceNow ITSM. Tools read and change IT incidents.",
    streamable_http_path="/mcp/servicenow",
    stateless_http=True,
    json_response=True,
    # Cloud Run gives us a public hostname, so the localhost-only default must be off.
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def sn_list_incidents(state: str = "", company: str = "", limit: int = 10) -> list[dict]:
    """List ServiceNow incidents. Optional filters: state (New, In Progress, On Hold, Resolved, Closed) and company name."""
    return list_incidents(state or None, company or None, limit)


@mcp.tool()
def sn_get_incident(number: str) -> dict:
    """Get full details of one ServiceNow incident by number, e.g. INC0010002. Includes caller contact details."""
    return get_incident(number)


@mcp.tool()
def sn_create_incident(short_description: str, description: str, caller_email: str,
                       priority: str = "3 - Moderate", company: str = "Contoso Internal") -> dict:
    """Create a new ServiceNow incident. Priority is one of '1 - Critical', '2 - High', '3 - Moderate', '4 - Low'."""
    return create_incident(short_description, description, priority, caller_email, company)


@mcp.tool()
def sn_add_work_note(number: str, work_note: str) -> dict:
    """Add a work note to an existing ServiceNow incident."""
    return update_incident(number, work_note=work_note)


@mcp.tool()
def sn_close_incident(number: str, resolution_notes: str) -> dict:
    """Close a ServiceNow incident. HIGH-RISK action: only approved agents may use it."""
    return update_incident(number, state="Closed", work_note=f"Closed: {resolution_notes}")


# ---------------------------------------------------------------------------
# FastAPI app (REST API + MCP at /mcp/servicenow)
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Mock ServiceNow", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    log.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


class IncidentCreate(BaseModel):
    short_description: str
    description: str = ""
    priority: str = "3 - Moderate"
    caller_email: str
    company: str = "Contoso Internal"


class IncidentPatch(BaseModel):
    state: str | None = None
    work_note: str | None = None


@app.get("/healthz")
def healthz():
    return {"status": "ok", "system": "servicenow-mock", "incidents": len(INCIDENTS)}


@app.post("/admin/reset")
def admin_reset():
    reset_data()
    return {"status": "reset", "incidents": len(INCIDENTS)}


@app.get("/api/now/table/incident")
def rest_list(state: str | None = None, company: str | None = None, limit: int = 10):
    return {"result": list_incidents(state, company, limit)}


@app.get("/api/now/table/incident/{number}")
def rest_get(number: str):
    try:
        return {"result": get_incident(number)}
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.post("/api/now/table/incident", status_code=201)
def rest_create(body: IncidentCreate):
    return {"result": create_incident(body.short_description, body.description, body.priority,
                                      body.caller_email, body.company)}


@app.patch("/api/now/table/incident/{number}")
def rest_patch(number: str, body: IncidentPatch):
    try:
        return {"result": update_incident(number, body.state, body.work_note)}
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


# Mounted last so the REST routes above take precedence. The MCP endpoint is /mcp/servicenow.
app.mount("/", mcp.streamable_http_app())
