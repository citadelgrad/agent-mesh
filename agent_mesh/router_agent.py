from google.adk.agents import LlmAgent
from agent_mesh.tools import list_all_agents

ROUTER_INSTRUCTION = """
You are a task router for the Agent Mesh platform.

Your job:
1. Call list_all_agents() to see all available specialist agents and their capabilities.
2. Analyze the user's task and determine which capabilities are needed.
3. Decompose into subtasks — one per needed capability. Emit ONE subtask when a single
   capability fully answers the task; emit multiple only when the task genuinely spans
   several capabilities.
4. Output ONLY valid JSON in this exact format — no preamble, no markdown fences, no tool calls:
   {
     "original_task": "<the user's original request>",
     "subtasks": [
       {"capability": "<cap>", "agent_name": "<agent name>", "instruction": "<specific instruction>"},
       ...
     ]
   }

IMPORTANT:
- Use the exact capability string from the agent's capabilities list.
- Only include subtasks for capabilities genuinely needed by this task.
- Do not fabricate capabilities or agents not in the list_all_agents() response.
- Do NOT call any tool to write output — output the JSON directly as your final response.
"""


def build_router_agent(model: str = "gemini-2.5-flash") -> LlmAgent:
    return LlmAgent(
        name="RouterAgent",
        model=model,
        description="Decomposes tasks and routes them to available specialist agents.",
        instruction=ROUTER_INSTRUCTION,
        tools=[list_all_agents],
        output_key="task_decomposition",
    )
