from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests


@dataclass
class LlmConfig:
    enabled: bool
    use_legacy_interface: bool
    provider: str
    endpoint: str
    api_key: str
    model: str
    timeout_seconds: int
    temperature: float
    max_tokens: int
    system_prompt: str
    prompt_template_file: str
    architecture_guide_file: str
    experiment_config_file: str
    num_new_models: int
    num_reference_models: int


class LlmProposalClient:
    def __init__(self, config: LlmConfig) -> None:
        self.config = config

    def generate_candidate(self, context: dict[str, Any]) -> dict[str, Any] | None:
        if not self.config.enabled:
            return None
        if self.config.use_legacy_interface:
            legacy_result = self._generate_with_legacy_interface(context)
            if legacy_result is not None:
                return legacy_result
        provider = self.config.provider.strip().lower()
        if provider == "mock":
            generation = int(context.get("generation", 0))
            metrics = context.get("latest_metrics", {})
            val_loss = float(metrics.get("val_loss_total", 1.0)) if isinstance(metrics, dict) else 1.0
            return {
                "base_model_id": "mock_base_model",
                "proposal": {
                    "layers_delta": {
                        "dense_units": 64 + (generation % 4) * 16,
                        "dropout": round(min(0.5, 0.1 + (val_loss / 2)), 3),
                    },
                    "optimizer_delta": {
                        "learning_rate": round(max(0.0001, 0.001 * (0.95 ** generation)), 6),
                    },
                },
                "llm_metadata": {
                    "provider": "mock",
                    "model": "mock-evolution-v1",
                    "raw_response": {"mode": "mock"},
                },
            }
        return self._generate_openai_compatible(context)

    def _generate_with_legacy_interface(self, context: dict[str, Any]) -> dict[str, Any] | None:
        repo_root = Path(__file__).resolve().parents[3]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        try:
            from utils.llm_interface import ask_openai
            from v2_prompt_builder import V2PromptBuilder
        except Exception:
            return None
        prompt_builder = V2PromptBuilder(
            repo_root=repo_root,
            prompt_template_file=self.config.prompt_template_file,
            architecture_guide_file=self.config.architecture_guide_file,
            experiment_config_file=self.config.experiment_config_file,
            num_new_models=self.config.num_new_models,
            num_reference_models=self.config.num_reference_models,
        )
        prompt_text = prompt_builder.build_prompt(context)
        llm_config = {
            "openai_api_key": self.config.api_key,
            "api_url": self._resolve_endpoint(self.config.endpoint),
            "openai_model_name": self.config.model,
            "system_message": self.config.system_prompt,
            "max_tokens": self.config.max_tokens,
            "temperature": self.config.temperature,
        }
        if llm_config["openai_api_key"] == "":
            env_key = os.getenv("OPENAI_API_KEY", "")
            if env_key != "":
                llm_config["openai_api_key"] = env_key
        if llm_config["openai_api_key"] == "":
            return None
        response_text = ask_openai(
            prompt_text,
            llm_config,
            context_for_log={"task_type": "v2_generate_candidate", "generation_num": context.get("generation")},
        )
        if not response_text:
            raise RuntimeError("Legacy LLM interface returned empty response")
        extracted = self._extract_first_json_payload(str(response_text))
        parsed = json.loads(extracted)
        return self._normalize_candidate_response(parsed, provider="legacy_interface")

    def _generate_openai_compatible(self, context: dict[str, Any]) -> dict[str, Any]:
        if self.config.endpoint.strip() == "":
            raise RuntimeError("LLM endpoint not configured")
        if self.config.api_key.strip() == "":
            raise RuntimeError("LLM api key not configured")
        endpoint = self._resolve_endpoint(self.config.endpoint)
        try:
            from v2_prompt_builder import V2PromptBuilder
            repo_root = Path(__file__).resolve().parents[3]
            prompt_builder = V2PromptBuilder(
                repo_root=repo_root,
                prompt_template_file=self.config.prompt_template_file,
                architecture_guide_file=self.config.architecture_guide_file,
                experiment_config_file=self.config.experiment_config_file,
                num_new_models=self.config.num_new_models,
                num_reference_models=self.config.num_reference_models,
            )
            prompt_text = prompt_builder.build_prompt(context)
        except Exception:
            prompt_text = json.dumps(context, ensure_ascii=False)
        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": prompt_text},
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.config.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        content = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content", "")).strip()
        extracted = self._extract_first_json_payload(content)
        parsed = json.loads(extracted)
        candidate = self._normalize_candidate_response(parsed, provider=self.config.provider)
        metadata = candidate.get("llm_metadata")
        metadata_payload = metadata if isinstance(metadata, dict) else {}
        metadata_payload["raw_response"] = data
        candidate["llm_metadata"] = metadata_payload
        return candidate

    def _resolve_endpoint(self, endpoint: str) -> str:
        trimmed = endpoint.strip().rstrip("/")
        if trimmed == "":
            return "https://api.openai.com/v1/chat/completions"
        if trimmed.endswith("/chat/completions"):
            return trimmed
        return f"{trimmed}/chat/completions"

    def _extract_first_json_payload(self, text: str) -> str:
        object_start = text.find("{")
        array_start = text.find("[")
        starts = [index for index in [object_start, array_start] if index >= 0]
        if not starts:
            raise RuntimeError("LLM response does not contain JSON payload")
        start = min(starts)
        opening = text[start]
        closing = "}" if opening == "{" else "]"
        if opening not in "{[":
            raise RuntimeError("LLM response does not contain JSON payload")
        return self._extract_balanced_payload(text, start, opening, closing)

    def _extract_balanced_payload(self, text: str, start: int, opening: str, closing: str) -> str:
        if start < 0:
            raise RuntimeError("LLM response does not contain JSON payload")
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
                continue
            if char == opening:
                depth += 1
                continue
            if char == closing:
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        raise RuntimeError("LLM JSON payload not closed")

    def _normalize_candidate_response(self, parsed: Any, provider: str) -> dict[str, Any]:
        if isinstance(parsed, list) and parsed:
            first = parsed[0]
            if isinstance(first, dict):
                base_model_id = str(first.get("base_model_id", "")).strip() or "legacy_generated_model"
                return {
                    "base_model_id": base_model_id,
                    "proposal": {"model_definition": first},
                    "llm_metadata": {"provider": provider, "model": self.config.model, "response_format": "list"},
                }
        if isinstance(parsed, dict):
            base_model_id = str(parsed.get("base_model_id", "")).strip()
            proposal = parsed.get("proposal")
            if base_model_id != "" and isinstance(proposal, dict) and len(proposal) > 0:
                return {
                    "base_model_id": base_model_id,
                    "proposal": proposal,
                    "llm_metadata": {"provider": provider, "model": self.config.model, "response_format": "proposal"},
                }
            return {
                "base_model_id": str(parsed.get("model_id", "legacy_generated_model")),
                "proposal": {"model_definition": parsed},
                "llm_metadata": {"provider": provider, "model": self.config.model, "response_format": "model_definition"},
            }
        raise RuntimeError("LLM response is neither JSON object nor JSON list")
