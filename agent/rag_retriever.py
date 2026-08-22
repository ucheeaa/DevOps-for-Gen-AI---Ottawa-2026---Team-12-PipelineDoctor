"""
RAG Retriever - Queries the Bedrock Knowledge Base for relevant runbooks,
documentation, and previous incident reports.
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


class RAGRetriever:
    """
    Wraps the Bedrock Knowledge Base retrieve and retrieve-and-generate APIs.
    """

    def __init__(self, knowledge_base_id: Optional[str] = None, region: Optional[str] = None):
        self.kb_id = knowledge_base_id or KB_ID
        self.region = region or AWS_REGION
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client("bedrock-agent-runtime", region_name=self.region)
        return self._client

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
        """Build a targeted query from failure details and return retrieved passages."""
        query = (
            f"How to fix {category} in CI/CD pipeline at stage '{stage}'. "
            f"Error: {error_message[:200]}"
        )
        return self.retrieve(query)
