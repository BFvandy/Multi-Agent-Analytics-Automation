"""
Web search tool using Serper.dev API.
Returns top search results for a given query.
"""

import os
import json
import http.client
from dotenv import load_dotenv

load_dotenv()

SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")


def web_search(query: str, num_results: int = 5) -> str:
    """
    Search the web using Serper.dev and return top results.
    Use this to find external factors, news, and context explaining spend trends.

    Args:
        query: Search query string
        num_results: Number of results to return (default 5)

    Returns:
        JSON string with search results including title, snippet, and link
    """
    if not SERPER_API_KEY:
        return json.dumps({"error": "SERPER_API_KEY not set in .env"})

    try:
        conn = http.client.HTTPSConnection("google.serper.dev")
        payload = json.dumps({"q": query, "num": num_results})
        headers = {
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json"
        }
        conn.request("POST", "/search", payload, headers)
        res = conn.getresponse()
        data = json.loads(res.read().decode("utf-8"))

        # Extract clean results
        results = []
        for item in data.get("organic", [])[:num_results]:
            results.append({
                "title":   item.get("title", ""),
                "snippet": item.get("snippet", ""),
                "link":    item.get("link", ""),
                "date":    item.get("date", ""),
            })

        return json.dumps({
            "query":        query,
            "result_count": len(results),
            "results":      results,
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e), "query": query})
