from strands.tools.mcp import MCPClient

from model.load import gateway_url


def get_salesforce_mcp_client(key: str) -> MCPClient:
    """Salesforce MCP server, reached only through the Apigee AI gateway."""
    return MCPClient(url=f"{gateway_url()}/ai/tools/mcp/salesforce", headers={"x-api-key": key})
