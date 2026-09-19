"""Mock Salesforce (CRM) system of record.

Exposes the same data two ways:
  * REST API shaped like the Salesforce REST API -> /services/data/v62.0/...
  * MCP server (streamable HTTP, stateless, JSON) -> /mcp/salesforce

Data is held in memory and resets whenever the container restarts. Access
control is NOT done here: only the Apigee AI gateway may call this service.
"""

import contextlib
import copy
import logging

from fastapi import FastAPI, HTTPException, Request
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("mock-salesforce")

API = "/services/data/v62.0"

SEED = {
    "accounts": [
        {"Id": "001A000001", "Name": "Acme Corp", "Industry": "Manufacturing", "Tier": "Platinum",
         "AnnualRevenue": 540000000, "BillingCountry": "USA", "Owner": "Jordan Blake"},
        {"Id": "001A000002", "Name": "Globex", "Industry": "Energy", "Tier": "Gold",
         "AnnualRevenue": 210000000, "BillingCountry": "USA", "Owner": "Emma Wright"},
        {"Id": "001A000003", "Name": "Initech Australia", "Industry": "Financial Services", "Tier": "Silver",
         "AnnualRevenue": 48000000, "BillingCountry": "Australia", "Owner": "Noah Singh"},
    ],
    "contacts": [
        {"Id": "003A000001", "AccountId": "001A000001", "Name": "Sarah Mitchell", "Title": "CFO",
         "Email": "sarah.mitchell@acme.example", "Phone": "+1 415 555 0142"},
        {"Id": "003A000002", "AccountId": "001A000001", "Name": "Raj Patel", "Title": "Head of Procurement",
         "Email": "raj.patel@acme.example", "Phone": "+1 415 555 0177"},
        {"Id": "003A000003", "AccountId": "001A000002", "Name": "Hank Scorpio", "Title": "CEO",
         "Email": "hank.scorpio@globex.example", "Phone": "+1 212 555 0199"},
        {"Id": "003A000004", "AccountId": "001A000003", "Name": "Olivia Tran", "Title": "IT Director",
         "Email": "olivia.tran@initech.example", "Phone": "+61 2 5550 1234"},
    ],
    "opportunities": [
        {"Id": "006A000001", "AccountId": "001A000001", "Name": "Acme - Portal Expansion FY27",
         "StageName": "Negotiation", "Amount": 1250000, "CloseDate": "2026-10-31", "Probability": 70},
        {"Id": "006A000002", "AccountId": "001A000001", "Name": "Acme - Support Renewal",
         "StageName": "Proposal", "Amount": 380000, "CloseDate": "2026-11-15", "Probability": 50},
        {"Id": "006A000003", "AccountId": "001A000002", "Name": "Globex - Billing Modernisation",
         "StageName": "Qualification", "Amount": 640000, "CloseDate": "2027-01-20", "Probability": 20},
        {"Id": "006A000004", "AccountId": "001A000003", "Name": "Initech - AI Governance Pilot",
         "StageName": "Closed Won", "Amount": 150000, "CloseDate": "2026-08-30", "Probability": 100},
    ],
    "cases": [
        {"Id": "500A000001", "CaseNumber": "00001026", "AccountId": "001A000001",
         "Subject": "Cannot place orders on B2B portal", "Status": "Escalated", "Priority": "High",
         "ContactId": "003A000001", "RelatedIncident": "INC0010002",
         "Description": "CFO escalated: order submission failing since last night, revenue impact."},
        {"Id": "500A000002", "CaseNumber": "00001027", "AccountId": "001A000002",
         "Subject": "Invoices not downloadable", "Status": "Working", "Priority": "Medium",
         "ContactId": "003A000003", "RelatedIncident": "INC0010004",
         "Description": "Finance team blocked on month-end close."},
    ],
}

VALID_STAGES = ["Prospecting", "Qualification", "Proposal", "Negotiation", "Closed Won", "Closed Lost"]

DB: dict[str, list[dict]] = {}


def reset_data() -> None:
    DB.clear()
    DB.update(copy.deepcopy(SEED))


reset_data()


def _find(table: str, key: str, value: str) -> dict:
    for row in DB[table]:
        if str(row[key]).lower() == str(value).lower():
            return row
    raise KeyError(f"{table[:-1].capitalize()} {value} not found")


# ---------------------------------------------------------------------------
# Business logic shared by REST and MCP
# ---------------------------------------------------------------------------

