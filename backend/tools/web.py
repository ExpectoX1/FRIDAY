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

        answer = response.get("answer")
        results = response.get("results", [])

        output = ""
        if answer:
            output += f"Summary: {answer}\n\n"

        if results:
            output += "Top Search Results & URLs:\n"
            for r in results[:3]:
                output += f"- {r['title']}: {r['content'][:150]} (URL: {r['url']})\n\n"

        if not output.strip():
            return "No results found Sir."

        return output.strip()
    except Exception as e:
        return f"Search failed: {e}"
