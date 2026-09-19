# Multi-cloud AI agent governance POC (Track A: Build)

Agents in **Google Cloud (ADK)**, **AWS (Strands on Bedrock AgentCore)** and **Azure (Microsoft Agent Framework)**
reach every LLM, MCP server and tool through **one governed Apigee AI gateway**. That gateway handles:

- **Identity:** one key per agent.
- **Allowlists:** which models and tools each agent may use.
- **Token budgets:** hourly limits per agent.
- **Safety:** Model Armor screening for prompt injection and sensitive data.
- **PII masking:** personal data hidden from agents not approved for it.
- **Kill switch:** revoke an agent in one step.
- **Audit:** one log across all clouds, feeding a BigQuery "control tower".

ServiceNow, Salesforce and the knowledge base are **mock systems**. They expose realistic REST and MCP interfaces.

Two step-by-step build guides exist (a browser/console one and a command-line one). They are kept internally
and are not part of this repository, because they contain project-specific names and account details.

| Folder | What it contains |
|---|---|
| `mock-systems/` | Mock ServiceNow and Salesforce (REST and MCP), plus the knowledge-base REST API, for Cloud Run |
| `apigee/proxies/` | `ai-llm-gateway` and `ai-tools-gateway` proxy bundles |
| `apigee/governance/agents.json` | The governance catalogue: each agent's allowed models, tools, PII access and token budget |
| `agents/gcp-itsm-agent/` | IT Service Desk agent (Google ADK), deployed to Cloud Run |
| `agents/aws-sales-agent/app/` | Sales Account agent (Strands) for AgentCore Runtime (command-line path) |
| `agents/aws-sales-agent/webapp/` | The same agent as a web app for AWS App Runner (console path) |
| `agents/azure-cx-agent/` | Customer 360 agent (Microsoft Agent Framework), deployed to Azure Container Apps |
| `tools/poc.py` | Admin helper: Model Armor, KVM, proxy deployment, agent onboarding, live policy changes, observability |
| `tools/governance_demo.py` | Scripted pass/fail proof of every governance control |
| `tools/postman/` | The same 17 checks as a Postman collection, for the console path |
| `observability/` | BigQuery views for the control-tower dashboard |
| `tests/apigee-policy-tests.js` | Offline unit tests for the gateway policy logic (`node tests/apigee-policy-tests.js`) |
| `config/poc.env.example` | All settings; copy it to `config/poc.env` (never commit that file) |
