from agent_mesh.registry import CapabilityRegistry
from agent_mesh.specialists.web_search import WEB_SEARCH_AGENT, WEB_SEARCH_CAPABILITIES, web_search_health_check
from agent_mesh.specialists.summarizer import SUMMARIZER_AGENT, SUMMARIZER_CAPABILITIES, summarizer_health_check
from agent_mesh.specialists.code_review import CODE_REVIEW_AGENT, CODE_REVIEW_CAPABILITIES, code_review_health_check


async def register_all_specialists(registry: CapabilityRegistry) -> None:
    await registry.register("WebSearchAgent", WEB_SEARCH_AGENT.description, WEB_SEARCH_CAPABILITIES, web_search_health_check)
    await registry.register("SummarizerAgent", SUMMARIZER_AGENT.description, SUMMARIZER_CAPABILITIES, summarizer_health_check)
    await registry.register("CodeReviewAgent", CODE_REVIEW_AGENT.description, CODE_REVIEW_CAPABILITIES, code_review_health_check)


__all__ = [
    "register_all_specialists",
    "WEB_SEARCH_AGENT", "WEB_SEARCH_CAPABILITIES", "web_search_health_check",
    "SUMMARIZER_AGENT", "SUMMARIZER_CAPABILITIES", "summarizer_health_check",
    "CODE_REVIEW_AGENT", "CODE_REVIEW_CAPABILITIES", "code_review_health_check",
]
