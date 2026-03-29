from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime
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
    fallback_provider: str
    fallback_endpoint: str
    fallback_api_key: str
    fallback_model: str
    timeout_seconds: int
    temperature: float
    max_tokens: int
    system_prompt: str
    prompt_template_file: str
    fix_error_prompt_file: str
    architecture_guide_file: str
    experiment_config_file: str
    num_new_models: int
    num_reference_models: int
    repair_on_validation_error: bool


class LlmRateLimitError(RuntimeError):
    pass


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
        try:
            return self._generate_with_provider(
                context,
                provider_label=self.config.provider,
                endpoint_override=self.config.endpoint,
                api_key_override=self.config.api_key,
                model_override=self.config.model,
            )
        except LlmRateLimitError:
            fallback_endpoint = self.config.fallback_endpoint.strip()
            fallback_api_key = self.config.fallback_api_key.strip()
            fallback_model = self.config.fallback_model.strip()
            fallback_provider = self.config.fallback_provider.strip() or "gemini"
            if fallback_api_key == "" or fallback_model == "":
                raise
            return self._generate_with_provider(
                context,
                provider_label=fallback_provider,
                endpoint_override=fallback_endpoint,
                api_key_override=fallback_api_key,
                model_override=fallback_model,
            )

    def _generate_with_provider(
        self,
        context: dict[str, Any],
        provider_label: str,
        endpoint_override: str,
        api_key_override: str,
        model_override: str,
    ) -> dict[str, Any]:
        normalized_provider = provider_label.strip().lower()
        if "gemini" in normalized_provider:
            return self._generate_gemini_native(
                context,
                provider_label=provider_label,
                endpoint_override=endpoint_override,
                api_key_override=api_key_override,
                model_override=model_override,
            )
        return self._generate_openai_compatible(
            context,
            provider_label=provider_label,
            endpoint_override=endpoint_override,
            api_key_override=api_key_override,
            model_override=model_override,
        )

    def _generate_with_legacy_interface(self, context: dict[str, Any]) -> dict[str, Any] | None:
        from shared.clients.llm_interface import ask_openai  # type: ignore[import]
        from v2_prompt_builder import V2PromptBuilder

        repo_root = Path(__file__).resolve().parents[2]
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
        candidate = self._normalize_candidate_response(parsed, provider="legacy_interface")
        try:
            candidate = self._validate_candidate(candidate)
        except Exception as validation_error:
            repaired = self._repair_candidate_after_validation_error(candidate, str(validation_error), context)
            if repaired is None:
                raise
            candidate = self._validate_candidate(repaired)
        self._attach_prompt_audit_metadata(candidate, context, prompt_text)
        return candidate

    def _generate_openai_compatible(
        self,
        context: dict[str, Any],
        provider_label: str,
        endpoint_override: str,
        api_key_override: str,
        model_override: str,
    ) -> dict[str, Any]:
        if endpoint_override.strip() == "":
            raise RuntimeError("LLM endpoint not configured")
        if api_key_override.strip() == "":
            raise RuntimeError("LLM api key not configured")
        endpoint = self._resolve_endpoint(endpoint_override)
        try:
            from v2_prompt_builder import V2PromptBuilder
            repo_root = Path(__file__).resolve().parents[2]
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
        last_error: Exception | None = None
        attempt_endpoint = endpoint
        data: dict[str, Any] = {}
        content = ""
        base_prompt_text = prompt_text
        repair_suffix = (
            "\n\nIMPORTANT: Your previous answer was not valid JSON. "
            "Return ONLY valid JSON with balanced brackets, double-quoted keys, no markdown fences, "
            "no explanations, and no trailing text before or after the JSON payload."
        )
        for generation_attempt in range(3):
            prompt_text = base_prompt_text if generation_attempt == 0 else (base_prompt_text + repair_suffix)
            attempt_endpoint = endpoint
            use_max_completion_tokens = False
            retries_for_server_error = 2
            retries_for_request_error = 2
            max_tokens_override: int | None = None
            data = {}
            content = ""
            for _ in range(4):
                payload = self._build_payload(attempt_endpoint, prompt_text, use_max_completion_tokens, max_tokens_override, model_override)
                try:
                    response = requests.post(
                        attempt_endpoint,
                        headers={
                            "Authorization": f"Bearer {api_key_override}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                        timeout=self.config.timeout_seconds,
                    )
                except requests.RequestException as error:
                    self._log_openai_attempt(
                        prompt_text=prompt_text,
                        response_data=None,
                        error_message=f"request_exception: {error}",
                        context=context,
                        endpoint=attempt_endpoint,
                        attempt=generation_attempt + 1,
                    )
                    last_error = error
                    if retries_for_request_error > 0:
                        retries_for_request_error -= 1
                        time.sleep(5 + generation_attempt)
                        continue
                    if generation_attempt < 2:
                        time.sleep(2 + generation_attempt)
                        break
                    raise RuntimeError(f"OpenAI request failed: {error}") from error
                if response.status_code >= 400:
                    error_payload = {}
                    try:
                        error_payload = response.json()
                    except Exception:
                        error_payload = {}
                    error = error_payload.get("error", {}) if isinstance(error_payload, dict) else {}
                    error_message = str(error.get("message", "") or "")
                    error_code = str(error.get("code", "") or "")
                    is_chat_endpoint = attempt_endpoint.endswith("/chat/completions")
                    if is_chat_endpoint and "not a chat model" in error_message.lower():
                        attempt_endpoint = "https://api.openai.com/v1/completions"
                        continue
                    if error_code == "unsupported_parameter" and "max_tokens" in error_message and not use_max_completion_tokens:
                        use_max_completion_tokens = True
                        continue
                    if response.status_code == 429 or error_code == "rate_limit_exceeded":
                        self._log_openai_attempt(
                            prompt_text=prompt_text,
                            response_data=error_payload if isinstance(error_payload, dict) else {"raw_text": response.text[:2000]},
                            error_message=f"rate_limit_status={response.status_code}",
                            context=context,
                            endpoint=attempt_endpoint,
                            attempt=generation_attempt + 1,
                        )
                        raise LlmRateLimitError(f"OpenAI rate limit reached: {error_message or response.text[:500]}")
                    if response.status_code >= 500 and retries_for_server_error > 0:
                        self._log_openai_attempt(
                            prompt_text=prompt_text,
                            response_data=error_payload if isinstance(error_payload, dict) else {"raw_text": response.text[:2000]},
                            error_message=f"server_error_status={response.status_code}",
                            context=context,
                            endpoint=attempt_endpoint,
                            attempt=generation_attempt + 1,
                        )
                        retries_for_server_error -= 1
                        time.sleep(1.5)
                        continue
                    response.raise_for_status()
                data = response.json()
                content = self._extract_content_from_response(data, attempt_endpoint)
                if content == "":
                    choices = data.get("choices") if isinstance(data, dict) else None
                    first_choice = choices[0] if isinstance(choices, list) and len(choices) > 0 and isinstance(choices[0], dict) else {}
                    finish_reason = str(first_choice.get("finish_reason", "") or "")
                    if finish_reason == "length":
                        self._log_openai_attempt(
                            prompt_text=prompt_text,
                            response_data=data,
                            error_message=f"empty_content_finish_reason=length current_max={max_tokens_override or self.config.max_tokens}",
                            context=context,
                            endpoint=attempt_endpoint,
                            attempt=generation_attempt + 1,
                        )
                        current_max = max_tokens_override if isinstance(max_tokens_override, int) and max_tokens_override > 0 else int(self.config.max_tokens)
                        increased_cap = max(int(self.config.max_tokens) * 3, 12000)
                        increased_max = min(max(current_max * 2, current_max + 1200), increased_cap)
                        if increased_max > current_max:
                            max_tokens_override = increased_max
                            continue
                try:
                    extracted = self._extract_first_json_payload(content)
                    parsed = json.loads(extracted)
                    candidate = self._normalize_candidate_response(parsed, provider=provider_label)
                    try:
                        candidate = self._validate_candidate(candidate)
                    except Exception as validation_error:
                        repaired = self._repair_candidate_after_validation_error(candidate, str(validation_error), context)
                        if repaired is None:
                            raise
                        candidate = self._validate_candidate(repaired)
                    metadata = candidate.get("llm_metadata")
                    metadata_payload = metadata if isinstance(metadata, dict) else {}
                    metadata_payload["raw_response"] = data
                    candidate["llm_metadata"] = metadata_payload
                    self._attach_prompt_audit_metadata(candidate, context, prompt_text)
                    return candidate
                except (json.JSONDecodeError, RuntimeError) as error:
                    self._log_openai_attempt(
                        prompt_text=prompt_text,
                        response_data=data,
                        error_message=f"parse_or_validation_error: {error}",
                        context=context,
                        endpoint=attempt_endpoint,
                        attempt=generation_attempt + 1,
                    )
                    last_error = error
                    if generation_attempt < 2:
                        time.sleep(2 + generation_attempt)
                        break
                    raise
            if generation_attempt < 2:
                continue
        if content == "":
            choices = data.get("choices") if isinstance(data, dict) else None
            first_choice = choices[0] if isinstance(choices, list) and len(choices) > 0 and isinstance(choices[0], dict) else {}
            finish_reason = first_choice.get("finish_reason", None) if isinstance(first_choice, dict) else None
            raw_preview = json.dumps(data, ensure_ascii=False)[:1200] if isinstance(data, dict) else str(data)[:1200]
            raise RuntimeError(
                f"OpenAI response content is empty (endpoint={attempt_endpoint}, "
                f"finish_reason={finish_reason}, raw_preview={raw_preview})"
            )
        if last_error is not None:
            raise RuntimeError(f"OpenAI generation failed after retries: {last_error}") from last_error
        raise RuntimeError("OpenAI generation failed without candidate after retries")

    def _generate_gemini_native(
        self,
        context: dict[str, Any],
        provider_label: str,
        endpoint_override: str,
        api_key_override: str,
        model_override: str,
    ) -> dict[str, Any]:
        if api_key_override.strip() == "":
            raise RuntimeError("Gemini api key not configured")
        try:
            from v2_prompt_builder import V2PromptBuilder
            repo_root = Path(__file__).resolve().parents[2]
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

        try:
            from google import genai  # type: ignore[import]

            client = genai.Client(api_key=api_key_override)
            response = client.models.generate_content(
                model=model_override,
                contents=prompt_text,
                config={
                    "system_instruction": self.config.system_prompt,
                    "temperature": self.config.temperature,
                    "max_output_tokens": int(self.config.max_tokens),
                },
            )
            content = str(getattr(response, "text", "") or "").strip()
            if content == "":
                raise RuntimeError("Gemini SDK returned empty text response")
            extracted = self._extract_first_json_payload(content)
            parsed = json.loads(extracted)
            candidate = self._normalize_candidate_response(parsed, provider=provider_label)
            candidate = self._validate_candidate(candidate)
            metadata = candidate.get("llm_metadata")
            metadata_payload = metadata if isinstance(metadata, dict) else {}
            metadata_payload["raw_response"] = {"sdk_text_preview": content[:4000]}
            metadata_payload["gemini_transport"] = "google_genai_sdk"
            candidate["llm_metadata"] = metadata_payload
            self._attach_prompt_audit_metadata(candidate, context, prompt_text)
            return candidate
        except ImportError:
            pass

        endpoint = self._resolve_gemini_endpoint(endpoint_override, model_override)
        payload = {
            "system_instruction": {
                "parts": [{"text": self.config.system_prompt}],
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt_text}],
                }
            ],
            "generationConfig": {
                "temperature": self.config.temperature,
                "maxOutputTokens": int(self.config.max_tokens),
            },
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = requests.post(
                    endpoint,
                    params={"key": api_key_override},
                    headers={"Content-Type": "application/json"},
                    json=payload,
                    timeout=self.config.timeout_seconds,
                )
            except requests.RequestException as error:
                last_error = error
                time.sleep(4 + attempt)
                continue

            if response.status_code == 429:
                body_preview = response.text[:500]
                raise LlmRateLimitError(f"Gemini rate limit reached: {body_preview}")
            if response.status_code >= 500 and attempt < 2:
                last_error = RuntimeError(f"Gemini server error {response.status_code}: {response.text[:500]}")
                time.sleep(3 + attempt)
                continue
            response.raise_for_status()
            data = response.json()
            content = self._extract_content_from_gemini_response(data)
            if content.strip() == "":
                last_error = RuntimeError(f"Gemini response content is empty: {json.dumps(data, ensure_ascii=False)[:1200]}")
                continue
            extracted = self._extract_first_json_payload(content)
            parsed = json.loads(extracted)
            candidate = self._normalize_candidate_response(parsed, provider=provider_label)
            candidate = self._validate_candidate(candidate)
            metadata = candidate.get("llm_metadata")
            metadata_payload = metadata if isinstance(metadata, dict) else {}
            metadata_payload["raw_response"] = data
            candidate["llm_metadata"] = metadata_payload
            self._attach_prompt_audit_metadata(candidate, context, prompt_text)
            return candidate

        if last_error is not None:
            raise RuntimeError(f"Gemini generation failed after retries: {last_error}") from last_error
        raise RuntimeError("Gemini generation failed without candidate after retries")

    def _log_openai_attempt(
        self,
        prompt_text: str,
        response_data: dict[str, Any] | None,
        error_message: str,
        context: dict[str, Any],
        endpoint: str,
        attempt: int,
    ) -> None:
        logs_dir = Path("logs") / "llm_interactions"
        try:
            logs_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
            generation = int(context.get("generation", 0)) if str(context.get("generation", "")).strip() != "" else 0
            run_id = str(context.get("run_id", "unknown_run")).replace("/", "_")
            filename = f"{ts}_{self.config.model.replace('/', '_')}_gen{generation}_attempt{attempt}_{run_id}.md"
            path = logs_dir / filename
            with path.open("w", encoding="utf-8") as handle:
                handle.write(f"# OpenAI Attempt Log\n\n")
                handle.write(f"- timestamp_utc: {datetime.utcnow().isoformat()}\n")
                handle.write(f"- model: {self.config.model}\n")
                handle.write(f"- endpoint: {endpoint}\n")
                handle.write(f"- generation: {generation}\n")
                handle.write(f"- run_id: {run_id}\n")
                handle.write(f"- attempt: {attempt}\n")
                handle.write(f"- error: {error_message}\n\n")
                handle.write("## Prompt\n```text\n")
                handle.write(prompt_text)
                handle.write("\n```\n\n")
                handle.write("## Response\n")
                if isinstance(response_data, dict):
                    handle.write("```json\n")
                    handle.write(json.dumps(response_data, ensure_ascii=False, indent=2))
                    handle.write("\n```\n")
                else:
                    handle.write("No structured response captured.\n")
        except Exception:
            return

    def _attach_prompt_audit_metadata(self, candidate: dict[str, Any], context: dict[str, Any], prompt_text: str) -> None:
        metadata_raw = candidate.get("llm_metadata")
        metadata_payload = metadata_raw if isinstance(metadata_raw, dict) else {}
        references = context.get("reference_models")
        ref_count = len([item for item in references if isinstance(item, dict)]) if isinstance(references, list) else 0
        latest_metrics_raw = context.get("latest_metrics")
        latest_metrics = latest_metrics_raw if isinstance(latest_metrics_raw, dict) else {}
        selection_trace_raw = context.get("reference_selection_trace")
        selection_trace = selection_trace_raw if isinstance(selection_trace_raw, dict) else {}
        selected_raw = selection_trace.get("selected")
        selected_refs = selected_raw if isinstance(selected_raw, list) else []
        policy_version = str(selection_trace.get("policy_version", "selection_policy_v1"))
        metadata_payload["prompt_audit"] = {
            "generation": int(context.get("generation", 0)),
            "run_id": str(context.get("run_id", "")),
            "code_version": str(context.get("code_version", "")),
            "reference_models_count": ref_count,
            "reference_policy_version": policy_version,
            "reference_models_selected": selected_refs,
            "latest_metrics": latest_metrics,
            "prompt_chars": len(prompt_text),
            "prompt_preview": prompt_text[:1000],
            "prompt_template_file": self.config.prompt_template_file,
            "architecture_guide_file": self.config.architecture_guide_file,
            "experiment_config_file": self.config.experiment_config_file,
        }
        candidate["llm_metadata"] = metadata_payload

    def _build_payload(
        self,
        endpoint: str,
        prompt_text: str,
        use_max_completion_tokens: bool,
        max_tokens_override: int | None = None,
        model_override: str | None = None,
    ) -> dict[str, Any]:
        max_tokens_value = max_tokens_override if isinstance(max_tokens_override, int) and max_tokens_override > 0 else self.config.max_tokens
        max_tokens_key = "max_completion_tokens" if use_max_completion_tokens else "max_tokens"
        model_name = model_override if isinstance(model_override, str) and model_override.strip() != "" else self.config.model
        if endpoint.endswith("/completions") and not endpoint.endswith("/chat/completions"):
            payload = {
                "model": model_name,
                "prompt": f"{self.config.system_prompt}\n\n{prompt_text}",
                "temperature": self.config.temperature,
                max_tokens_key: max_tokens_value,
            }
            return payload
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": prompt_text},
            ],
            "temperature": self.config.temperature,
            max_tokens_key: max_tokens_value,
        }
        return payload

    def _extract_content_from_response(self, data: dict[str, Any], endpoint: str) -> str:
        choices = data.get("choices")
        first_choice = choices[0] if isinstance(choices, list) and len(choices) > 0 and isinstance(choices[0], dict) else {}
        if endpoint.endswith("/completions") and not endpoint.endswith("/chat/completions"):
            return str(first_choice.get("text", "")).strip()
        message = first_choice.get("message")
        if isinstance(message, dict):
            message_content = message.get("content", "")
            if isinstance(message_content, str):
                value = message_content.strip()
                if value != "":
                    return value
            if isinstance(message_content, list):
                parts: list[str] = []
                for item in message_content:
                    if isinstance(item, dict):
                        if isinstance(item.get("text"), str):
                            parts.append(str(item.get("text")))
                            continue
                        nested_text = item.get("text", {})
                        if isinstance(nested_text, dict) and isinstance(nested_text.get("value"), str):
                            parts.append(str(nested_text.get("value")))
                joined = "\n".join([part for part in parts if part.strip() != ""]).strip()
                if joined != "":
                    return joined
        if isinstance(first_choice.get("text"), str):
            fallback_text = str(first_choice.get("text")).strip()
            if fallback_text != "":
                return fallback_text
        if isinstance(data.get("output_text"), str):
            output_text = str(data.get("output_text")).strip()
            if output_text != "":
                return output_text
        return ""

    def _resolve_endpoint(self, endpoint: str) -> str:
        trimmed = endpoint.strip().rstrip("/")
        if trimmed == "":
            return "https://api.openai.com/v1/chat/completions"
        if trimmed.endswith("/completions"):
            return trimmed
        if trimmed.endswith("/chat/completions"):
            return trimmed
        return f"{trimmed}/chat/completions"

    def _resolve_gemini_endpoint(self, endpoint: str, model: str) -> str:
        trimmed = endpoint.strip().rstrip("/")
        if trimmed == "":
            trimmed = "https://generativelanguage.googleapis.com/v1beta/models"
        if ":generateContent" in trimmed:
            return trimmed
        if trimmed.endswith("/models"):
            return f"{trimmed}/{model}:generateContent"
        if trimmed.endswith("/models/"):
            return f"{trimmed}{model}:generateContent"
        if "/models/" in trimmed and not trimmed.endswith(model):
            return f"{trimmed}/{model}:generateContent"
        if trimmed.endswith(model):
            return f"{trimmed}:generateContent"
        return f"{trimmed}/models/{model}:generateContent"

    def _extract_content_from_gemini_response(self, data: dict[str, Any]) -> str:
        candidates = data.get("candidates")
        first_candidate = candidates[0] if isinstance(candidates, list) and len(candidates) > 0 and isinstance(candidates[0], dict) else {}
        content = first_candidate.get("content")
        if isinstance(content, dict):
            parts = content.get("parts")
            if isinstance(parts, list):
                texts: list[str] = []
                for item in parts:
                    if isinstance(item, dict) and isinstance(item.get("text"), str):
                        texts.append(str(item.get("text")))
                joined = "\n".join([text for text in texts if text.strip() != ""]).strip()
                if joined != "":
                    return joined
        return ""

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

    def _repair_candidate_after_validation_error(
        self,
        candidate: dict[str, Any],
        validation_error: str,
        context: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not self.config.repair_on_validation_error:
            return None
        auto_repaired = self._auto_repair_candidate_structure(candidate)
        if auto_repaired is not None:
            return auto_repaired
        model_definition = self._extract_model_definition(candidate)
        if model_definition is None:
            return None
        prompt_text = self._build_repair_prompt(model_definition, validation_error, context)
        if prompt_text.strip() == "":
            return None
        if self.config.use_legacy_interface:
            repaired = self._repair_with_legacy_interface(prompt_text, context)
        else:
            repaired = self._repair_with_openai_compatible(prompt_text)
        if repaired is None:
            return None
        repaired_candidate = self._normalize_candidate_response(repaired, provider=f"{self.config.provider}_repair")
        repaired_metadata = repaired_candidate.get("llm_metadata")
        repaired_metadata_payload = repaired_metadata if isinstance(repaired_metadata, dict) else {}
        repaired_metadata_payload["repair_from_error"] = validation_error
        repaired_candidate["llm_metadata"] = repaired_metadata_payload
        return repaired_candidate

    def _auto_repair_candidate_structure(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        model_definition = self._extract_model_definition(candidate)
        if not isinstance(model_definition, dict):
            return None
        model_definition = self._normalize_model_definition_schema(model_definition)
        proposal_payload = candidate.get("proposal")
        if isinstance(proposal_payload, dict):
            proposal_payload["model_definition"] = model_definition
            candidate["proposal"] = proposal_payload
        architecture = model_definition.get("architecture_definition")
        if not isinstance(architecture, dict):
            return None
        changed = False
        used_inputs = architecture.get("used_inputs")
        if not isinstance(used_inputs, list) or len(used_inputs) == 0:
            autofilled_inputs = self._autofill_used_inputs(architecture)
            if len(autofilled_inputs) > 0:
                architecture["used_inputs"] = autofilled_inputs
                changed = True
        output_heads = architecture.get("output_heads")
        if not isinstance(output_heads, list) or len(output_heads) == 0:
            autofilled_heads = self._autofill_output_heads(architecture)
            if len(autofilled_heads) > 0:
                architecture["output_heads"] = autofilled_heads
                changed = True
        return candidate if changed else None

    def _autofill_used_inputs(self, architecture: dict[str, Any]) -> list[dict[str, Any]]:
        experiment = self._read_json(self.config.experiment_config_file)
        candidates: list[dict[str, Any]] = []
        features = experiment.get("input_features_config", [])
        if isinstance(features, list):
            mandatory = [item for item in features if isinstance(item, dict) and bool(item.get("is_mandatory_input", False))]
            ordered = mandatory if len(mandatory) > 0 else [item for item in features if isinstance(item, dict)]
            for item in ordered[:4]:
                input_layer_name = str(item.get("default_input_layer_name", "")).strip()
                source_feature_name = str(item.get("feature_name", "")).strip()
                total_columns = int(item.get("total_columns", 0) or 0)
                if input_layer_name == "" or source_feature_name == "" or total_columns <= 0:
                    continue
                candidates.append(
                    {
                        "input_layer_name": input_layer_name,
                        "source_feature_name": source_feature_name,
                        "shape": [total_columns],
                    }
                )
        if len(candidates) > 0:
            return candidates
        branches = architecture.get("branches", [])
        if isinstance(branches, list):
            seen: set[str] = set()
            for branch in branches:
                if not isinstance(branch, dict):
                    continue
                input_name = str(branch.get("input_source_layer", "")).strip()
                if input_name == "" or input_name in seen:
                    continue
                seen.add(input_name)
                candidates.append(
                    {
                        "input_layer_name": input_name,
                        "source_feature_name": input_name,
                        "shape": [1],
                    }
                )
        return candidates

    def _autofill_output_heads(self, architecture: dict[str, Any]) -> list[dict[str, Any]]:
        experiment = self._read_json(self.config.experiment_config_file)
        targets = experiment.get("output_targets_config", [])
        source_feature_map = self._guess_source_feature_map(architecture)
        if source_feature_map == "":
            return []
        heads: list[dict[str, Any]] = []
        if isinstance(targets, list):
            mandatory = [item for item in targets if isinstance(item, dict) and bool(item.get("is_mandatory_output", False))]
            ordered = mandatory if len(mandatory) > 0 else [item for item in targets if isinstance(item, dict)]
            for item in ordered[:4]:
                target_name = str(item.get("target_name", "")).strip()
                if target_name == "":
                    continue
                output_layer_name = str(item.get("default_output_layer_name", "")).strip() or f"output_{target_name}"
                total_columns = int(item.get("total_columns", 1) or 1)
                activation = str(item.get("activation_output_layer", "")).strip() or "linear"
                heads.append(
                    {
                        "output_layer_name": output_layer_name,
                        "maps_to_target_config_name": target_name,
                        "source_feature_map": source_feature_map,
                        "units": max(1, total_columns),
                        "activation": activation,
                    }
                )
        return heads

    def _guess_source_feature_map(self, architecture: dict[str, Any]) -> str:
        merges = architecture.get("merges", [])
        if isinstance(merges, list) and len(merges) > 0:
            for merge in reversed(merges):
                if not isinstance(merge, dict):
                    continue
                out = str(merge.get("output_feature_map_name", "")).strip()
                if out != "":
                    return out
        branches = architecture.get("branches", [])
        if isinstance(branches, list) and len(branches) > 0:
            for branch in reversed(branches):
                if not isinstance(branch, dict):
                    continue
                out = str(branch.get("output_feature_map_name", "")).strip()
                if out != "":
                    return out
        used_inputs = architecture.get("used_inputs", [])
        if isinstance(used_inputs, list) and len(used_inputs) > 0:
            first = used_inputs[0]
            if isinstance(first, dict):
                return str(first.get("input_layer_name", "")).strip()
        return ""

    def _extract_model_definition(self, candidate: dict[str, Any]) -> dict[str, Any] | None:
        proposal = candidate.get("proposal")
        if not isinstance(proposal, dict):
            return None
        model_definition = proposal.get("model_definition")
        if isinstance(model_definition, dict):
            return model_definition
        if isinstance(proposal.get("architecture_definition"), dict):
            return proposal
        return None

    def _build_repair_prompt(self, model_definition: dict[str, Any], validation_error: str, context: dict[str, Any]) -> str:
        template = self._read_text(self.config.fix_error_prompt_file)
        if template.strip() == "":
            return ""
        experiment = self._read_json(self.config.experiment_config_file)
        architecture_guide = self._read_text(self.config.architecture_guide_file)
        references = context.get("reference_models")
        working_example = references[0] if isinstance(references, list) and len(references) > 0 and isinstance(references[0], dict) else {}
        try:
            from v2_prompt_builder import V2PromptBuilder
            repo_root = Path(__file__).resolve().parents[2]
            builder = V2PromptBuilder(
                repo_root=repo_root,
                prompt_template_file=self.config.prompt_template_file,
                architecture_guide_file=self.config.architecture_guide_file,
                experiment_config_file=self.config.experiment_config_file,
                num_new_models=self.config.num_new_models,
                num_reference_models=self.config.num_reference_models,
            )
            architecture_guide = builder._combined_architecture_guide(architecture_guide)
        except Exception:
            pass
        error_context = {
            "validation_error": validation_error,
            "generation": int(context.get("generation", 0)),
            "run_id": str(context.get("run_id", "")),
            "latest_metrics": context.get("latest_metrics", {}),
            "reference_selection_trace": context.get("reference_selection_trace", {}),
        }
        prompt = template
        prompt = prompt.replace("{{buggy_model_json}}", json.dumps(model_definition, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{{error_traceback}}", json.dumps(error_context, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{{working_model_example_json}}", json.dumps(working_example, ensure_ascii=False, indent=2))
        prompt = prompt.replace("{{available_inputs_description}}", self._inputs_description(experiment))
        prompt = prompt.replace("{{available_outputs_description}}", self._outputs_description(experiment))
        prompt = prompt.replace("{{architecture_guide_content}}", architecture_guide)
        return prompt

    def _repair_with_legacy_interface(self, prompt_text: str, context: dict[str, Any]) -> dict[str, Any] | None:
        from shared.clients.llm_interface import ask_openai  # type: ignore[import]
        llm_config = {
            "openai_api_key": self.config.api_key or os.getenv("OPENAI_API_KEY", ""),
            "api_url": self._resolve_endpoint(self.config.endpoint),
            "openai_model_name": self.config.model,
            "system_message": self.config.system_prompt,
            "max_tokens": max(1200, int(self.config.max_tokens)),
            "temperature": self.config.temperature,
        }
        if str(llm_config["openai_api_key"]).strip() == "":
            return None
        response_text = ask_openai(
            prompt_text,
            llm_config,
            context_for_log={"task_type": "v2_fix_model_error", "generation_num": context.get("generation")},
        )
        if not response_text:
            return None
        extracted = self._extract_first_json_payload(str(response_text))
        parsed = json.loads(extracted)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
            return parsed[0]
        return None

    def _repair_with_openai_compatible(self, prompt_text: str) -> dict[str, Any] | None:
        endpoint = self._resolve_endpoint(self.config.endpoint)
        payload = self._build_payload(endpoint, prompt_text, False, max(1200, int(self.config.max_tokens)))
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
        content = self._extract_content_from_response(data, endpoint)
        if content.strip() == "":
            return None
        extracted = self._extract_first_json_payload(content)
        parsed = json.loads(extracted)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and len(parsed) > 0 and isinstance(parsed[0], dict):
            return parsed[0]
        return None

    def _resolve_path(self, file_path: str) -> Path:
        raw = Path(file_path)
        if raw.is_absolute():
            if raw.exists():
                return raw
            normalized = str(raw).replace("\\", "/")
            if "/V2/" in normalized:
                fallback = Path(normalized.replace("/V2/", "/", 1))
                if fallback.exists():
                    return fallback
            return raw
        repo_root = Path(__file__).resolve().parents[2]
        candidate = (repo_root / raw).resolve()
        if candidate.exists():
            return candidate
        normalized_rel = str(raw).replace("\\", "/")
        if normalized_rel.startswith("V2/"):
            fallback = (repo_root / normalized_rel[3:]).resolve()
            if fallback.exists():
                return fallback
        return candidate

    def _read_text(self, file_path: str) -> str:
        path = self._resolve_path(file_path)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _read_json(self, file_path: str) -> dict[str, Any]:
        path = self._resolve_path(file_path)
        if not path.exists():
            return {}
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def _inputs_description(self, experiment: dict[str, Any]) -> str:
        rows: list[str] = []
        for item in experiment.get("input_features_config", [])[:30]:
            if not isinstance(item, dict):
                continue
            rows.append(
                f"- feature_name={item.get('feature_name', 'unknown')}, "
                f"default_input_layer_name={item.get('default_input_layer_name', 'n/a')}, "
                f"total_columns={item.get('total_columns', 'n/a')}"
            )
        return "\n".join(rows) if rows else "No input features config available."

    def _outputs_description(self, experiment: dict[str, Any]) -> str:
        rows: list[str] = []
        for item in experiment.get("output_targets_config", [])[:30]:
            if not isinstance(item, dict):
                continue
            rows.append(
                f"- target_name={item.get('target_name', 'unknown')}, "
                f"default_output_layer_name={item.get('default_output_layer_name', 'n/a')}, "
                f"total_columns={item.get('total_columns', 'n/a')}, "
                f"is_mandatory_output={item.get('is_mandatory_output', False)}"
            )
        return "\n".join(rows) if rows else "No output targets config available."

    def _validate_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        proposal = candidate.get("proposal")
        if not isinstance(proposal, dict) or len(proposal) == 0:
            raise RuntimeError("LLM candidate proposal is empty or invalid")
        model_definition = proposal.get("model_definition")
        if not isinstance(model_definition, dict):
            if isinstance(proposal.get("architecture_definition"), dict):
                model_definition = proposal
                candidate["proposal"] = {"model_definition": model_definition}
            else:
                raise RuntimeError("LLM candidate must include model_definition")
        model_definition = self._normalize_model_definition_schema(model_definition)
        candidate["proposal"] = {"model_definition": model_definition}
        architecture = model_definition.get("architecture_definition", {})
        if not isinstance(architecture, dict):
            raise RuntimeError("LLM model_definition misses architecture_definition")
        used_inputs = architecture.get("used_inputs", [])
        output_heads = architecture.get("output_heads", [])
        if (not isinstance(used_inputs, list) or len(used_inputs) == 0) or (
            not isinstance(output_heads, list) or len(output_heads) == 0
        ):
            repaired = self._auto_repair_candidate_structure(candidate)
            if repaired is not None:
                repaired_proposal = repaired.get("proposal")
                repaired_model_definition = repaired_proposal.get("model_definition") if isinstance(repaired_proposal, dict) else None
                if isinstance(repaired_model_definition, dict):
                    architecture = repaired_model_definition.get("architecture_definition", {})
                    used_inputs = architecture.get("used_inputs", []) if isinstance(architecture, dict) else []
                    output_heads = architecture.get("output_heads", []) if isinstance(architecture, dict) else []
                    candidate = repaired
        if not isinstance(used_inputs, list) or len(used_inputs) == 0:
            raise RuntimeError("LLM model_definition has empty used_inputs")
        if not isinstance(output_heads, list) or len(output_heads) == 0:
            raise RuntimeError("LLM model_definition has empty output_heads")
        return candidate

    def _normalize_model_definition_schema(self, model_definition: dict[str, Any]) -> dict[str, Any]:
        architecture = model_definition.get("architecture_definition")
        if not isinstance(architecture, dict):
            architecture = {}
        for key in ["used_inputs", "branches", "merges", "output_heads"]:
            if isinstance(model_definition.get(key), list) and key not in architecture:
                architecture[key] = model_definition.get(key)
        model_definition["architecture_definition"] = architecture
        return model_definition
