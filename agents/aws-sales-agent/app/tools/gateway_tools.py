import httpx
from strands import tool

from model.load import gateway_url


def make_kb_search(key: str):
    """Knowledge-base REST tool, reached only through the Apigee AI gateway."""

    @tool
    def kb_search(query: str) -> dict:
        """Search the enterprise knowledge base for policies, workarounds and troubleshooting articles.

        Args:
            query: Keywords describing what to look for.
        """
        resp = httpx.get(f"{gateway_url()}/ai/tools/kb/search", params={"q": query, "top": 3},
                         headers={"x-api-key": key}, timeout=30)
        if resp.status_code != 200:
            return {"error": f"AI gateway returned {resp.status_code}: {resp.text}"}
        return resp.json()

    return kb_search
