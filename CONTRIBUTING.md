# Contributing to HYDRA-UMC-SEMANTIC-PLANNER 🦾

We welcome contributions to the mission orchestrator of the HYDRA-UMC platform.

## Technology Stack
- **Language**: Python 3.12.
- **Hardware**: Hailo-10 M.2 AI Accelerator (40 TOPS).
- **LLM Frameworks**: LangChain, quantized Llama-3/Mistral runners.
- **Protocols**: gRPC for inter-node communication.

## Guidelines
1. **Agentic Determinism**: While using LLMs, ensure that task decomposition leads to deterministic and safe robotic primitives.
2. **Error Recovery Logic**: All proposed recovery strategies must be validated against the robot's physical constraints and tool capabilities.
3. **Response Time**: Reasoning chains should not block real-time safety critical monitoring.
4. **Knowledge Base**: When adding new tool capabilities, update the `knowledge/` Markdown files to allow the planner to reason about them.
