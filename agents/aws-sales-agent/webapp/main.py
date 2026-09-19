"""Sales Account agent - AWS, as a small web app (for AWS App Runner).

Same agent and same governance as the AgentCore version in ../app, but packaged
as a FastAPI web app with a chat page, so it can be deployed from the AWS
console without any command line.

The only credential it holds is its Apigee agent key. Amazon Bedrock, the
Salesforce MCP server and the knowledge base are all reached through the
Apigee AI gateway.
"""

import os
import uuid
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel
from strands import Agent, tool
from strands.models.openai import OpenAIModel
from strands.tools.mcp import MCPClient

GATEWAY_URL = os.environ["AI_GATEWAY_URL"].rstrip("/")
GATEWAY_KEY = os.environ["AI_GATEWAY_API_KEY"]
LLM_MODEL = os.environ.get("LLM_MODEL", "openai.gpt-oss-120b")
HEADERS = {"x-api-key": GATEWAY_KEY}

SYSTEM_PROMPT = """You are the Sales Account agent for Contoso, running on AWS.
You help account managers with Salesforce accounts, contacts, opportunities and cases,
and use the knowledge base for customer-facing policies and workarounds.
- Look data up with the Salesforce tools; never invent figures.
- If a tool result says ACCESS DENIED, explain that the enterprise AI gateway blocked it.
- Keep answers short and business-focused."""


@tool
def kb_search(query: str) -> dict:
    """Search the enterprise knowledge base for policies, workarounds and troubleshooting articles.

    Args:
        query: Keywords describing what to look for.
    """
    resp = httpx.get(f"{GATEWAY_URL}/ai/tools/kb/search", params={"q": query, "top": 3},
                     headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        return {"error": f"AI gateway returned {resp.status_code}: {resp.text}"}
    return resp.json()


def build_agent() -> Agent:
    return Agent(
        model=OpenAIModel(
            client_args={"api_key": GATEWAY_KEY, "base_url": f"{GATEWAY_URL}/ai/llm/v1",
                         "default_headers": HEADERS},
            model_id=LLM_MODEL,
        ),
        system_prompt=SYSTEM_PROMPT,
        tools=[MCPClient(url=f"{GATEWAY_URL}/ai/tools/mcp/salesforce", headers=HEADERS), kb_search],
    )


sessions: dict = {}
app = FastAPI(title="Sales Account agent (AWS)")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "agent": "sales-agent-aws", "model": LLM_MODEL}


@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id or str(uuid.uuid4())
    if session_id not in sessions:
        if len(sessions) > 100:
            sessions.clear()
        sessions[session_id] = build_agent()
    try:
        result = await sessions[session_id].invoke_async(req.message)
        reply = str(result)
    except Exception as exc:  # gateway denials (blocked prompt, quota, revoked key) surface here
        reply = f"The enterprise AI gateway stopped this request.\n\nDetails: {exc}"
    return {"session_id": session_id, "reply": reply}
