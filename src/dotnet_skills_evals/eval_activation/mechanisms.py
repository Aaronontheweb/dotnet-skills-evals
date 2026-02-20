"""Discovery mechanism implementations using raw LiteLLM calls.

Three mechanisms for how a model discovers available skills:
1. Tool-based: model gets a Skill tool it can call (mirrors Claude Code)
2. Compressed index: routing snippet in system prompt
3. Fat index: all skill names + descriptions in system prompt
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import litellm

from ..skills.loader import Skill
from .detection import detect_skill_references


SYSTEM_PROMPT = (
    "You are a .NET development assistant. You help developers write "
    "high-quality C# and .NET code with working examples and clear "
    "explanations. Focus on modern .NET practices (.NET 8+, C# 12+)."
)


@dataclass
class MechanismResult:
    """Result from a single mechanism invocation."""

    activated: bool
    activated_skills: list[str]
    response_text: str
    prompt_tokens: int
    completion_tokens: int


class DiscoveryMechanism(ABC):
    """Base class for skill discovery mechanisms."""

    name: str

    @abstractmethod
    def run(
        self, task: str, model: str, api_key: str, api_base: str
    ) -> MechanismResult:
        ...


class ToolBasedDiscovery(DiscoveryMechanism):
    """Simulates Claude Code's Skill tool.

    The model gets a tool definition listing all available skills.
    If it calls the tool, we return the full SKILL.md content and
    let the model continue its response.
    """

    name = "tool"

    def __init__(self, skills: list[Skill]):
        self.skill_map = {s.metadata.name: s for s in skills}
        self.all_skill_names = list(self.skill_map.keys())

        # Build the tool description with all skill names
        skill_list = "\n".join(
            f"  - {s.metadata.name}: {s.metadata.description}"
            for s in skills
        )
        self.tool_definition = {
            "type": "function",
            "function": {
                "name": "invoke_skill",
                "description": (
                    "Look up a .NET development skill by exact name to get "
                    "detailed guidance and code patterns.\n\n"
                    f"Available skills:\n{skill_list}"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "skill_name": {
                            "type": "string",
                            "description": "The exact skill name to look up.",
                        }
                    },
                    "required": ["skill_name"],
                },
            },
        }

    def run(
        self, task: str, model: str, api_key: str, api_base: str
    ) -> MechanismResult:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": task},
        ]

        total_prompt_tokens = 0
        total_completion_tokens = 0
        activated_skills = []

        # Initial call with tool
        response = litellm.completion(
            model=model,
            messages=messages,
            tools=[self.tool_definition],
            api_key=api_key,
            api_base=api_base,
            temperature=0.0,
        )

        total_prompt_tokens += response.usage.prompt_tokens
        total_completion_tokens += response.usage.completion_tokens

        choice = response.choices[0]

        # Handle tool calls (may need multiple rounds)
        max_rounds = 3
        round_count = 0
        while (
            choice.finish_reason == "tool_calls"
            and choice.message.tool_calls
            and round_count < max_rounds
        ):
            round_count += 1
            # Add assistant message with tool calls
            messages.append(choice.message.model_dump())

            # Process each tool call
            for tool_call in choice.message.tool_calls:
                if tool_call.function.name == "invoke_skill":
                    args = json.loads(tool_call.function.arguments)
                    skill_name = args.get("skill_name", "")
                    activated_skills.append(skill_name)

                    # Return skill content or error
                    if skill_name in self.skill_map:
                        content = self.skill_map[skill_name].full_content
                    else:
                        content = (
                            f"Unknown skill: {skill_name}. "
                            f"Available: {', '.join(self.all_skill_names)}"
                        )

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": content,
                    })

            # Continue conversation
            response = litellm.completion(
                model=model,
                messages=messages,
                tools=[self.tool_definition],
                api_key=api_key,
                api_base=api_base,
                temperature=0.0,
            )

            total_prompt_tokens += response.usage.prompt_tokens
            total_completion_tokens += response.usage.completion_tokens
            choice = response.choices[0]

        response_text = choice.message.content or ""

        return MechanismResult(
            activated=len(activated_skills) > 0,
            activated_skills=activated_skills,
            response_text=response_text,
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
        )


class CompressedIndexDiscovery(DiscoveryMechanism):
    """Injects compressed routing index into the system prompt.

    The model sees the terse Vercel-style routing snippet (~15 lines)
    as part of its system context. No tool available.
    """

    name = "compressed"

    def __init__(self, compressed_index: str, all_skill_names: list[str]):
        self.compressed_index = compressed_index
        self.all_skill_names = all_skill_names

    def run(
        self, task: str, model: str, api_key: str, api_base: str
    ) -> MechanismResult:
        system_content = (
            f"{SYSTEM_PROMPT}\n\n"
            f"The following development skills and resources are available "
            f"in this workspace:\n\n{self.compressed_index}"
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": task},
        ]

        response = litellm.completion(
            model=model,
            messages=messages,
            api_key=api_key,
            api_base=api_base,
            temperature=0.0,
        )

        response_text = response.choices[0].message.content or ""
        activated_skills = detect_skill_references(
            response_text, self.all_skill_names
        )

        return MechanismResult(
            activated=len(activated_skills) > 0,
            activated_skills=activated_skills,
            response_text=response_text,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )


class FatIndexDiscovery(DiscoveryMechanism):
    """Injects full skill catalog (names + descriptions) into the system prompt.

    The model sees all 31 skill names with their full description strings.
    No tool available.
    """

    name = "fat"

    def __init__(self, skill_catalog: str, all_skill_names: list[str]):
        self.skill_catalog = skill_catalog
        self.all_skill_names = all_skill_names

    def run(
        self, task: str, model: str, api_key: str, api_base: str
    ) -> MechanismResult:
        system_content = (
            f"{SYSTEM_PROMPT}\n\n"
            f"The following development skills and resources are available "
            f"in this workspace:\n\n{self.skill_catalog}"
        )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": task},
        ]

        response = litellm.completion(
            model=model,
            messages=messages,
            api_key=api_key,
            api_base=api_base,
            temperature=0.0,
        )

        response_text = response.choices[0].message.content or ""
        activated_skills = detect_skill_references(
            response_text, self.all_skill_names
        )

        return MechanismResult(
            activated=len(activated_skills) > 0,
            activated_skills=activated_skills,
            response_text=response_text,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
        )
