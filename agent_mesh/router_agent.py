from google.adk.agents import LlmAgent
from agent_mesh.tools import list_all_agents

ROUTER_INSTRUCTION = """
You are a task router for the Agent Mesh platform.

Your job:
1. Call list_all_agents() to see ALL registered specialist agents, their capabilities, and their status.
2. Analyze the user's task and determine which capabilities are needed.
3. Decompose the task into subtasks, one per required capability.
4. Output ONLY valid JSON in this exact format — no preamble, no markdown fences, no tool calls:
   {
     "original_task": "<the user's original request>",
     "subtasks": [
       {"capability": "<cap>", "agent_name": "<name or UNAVAILABLE>", "instruction": "<specific instruction for this agent>"},
       ...
     ]
   }
5. For each needed capability: if the agent's status is "offline", set agent_name to "UNAVAILABLE".
   Use the exact capability string from the agent's capabilities list.

IMPORTANT: Only include subtasks for capabilities that are genuinely needed.
Do not fabricate capabilities or agents not in the list_all_agents() response.
Do NOT call any tool to write output — just output the JSON directly as your final response.
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
