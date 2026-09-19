"""Sales Account agent - AWS (Strands Agents on Amazon Bedrock AgentCore Runtime).

Governance pattern: the only secret this agent has is its Apigee agent key,
kept in AgentCore Identity. Model calls (Amazon Bedrock), the Salesforce MCP
server and the knowledge base are all reached through the Apigee AI gateway.
"""

from collections import OrderedDict

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent

from mcp_client.client import get_salesforce_mcp_client
from model.load import get_gateway_key, load_model
from tools.gateway_tools import make_kb_search

app = BedrockAgentCoreApp()
log = app.logger

SYSTEM_PROMPT = """You are the Sales Account agent for Contoso, running on AWS.
You help account managers with Salesforce accounts, contacts, opportunities and cases,
and use the knowledge base for customer-facing policies and workarounds.
- Look data up with the Salesforce tools; never invent figures.
- If a tool result says ACCESS DENIED, explain that the enterprise AI gateway blocked it.
- Keep answers short and business-focused."""


def agent_factory():
    """One Agent per session so each conversation keeps its own history (bounded LRU)."""
    cache = OrderedDict()

    def get_or_create(session_id):
        if session_id in cache:
            cache.move_to_end(session_id)
            return cache[session_id]
        if len(cache) >= 64:
            cache.popitem(last=False)
        key = get_gateway_key()
        cache[session_id] = Agent(
            model=load_model(key),
            system_prompt=SYSTEM_PROMPT,
            tools=[get_salesforce_mcp_client(key), make_kb_search(key)],
        )
        return cache[session_id]

    return get_or_create


get_or_create_agent = agent_factory()


@app.entrypoint
async def invoke(payload, context):
    prompt = payload.get("prompt") if isinstance(payload, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": 'Send a JSON payload like {"prompt": "..."}'}

    session_id = getattr(context, "session_id", None) or "default-session"
    agent = get_or_create_agent(session_id)
    try:
        result = await agent.invoke_async(prompt)
        return {"agent": "sales-agent-aws", "result": str(result)}
    except Exception as exc:  # gateway denials (blocked prompt, quota, revoked key) surface here
        log.warning("Gateway or model error: %s", exc)
        return {"agent": "sales-agent-aws",
                "result": f"The enterprise AI gateway stopped this request. Details: {exc}"}


if __name__ == "__main__":
    app.run()
