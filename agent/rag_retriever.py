"""
RAG Retriever - Queries the Bedrock Knowledge Base for relevant runbooks,
documentation, and previous incident reports.

Also performs live web search and URL fetching via the MCP Browser Lambda
when MCP_BROWSER_URL is configured, enriching diagnosis context with
up-to-date information from the internet.
"""
from __future__ import annotations

import os
from typing import Optional

import boto3
import structlog

log = structlog.get_logger(__name__)

AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
KB_ID = os.getenv("BEDROCK_KB_ID", "")
MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
MAX_RESULTS = int(os.getenv("RAG_MAX_RESULTS", "5"))
MCP_SEARCH_RESULTS = int(os.getenv("MCP_SEARCH_RESULTS", "3"))
MCP_ENABLED = os.getenv("MCP_BROWSER_FUNCTION_NAME", "pipeline-doctor-mcp-browser-v2") != ""


class RAGRetriever:
    """
    Combines three context sources for pipeline failure diagnosis:
      1. Bedrock Knowledge Base (local runbooks + policies)
      2. MCP web search (live internet search via Brave)
      3. MCP fetch (targeted URL content retrieval)
    """

    def __init__(self, knowledge_base_id: Optional[str] = None, region: Optional[str] = None):
        self.kb_id = knowledge_base_id or KB_ID
        self.region = region or AWS_REGION
        self._client = None  # lazy init
        # Lazy-init MCP client so it doesn't fail if MCP isn't configured
        self._mcp: Optional[object] = None

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client("bedrock-agent-runtime", region_name=self.region)
        return self._client

    def _get_mcp(self):
        """Lazy-init the MCP browser client."""
        if self._mcp is None:
            from agent.mcp_client import MCPBrowserClient
            self._mcp = MCPBrowserClient()
        return self._mcp

    def retrieve(self, query: str, max_results: int = MAX_RESULTS) -> list[str]:
        """
        Retrieve relevant text chunks from the Knowledge Base.
        Returns an empty list if the KB is not configured.
        """
        if not self.kb_id:
            log.warning("rag_kb_id_not_set", msg="BEDROCK_KB_ID not configured; skipping RAG")
            return []

        try:
            response = self._get_client().retrieve(
                knowledgeBaseId=self.kb_id,
                retrievalQuery={"text": query},
                retrievalConfiguration={
                    "vectorSearchConfiguration": {
                        "numberOfResults": max_results,
                    }
                },
            )
            results = response.get("retrievalResults", [])
            passages = [
                r["content"]["text"]
                for r in results
                if r.get("content", {}).get("text")
            ]
            log.info("rag_retrieved", query_preview=query[:80], count=len(passages))
            return passages

        except Exception as exc:
            log.error("rag_retrieve_error", error=str(exc))
            return []

    def ask(self, question: str) -> str:
        """Use retrieve-and-generate to get a grounded answer."""
        if not self.kb_id:
            return "Knowledge base not configured."

        try:
            response = self._get_client().retrieve_and_generate(
                input={"text": question},
                retrieveAndGenerateConfiguration={
                    "type": "KNOWLEDGE_BASE",
                    "knowledgeBaseConfiguration": {
                        "knowledgeBaseId": self.kb_id,
                        "modelArn": f"arn:aws:bedrock:{self.region}::foundation-model/{MODEL_ID}",
                        "retrievalConfiguration": {
                            "vectorSearchConfiguration": {
                                "numberOfResults": MAX_RESULTS,
                            }
                        },
                    },
                },
            )
            return response.get("output", {}).get("text", "No answer found.")
        except Exception as exc:
            log.error("rag_ask_error", error=str(exc))
            return f"RAG error: {exc}"

    def build_context_for_failure(
        self,
        error_message: str,
        category: str,
        stage: str,
    ) -> list[str]:
        """
        Build context from all available sources and return merged passages:
          1. Bedrock Knowledge Base (local runbooks)
          2. MCP web search (live internet results, if configured)
        """
        query = (
            f"How to fix {category} in CI/CD pipeline at stage '{stage}'. "
            f"Error: {error_message[:200]}"
        )

        # Source 1: Bedrock KB (always attempted)
        kb_passages = self.retrieve(query)

        # Source 2: MCP web search (only if MCP_BROWSER_URL is set)
        web_passages = self.web_search(
            query=f"{category} CI/CD error: {error_message[:150]}",
            num_results=MCP_SEARCH_RESULTS,
        )

        all_passages = kb_passages + web_passages
        log.info(
            "context_built",
            kb_count=len(kb_passages),
            web_count=len(web_passages),
            total=len(all_passages),
        )
        return all_passages

    # ------------------------------------------------------------------
    # MCP web search and fetch
    # ------------------------------------------------------------------

    def web_search(self, query: str, num_results: int = MCP_SEARCH_RESULTS) -> list[str]:
        """
        Search the internet via the MCP Browser Lambda.
        Returns an empty list silently if MCP is not configured.
        """
        if not MCP_ENABLED:
            log.debug("mcp_web_search_skipped", reason="MCP_BROWSER_URL not set")
            return []
        try:
            results = self._get_mcp().web_search(query, num_results=num_results)
            log.info("mcp_web_search_done", query_preview=query[:80], count=len(results))
            return results
        except Exception as exc:
            log.warning("mcp_web_search_failed", error=str(exc))
            return []

    def fetch_url(self, url: str) -> str:
        """
        Fetch the content of a URL via the MCP Browser Lambda.
        Returns an empty string silently if MCP is not configured.
        """
        if not MCP_ENABLED:
            log.debug("mcp_fetch_skipped", reason="MCP_BROWSER_URL not set")
            return ""
        try:
            content = self._get_mcp().fetch(url)
            log.info("mcp_fetch_done", url=url, length=len(content))
            return content
        except Exception as exc:
            log.warning("mcp_fetch_failed", url=url, error=str(exc))
            return ""