def search_accounts(name: str) -> list[dict]:
    return [a for a in DB["accounts"] if name.lower() in a["Name"].lower()]


def get_account(account_id: str) -> dict:
    account = copy.deepcopy(_find("accounts", "Id", account_id))
    account["Contacts"] = [c for c in DB["contacts"] if c["AccountId"] == account_id]
    account["OpenOpportunities"] = [o for o in DB["opportunities"]
                                    if o["AccountId"] == account_id and not o["StageName"].startswith("Closed")]
    account["Cases"] = [c for c in DB["cases"] if c["AccountId"] == account_id]
    return account


def list_opportunities(account_id: str | None = None, stage: str | None = None) -> list[dict]:
    rows = DB["opportunities"]
    if account_id:
        rows = [o for o in rows if o["AccountId"] == account_id]
    if stage:
        rows = [o for o in rows if o["StageName"].lower() == stage.lower()]
    return rows


def update_opportunity_stage(opportunity_id: str, stage: str) -> dict:
    if stage not in VALID_STAGES:
        raise ValueError(f"stage must be one of {VALID_STAGES}")
    opp = _find("opportunities", "Id", opportunity_id)
    opp["StageName"] = stage
    return opp


def get_case(case_number: str) -> dict:
    case = copy.deepcopy(_find("cases", "CaseNumber", case_number))
    case["Contact"] = _find("contacts", "Id", case["ContactId"])
    return case


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "salesforce",
    instructions="Mock Salesforce CRM. Tools read accounts, contacts, opportunities and cases.",
    streamable_http_path="/mcp/salesforce",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def sf_search_accounts(name: str) -> list[dict]:
    """Search Salesforce accounts by (partial) company name. Returns account Ids to use with other tools."""
    return search_accounts(name)


@mcp.tool()
def sf_get_account(account_id: str) -> dict:
    """Get a Salesforce account with its contacts (names, emails, phones), open opportunities and cases."""
    return get_account(account_id)


@mcp.tool()
def sf_list_opportunities(account_id: str = "", stage: str = "") -> list[dict]:
    """List Salesforce opportunities, optionally filtered by account Id and/or stage name."""
    return list_opportunities(account_id or None, stage or None)


@mcp.tool()
def sf_update_opportunity_stage(opportunity_id: str, stage: str) -> dict:
    """Change the stage of a Salesforce opportunity. WRITE action. Stages: Prospecting, Qualification,
    Proposal, Negotiation, Closed Won, Closed Lost."""
    return update_opportunity_stage(opportunity_id, stage)


@mcp.tool()
def sf_get_case(case_number: str) -> dict:
    """Get a Salesforce support case by case number (e.g. 00001026), including the contact and the
    related ServiceNow incident number."""
    return get_case(case_number)


# ---------------------------------------------------------------------------
# FastAPI app (REST API + MCP at /mcp/salesforce)
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="Mock Salesforce", lifespan=lifespan)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    response = await call_next(request)
    log.info("%s %s -> %s", request.method, request.url.path, response.status_code)
    return response


class StagePatch(BaseModel):
    StageName: str


@app.get("/healthz")
def healthz():
    return {"status": "ok", "system": "salesforce-mock", "accounts": len(DB["accounts"])}


@app.post("/admin/reset")
def admin_reset():
    reset_data()
    return {"status": "reset"}


@app.get(f"{API}/search/accounts")
def rest_search(name: str):
    return {"records": search_accounts(name)}


@app.get(f"{API}/sobjects/Account/{{account_id}}")
def rest_account(account_id: str):
    try:
        return get_account(account_id)
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get(f"{API}/sobjects/Opportunity")
def rest_opps(account_id: str | None = None, stage: str | None = None):
    return {"records": list_opportunities(account_id, stage)}


@app.patch(f"{API}/sobjects/Opportunity/{{opportunity_id}}")
def rest_patch_opp(opportunity_id: str, body: StagePatch):
    try:
        return update_opportunity_stage(opportunity_id, body.StageName)
    except KeyError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get(f"{API}/sobjects/Case/{{case_number}}")
def rest_case(case_number: str):
    try:
        return get_case(case_number)
    except KeyError as e:
        raise HTTPException(404, str(e))


# Mounted last so the REST routes above take precedence. The MCP endpoint is /mcp/salesforce.
app.mount("/", mcp.streamable_http_app())
