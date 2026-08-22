"""
MCP Browser Client

Calls the pipeline-doctor-mcp-browser-v2 Lambda using direct boto3
InvokeFunction — no HTTP Function URL needed.

This avoids account-level SCP restrictions on public Lambda URLs while
keeping the same JSON-RPC 2.0 MCP protocol.  The Pipeline Doctor Lambda's
execution role already has lambda:InvokeFunction on the MCP browser ARN
(granted by CDK).

Supports two tools:
  fetch(url)                   → page text
  web_search(query, n)         → list of result snippets

Falls back silently if:
  - MCP_BROWSER_FUNCTION_NAME is not set (returns empty / placeholder)
  - The invoke call fails (logs a warning, does not crash the agent)

Environment variables:
  MCP_BROWSER_FUNCTION_NAME  — Lambda function name (default: pipeline-doctor-mcp-browser-v2)
  MCP_BROWSER_REGION         — AWS region of that Lambda (default: us-east-1)
  MCP_BROWSER_URL            — kept for env-var compatibility, not used
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

import boto3
import structlog

log = structlog.get_logger(__name__)

MCP_BROWSER_FUNCTION_NAME = os.getenv(
    "MCP_BROWSER_FUNCTION_NAME", "pipeline-doctor-mcp-browser-v2"
)
MCP_BROWSER_REGION = os.getenv("MCP_BROWSER_REGION", os.getenv("AWS_REGION", "us-east-1"))


class MCPBrowserClient:
    """
    Thin client for the MCP Browser Lambda using direct boto3 InvokeFunction.

    Usage:
        client = MCPBrowserClient()
        text   = client.fetch("https://docs.python.org/3/library/venv.html")
        hits   = client.web_search("ModuleNotFoundError boto3 fix")
    """

    def __init__(
        self,
        function_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.function_name = function_name or MCP_BROWSER_FUNCTION_NAME
        self.region = region or MCP_BROWSER_REGION
        self._call_id = 0
        self._lambda_client = None  # lazy init

    def _get_lambda(self):
        if self._lambda_client is None:
            self._lambda_client = boto3.client("lambda", region_name=self.region)
        return self._lambda_client

    # ------------------------------------------------------------------
    # Tool wrappers
    # ------------------------------------------------------------------

    def fetch(self, url: str, max_bytes: int = 32768) -> str:
        """Fetch a URL via the MCP browser Lambda and return the page text."""
        result = self._call_tool("fetch", {"url": url, "max_bytes": max_bytes})
        return _extract_text(result)

    def web_search(self, query: str, num_results: int = 5) -> list[str]:
        """Search the web and return a list of formatted result snippets."""
        result = self._call_tool("web_search", {"query": query, "num_results": num_results})
        raw = _extract_text(result)
        if not raw:
            return []
        parts = re.split(r"\n(?=\d+\. )", raw)
        return [p.strip() for p in parts if p.strip() and not p.startswith("Search results")]

    def list_tools(self) -> list[dict]:
        """Return the list of tools advertised by the MCP server."""
        response = self._rpc("tools/list", {})
        return response.get("result", {}).get("tools", [])

    # ------------------------------------------------------------------
    # Internal JSON-RPC over boto3 Lambda invoke
    # ------------------------------------------------------------------

    def _call_tool(self, name: str, arguments: dict) -> dict:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})

    def _rpc(self, method: str, params: dict) -> dict:
        """
        Invoke the MCP browser Lambda directly via boto3 InvokeFunction
        and return the JSON-RPC response dict.
        On any error returns {"error": {...}} rather than raising.
        """
        if not self.function_name:
            log.debug("mcp_browser_not_configured", method=method)
            return {"result": {"content": [{"type": "text", "text": ""}]}}

        self._call_id += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": str(self._call_id),
            "method": method,
            "params": params,
        })

        try:
            response = self._get_lambda().invoke(
                FunctionName=self.function_name,
                InvocationType="RequestResponse",
                Payload=payload.encode("utf-8"),
            )
            raw = response["Payload"].read().decode("utf-8")
            data = json.loads(raw)
            # Unwrap HTTP envelope if present (Function URL path)
            if "body" in data and "statusCode" in data:
                data = json.loads(data["body"])
            return data

        except Exception as exc:
            log.warning("mcp_browser_call_failed", method=method, error=str(exc))
            return {"error": {"code": -1, "message": str(exc)}}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _extract_text(rpc_response: dict) -> str:
    """Pull the text content out of an MCP tools/call response."""
    result = rpc_response.get("result", {})
    content = result.get("content", [])
    for block in content:
        if block.get("type") == "text":
            return block.get("text", "")
    return ""
