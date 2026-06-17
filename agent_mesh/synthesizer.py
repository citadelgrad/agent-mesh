from google.adk.agents import LlmAgent
from agent_mesh.models import MeshResponse

SYNTHESIZER_INSTRUCTION = """
You are the response synthesizer for the Agent Mesh platform.

Session state contains results from specialist agents under keys starting with "result_".
Each result is a JSON SpecialistResult with fields: agent_name, capability, output, success, error.

Also check "unavailable_capabilities" in session state for capabilities that had no healthy agent.

Your job:
1. Read all result_* keys from session state.
2. Synthesize a single, coherent answer to the user's original task.
3. List the agent names that contributed (sources).
4. Set partial=true if ANY of these apply:
   - No result_* keys exist in session state (nothing was dispatched)
   - Any specialist result had success=false
   - unavailable_capabilities in session state is non-empty
5. List all unavailable_capabilities from session state.

Return ONLY valid JSON matching the MeshResponse schema. No preamble, no markdown fences.
"""


def build_synthesizer_agent(model: str = "gemini-2.5-flash") -> LlmAgent:
    return LlmAgent(
        name="SynthesizerAgent",
        model=model,
        description="Assembles parallel specialist results into a final structured response.",
        instruction=SYNTHESIZER_INSTRUCTION,
        output_schema=MeshResponse,
        output_key="mesh_response",
    )
