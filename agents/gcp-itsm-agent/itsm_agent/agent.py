"""IT Service Desk agent - Google Cloud (Agent Development Kit).

Governance pattern: this agent holds ONE credential, its Apigee agent key.
Every model call, MCP tool call and REST tool call goes through the
Apigee AI gateway, which decides what this agent may do.
"""

import os

import httpx
from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.tools.mcp_tool import McpToolset, StreamableHTTPConnectionParams
from google.genai import types

GATEWAY_URL = os.environ["AI_GATEWAY_URL"].rstrip("/")
GATEWAY_KEY = os.environ["AI_GATEWAY_API_KEY"]
LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")
HEADERS = {"x-api-key": GATEWAY_KEY}

INSTRUCTION = """You are the IT Service Desk agent for Contoso, running on Google Cloud.
You help staff with IT incidents using the ServiceNow tools and the knowledge base.
- Always look up an incident before answering questions about it.
- Search the knowledge base for fixes and workarounds and cite the article id.
- If a tool result says ACCESS DENIED, explain that the enterprise AI gateway blocked
  the action and suggest contacting a human service desk analyst.
- Never invent incident numbers or data."""


def kb_search(query: str) -> dict:
    """Search the enterprise knowledge base for troubleshooting articles and policies.

    Args:
        query: Keywords describing the problem, e.g. "vpn disconnects".
    """
    resp = httpx.get(f"{GATEWAY_URL}/ai/tools/kb/search", params={"q": query, "top": 3},
                     headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        return {"error": f"AI gateway returned {resp.status_code}: {resp.text}"}
    return resp.json()


def explain_gateway_block(callback_context, llm_request, error: Exception):
    """Turn a gateway denial (blocked prompt, quota, model not allowed) into a visible reply."""
    return LlmResponse(content=types.Content(role="model", parts=[types.Part(
        text=f"The enterprise AI gateway stopped this request.\n\nDetails: {error}")]))


root_agent = Agent(
    name="itsm_agent",
    description="IT Service Desk agent (Google Cloud) governed by the Apigee AI gateway",
    model=LiteLlm(
        model=f"openai/{LLM_MODEL}",          # OpenAI-compatible protocol, served by the gateway
        api_base=f"{GATEWAY_URL}/ai/llm/v1",
        api_key=GATEWAY_KEY,
        extra_headers=HEADERS,
    ),
    instruction=INSTRUCTION,
    tools=[
        McpToolset(connection_params=StreamableHTTPConnectionParams(
            url=f"{GATEWAY_URL}/ai/tools/mcp/servicenow", headers=HEADERS)),
        kb_search,
    ],
    on_model_error_callback=explain_gateway_block,
)
