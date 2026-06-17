from google.adk.agents import LlmAgent

CODE_REVIEW_AGENT = LlmAgent(
    name="CodeReviewAgent",
    model="gemini-2.5-flash",
    description="Reviews code samples for bugs, style issues, and improvement opportunities.",
    instruction=(
        "Review the provided code. Identify: bugs, security issues, style violations, "
        "and improvement opportunities. Be specific and actionable."
    ),
)

CODE_REVIEW_CAPABILITIES = ["code_review", "code_analysis", "lint"]


async def code_review_health_check() -> bool:
    return True
