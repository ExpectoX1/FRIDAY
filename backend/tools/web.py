import os
from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()
print(os.getenv("TAVILY_API_KEY"))
client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


def search_web(query: str) -> str:
    try:
        response = client.search(
            query=query,
            search_depth="basic",
            max_results=5,
            include_answer=True,  # Tavily generates a summary
        )

        # use Tavily's answer if available
        answer = response.get("answer")
        if answer:
            return answer

        # fallback to raw results
        results = response.get("results", [])
        if not results:
            return "No results found Sir."

        summary = ""
        for r in results[:3]:
            summary += f"{r['title']}: {r['content'][:150]}\n\n"

        return summary.strip()
    except Exception as e:
        return f"Search failed: {e}"
