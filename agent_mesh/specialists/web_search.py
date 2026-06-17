from google.adk.agents import LlmAgent
from google.adk.tools import google_search

WEB_SEARCH_AGENT = LlmAgent(
    name="WebSearchAgent",
    model="gemini-2.5-flash",
    description="Performs live web searches and returns summarized results with source URLs.",
    instruction="Search the web for the given query. Return a concise summary with source URLs.",
    tools=[google_search],
)

WEB_SEARCH_CAPABILITIES = ["web_search", "search", "internet_lookup"]


async def web_search_health_check() -> bool:
    return True  # ponytail: stateless — healthy if process is alive
