from google.adk.agents import LlmAgent

SUMMARIZER_AGENT = LlmAgent(
    name="SummarizerAgent",
    model="gemini-2.5-flash",
    description="Summarizes long-form text into concise, structured bullet points.",
    instruction="Summarize the provided text. Be concise. Preserve key facts and source attributions.",
)

SUMMARIZER_CAPABILITIES = ["summarize", "summarization", "condense"]


async def summarizer_health_check() -> bool:
    return True
