"""Customer 360 agent - Microsoft Azure (Microsoft Agent Framework on Azure Container Apps).

Governance pattern: the agent holds only its Apigee agent key. Azure OpenAI,
the ServiceNow and Salesforce MCP servers and the knowledge base are all
reached through the Apigee AI gateway, which gives this agent READ-ONLY tools
and masks personal data for it.
"""

import os
import uuid
from pathlib import Path
from typing import Annotated

import httpx
from agent_framework import Agent, MCPStreamableHTTPTool, tool
from agent_framework.openai import OpenAIChatCompletionClient
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

GATEWAY_URL = os.environ["AI_GATEWAY_URL"].rstrip("/")
GATEWAY_KEY = os.environ["AI_GATEWAY_API_KEY"]
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-5-mini")
HEADERS = {"x-api-key": GATEWAY_KEY}

INSTRUCTIONS = """You are the Customer 360 agent for Contoso, running on Microsoft Azure.
You give customer-facing staff one view of a customer across Salesforce (accounts, cases)
and ServiceNow (incidents), plus knowledge-base guidance.
- For a customer question: find the account, check its cases, then look up any related incident.
- Search the knowledge base for workarounds and policies; cite the article id.
- You are read-only. If a tool result says ACCESS DENIED, explain that the enterprise AI
  gateway blocked the action and who could do it instead.
- Personal data may appear masked (***); never try to guess it."""


@tool
def kb_search(query: Annotated[str, Field(description="Keywords describing what to look for")]) -> dict:
    """Search the enterprise knowledge base for policies, workarounds and troubleshooting articles."""
    resp = httpx.get(f"{GATEWAY_URL}/ai/tools/kb/search", params={"q": query, "top": 3},
                     headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        return {"error": f"AI gateway returned {resp.status_code}: {resp.text}"}
    return resp.json()


def build_agent() -> Agent:
    http_client = httpx.AsyncClient(headers=HEADERS, timeout=60)
    return Agent(
        client=OpenAIChatCompletionClient(
            model=LLM_MODEL,
            api_key=GATEWAY_KEY,
            base_url=f"{GATEWAY_URL}/ai/llm/v1",     # Azure OpenAI, reached through the gateway
            default_headers=HEADERS,
        ),
        name="customer360",
        instructions=INSTRUCTIONS,
        tools=[
            MCPStreamableHTTPTool(name="servicenow", url=f"{GATEWAY_URL}/ai/tools/mcp/servicenow",
                                  http_client=http_client, load_prompts=False),
            MCPStreamableHTTPTool(name="salesforce", url=f"{GATEWAY_URL}/ai/tools/mcp/salesforce",
                                  http_client=http_client, load_prompts=False),
            kb_search,
        ],
    )


agent = build_agent()
sessions: dict = {}
app = FastAPI(title="Customer 360 agent (Azure)")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "agent": "cx-agent-azure", "model": LLM_MODEL}


@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    if session_id not in sessions:
        if len(sessions) > 200:
            sessions.clear()
        sessions[session_id] = agent.create_session(session_id=session_id)
    try:
        result = await agent.run(req.message, session=sessions[session_id])
        reply = result.text
    except Exception as exc:  # gateway denials (blocked prompt, quota, revoked key) surface here
        reply = f"The enterprise AI gateway stopped this request.\n\nDetails: {exc}"
    return {"session_id": session_id, "reply": reply}
