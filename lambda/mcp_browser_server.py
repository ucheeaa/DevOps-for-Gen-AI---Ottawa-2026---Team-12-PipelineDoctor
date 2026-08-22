"""
MCP Browser Server — Lambda Function

Implements the Model Context Protocol (MCP) over HTTP/JSON, exposing two tools:

  fetch        — Download a URL and return the text content
  web_search   — Search the web via Brave Search API and return result snippets

Protocol:
  POST /          body: {"jsonrpc":"2.0","id":"1","method":"tools/list"}
  POST /          body: {"jsonrpc":"2.0","id":"2","method":"tools/call",
                          "params":{"name":"fetch","arguments":{"url":"..."}}}

This Lambda is deployed with a Function URL (auth: AWS_IAM) so that only
the Pipeline Doctor Lambda (via SigV4) can call it.

Environment variables:
  BRAVE_API_KEY          — Brave Search subscription key (get free at brave.com/search/api/)
  FETCH_MAX_BYTES        — Max response body to return (default 32768)
  SEARCH_MAX_RESULTS     — Max search results to return (default 5)
  USER_AGENT             — HTTP User-Agent header for fetch requests
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.error
import urllib.parse
from typing import Any

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BRAVE_API_KEY = os.getenv("BRAVE_API_KEY", "")
FETCH_MAX_BYTES = int(os.getenv("FETCH_MAX_BYTES", "32768"))   # 32 KB default
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))
USER_AGENT = os.getenv(
    "USER_AGENT",
    "Mozilla/5.0 (compatible; PipelineDoctor/1.0; +https://github.com/pipeline-doctor)",
)

# ---------------------------------------------------------------------------
# MCP tool schemas
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "fetch",
        "description": (
            "Fetch the content of a URL and return the text. "
            "Useful for reading documentation pages, GitHub issues, Stack Overflow answers, "
            "error reports, and any web resource reachable via HTTP/HTTPS."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The full URL to fetch (must start with http:// or https://)",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes of content to return (default 32768)",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": (
            "Search the internet using Brave Search and return a list of result titles, "
            "URLs, and description snippets. Use this to find relevant documentation, "
            "GitHub issues, Stack Overflow threads, or CVE reports for a pipeline error."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string",
                },
                "num_results": {
                    "type": "integer",
                    "description": f"Number of results to return (default {SEARCH_MAX_RESULTS}, max 10)",
                },
            },
            "required": ["query"],
        },
    },
]

# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------

def handler(event: dict[str, Any], context: Any) -> dict:
    """
    Handles both:
      - API Gateway v2 / Function URL  (event has "body" key)
      - Direct Lambda invocation        (event IS the JSON-RPC payload)
    """
    # Unwrap API Gateway / Function URL envelope
    if "body" in event:
        raw_body = event["body"]
        if isinstance(raw_body, str):
            try:
                rpc = json.loads(raw_body)
            except json.JSONDecodeError:
                return _http_response(400, _error_response(None, -32700, "Parse error"))
        else:
            rpc = raw_body
    else:
        rpc = event  # direct invocation

    response_body = _dispatch(rpc)

    # If the caller is API Gateway / Function URL, wrap in HTTP response
    if "body" in event or "requestContext" in event:
        return _http_response(200, response_body)

    # Direct invocation — return JSON-RPC body directly
    return response_body


# ---------------------------------------------------------------------------
# JSON-RPC dispatcher
# ---------------------------------------------------------------------------

def _dispatch(rpc: dict) -> dict:
    rpc_id = rpc.get("id")
    method = rpc.get("method", "")
    params = rpc.get("params", {})

    if method == "tools/list":
        return _success_response(rpc_id, {"tools": TOOLS})

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        return _call_tool(rpc_id, tool_name, arguments)

    if method == "initialize":
        # MCP handshake — acknowledge and return server capabilities
        return _success_response(rpc_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "pipeline-doctor-browser", "version": "1.0.0"},
        })

    return _error_response(rpc_id, -32601, f"Method not found: {method}")


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _call_tool(rpc_id: Any, name: str, arguments: dict) -> dict:
    try:
        if name == "fetch":
            result_text = _tool_fetch(
                url=arguments["url"],
                max_bytes=int(arguments.get("max_bytes", FETCH_MAX_BYTES)),
            )
        elif name == "web_search":
            result_text = _tool_web_search(
                query=arguments["query"],
                num_results=int(arguments.get("num_results", SEARCH_MAX_RESULTS)),
            )
        else:
            return _error_response(rpc_id, -32602, f"Unknown tool: {name}")

        return _success_response(rpc_id, {
            "content": [{"type": "text", "text": result_text}],
            "isError": False,
        })

    except KeyError as exc:
        return _error_response(rpc_id, -32602, f"Missing required argument: {exc}")
    except Exception as exc:
        return _success_response(rpc_id, {
            "content": [{"type": "text", "text": f"Error: {exc}"}],
            "isError": True,
        })


def _tool_fetch(url: str, max_bytes: int = FETCH_MAX_BYTES) -> str:
    """Fetch a URL and return cleaned text content."""
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL must start with http:// or https://, got: {url!r}")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read(max_bytes)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} fetching {url}: {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to reach {url}: {exc.reason}") from exc

    # Decode
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=")[-1].split(";")[0].strip()
    try:
        text = raw.decode(charset, errors="replace")
    except (LookupError, UnicodeDecodeError):
        text = raw.decode("utf-8", errors="replace")

    # Strip HTML tags for cleaner output
    if "html" in content_type.lower():
        text = _strip_html(text)

    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    truncated = len(raw) >= max_bytes
    suffix = f"\n\n[Content truncated at {max_bytes} bytes]" if truncated else ""
    return text + suffix


def _tool_web_search(query: str, num_results: int = SEARCH_MAX_RESULTS) -> str:
    """
    Search the web and return formatted results.

    Priority:
      1. Brave Search API  (if BRAVE_API_KEY is set)
      2. DuckDuckGo Instant Answer API  (free, no key required)
    """
    if BRAVE_API_KEY:
        return _search_brave(query, num_results)
    return _search_duckduckgo(query, num_results)


def _search_brave(query: str, num_results: int) -> str:
    """Search using the Brave Search API."""
    num_results = min(num_results, 10)
    search_url = (
        f"https://api.search.brave.com/res/v1/web/search"
        f"?q={urllib.parse.quote_plus(query)}&count={num_results}&search_lang=en"
    )
    req = urllib.request.Request(
        search_url,
        headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Brave Search API error: {exc}") from exc

    web_results = data.get("web", {}).get("results", [])
    if not web_results:
        return f"No results found for: {query}"

    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(web_results[:num_results], 1):
        title = r.get("title", "No title")
        url = r.get("url", "")
        desc = r.get("description", "No description")
        lines.append(f"{i}. {title}\n   URL: {url}\n   {desc}\n")
    return "\n".join(lines)


def _search_duckduckgo(query: str, num_results: int) -> str:
    """
    Search by scraping DuckDuckGo HTML results — no API key required.
    Works for any query including technical developer searches.

    Uses the DuckDuckGo HTML endpoint (html.duckduckgo.com) which returns
    a plain HTML page that is much easier to parse than the JS-rendered one.
    Falls back to the Lite endpoint if HTML parsing yields nothing.
    """
    num_results = min(num_results, 10)
    encoded_query = urllib.parse.quote_plus(query)

    # Try the HTML endpoint first — returns <a class="result__a"> links
    html_url = f"https://html.duckduckgo.com/html/?q={encoded_query}&kl=us-en"
    req = urllib.request.Request(
        html_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "identity",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://duckduckgo.com/",
            "Cookie": "kl=us-en; s=0; dc=1",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read(65536).decode("utf-8", errors="replace")
    except Exception as exc:
        raise RuntimeError(f"DuckDuckGo HTML search error: {exc}") from exc

    results = _parse_ddg_html(html, num_results)

    if results:
        lines = [f"Search results for: {query}\n"]
        for i, (title, url, snippet) in enumerate(results, 1):
            lines.append(f"{i}. {title}\n   URL: {url}\n   {snippet}\n")
        return "\n".join(lines)

    # Fallback: DuckDuckGo Lite (even simpler HTML)
    try:
        lite_url = f"https://lite.duckduckgo.com/lite/?q={encoded_query}"
        req2 = urllib.request.Request(
            lite_url,
            headers={"User-Agent": "Mozilla/5.0", "Accept": "text/html"},
        )
        with urllib.request.urlopen(req2, timeout=12) as resp2:
            html2 = resp2.read(32768).decode("utf-8", errors="replace")
        results2 = _parse_ddg_lite(html2, num_results)
        if results2:
            lines = [f"Search results for: {query}\n"]
            for i, (title, url, snippet) in enumerate(results2, 1):
                lines.append(f"{i}. {title}\n   URL: {url}\n   {snippet}\n")
            return "\n".join(lines)
    except Exception:
        pass

    # Final fallback — useful links for the agent to follow up with fetch()
    return (
        f"Search results for: {query}\n\n"
        f"Direct search links (use fetch() to retrieve):\n"
        f"  https://duckduckgo.com/?q={encoded_query}\n"
        f"  https://stackoverflow.com/search?q={encoded_query}\n"
        f"  https://github.com/search?q={encoded_query}&type=issues\n"
        f"  https://pypi.org/search/?q={encoded_query}"
    )


def _parse_ddg_html(html: str, num_results: int) -> list[tuple[str, str, str]]:
    """
    Parse DuckDuckGo HTML search results page.
    Returns list of (title, url, snippet) tuples.
    """
    results = []

    # Each result block: <div class="result ..."> ... </div>
    # Title link: <a class="result__a" href="...">Title</a>
    # Snippet:    <a class="result__snippet">...</a>
    # DDG wraps outbound URLs in a redirect; extract the real URL from
    # the uddg= query parameter if present.

    title_pattern = re.compile(
        r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    snippet_pattern = re.compile(
        r'class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    titles = title_pattern.findall(html)
    snippets = [m.group(1) for m in snippet_pattern.finditer(html)]

    for i, (raw_url, raw_title) in enumerate(titles[:num_results]):
        title = _clean_text(raw_title)
        snippet = _clean_text(snippets[i]) if i < len(snippets) else ""

        # Decode DDG redirect URL → real URL
        url = _decode_ddg_url(raw_url)

        if title and url:
            results.append((title, url, snippet))

    return results


def _parse_ddg_lite(html: str, num_results: int) -> list[tuple[str, str, str]]:
    """
    Parse DuckDuckGo Lite results page (simpler markup).
    Result links appear as <a class="result-link" href="...">Title</a>
    followed by a <td class="result-snippet">snippet</td>.
    """
    results = []
    link_pattern = re.compile(
        r'class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )
    snippet_pattern = re.compile(
        r'class="result-snippet"[^>]*>(.*?)</td>',
        re.DOTALL | re.IGNORECASE,
    )

    links = link_pattern.findall(html)
    snippets = [m.group(1) for m in snippet_pattern.finditer(html)]

    for i, (raw_url, raw_title) in enumerate(links[:num_results]):
        title = _clean_text(raw_title)
        snippet = _clean_text(snippets[i]) if i < len(snippets) else ""
        url = _decode_ddg_url(raw_url)
        if title and url:
            results.append((title, url, snippet))

    return results


def _decode_ddg_url(raw_url: str) -> str:
    """Extract the real destination URL from a DuckDuckGo redirect."""
    if "uddg=" in raw_url:
        try:
            qs = urllib.parse.urlparse(raw_url).query
            params = urllib.parse.parse_qs(qs)
            uddg = params.get("uddg", [""])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
        except Exception:
            pass
    if raw_url.startswith("//"):
        return "https:" + raw_url
    return raw_url


def _clean_text(html_fragment: str) -> str:
    """Strip tags and collapse whitespace from an HTML fragment."""
    text = re.sub(r"<[^>]+>", " ", html_fragment)
    entities = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&nbsp;": " ", "&apos;": "'",
        "&#x27;": "'", "&#x2F;": "/", "&#x60;": "`", "&#x3D;": "=",
    }
    for ent, ch in entities.items():
        text = text.replace(ent, ch)
    # Also handle decimal numeric entities like &#123;
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# HTML stripper (no external deps — stdlib only)
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
    """Remove HTML tags and decode common entities."""
    # Remove <script> and <style> blocks entirely
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining tags
    html = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities
    entities = {
        "&amp;": "&", "&lt;": "<", "&gt;": ">",
        "&quot;": '"', "&#39;": "'", "&nbsp;": " ",
        "&apos;": "'",
    }
    for entity, char in entities.items():
        html = html.replace(entity, char)
    # Collapse whitespace
    html = re.sub(r"[ \t]+", " ", html)
    return html


# ---------------------------------------------------------------------------
# JSON-RPC helpers
# ---------------------------------------------------------------------------

def _success_response(rpc_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _error_response(rpc_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _http_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
