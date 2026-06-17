from google.adk.agents import LlmAgent
from agent_mesh.tools import list_healthy

ROUTER_INSTRUCTION = """
You are a task router for the Agent Mesh platform.

Your job:
1. Call list_healthy() to see what specialist agents are available and their capabilities.
2. Analyze the user's task and determine which capabilities are needed.
3. Decompose the task into subtasks, one per required capability.
4. Write your decomposition to session state as key "task_decomposition" in this exact JSON format:
   {
     "original_task": "<the user's original request>",
     "subtasks": [
       {"capability": "<cap>", "agent_name": "<name>", "instruction": "<specific instruction for this agent>"},
       ...
     ]
   }
5. If a required capability has no healthy agent, include it in the decomposition with agent_name "UNAVAILABLE".

IMPORTANT: Only include subtasks for capabilities that are genuinely needed.
Do not fabricate capabilities or agents not in the list_healthy() response.
"""


def build_router_agent(model: str = "gemini-2.5-flash") -> LlmAgent:
    return LlmAgent(
        name="RouterAgent",
        model=model,
        description="Decomposes tasks and routes them to available specialist agents.",
        instruction=ROUTER_INSTRUCTION,
        tools=[list_healthy],
        output_key="task_decomposition",
    )
