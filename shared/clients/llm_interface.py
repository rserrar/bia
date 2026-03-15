import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import requests

try:
    from tenacity import RetryError, retry, stop_after_attempt, wait_exponential
except ImportError:  # pragma: no cover - dependència opcional, es documenta a requirements
    RetryError = Exception  # type: ignore[assignment]

    def retry(*_args: Any, **_kwargs: Any):  # type: ignore[no-redef]
        def decorator(func):
            return func

        return decorator

    def stop_after_attempt(_n: int):  # type: ignore[no-redef]
        return None

    def wait_exponential(*_args: Any, **_kwargs: Any):  # type: ignore[no-redef]
        return None


LLM_LOGS_DIR = "logs/llm_interactions"


def load_llm_config(config_file_path: str) -> Dict[str, Any]:
    """
    Carrega la configuració de l'LLM des d'un JSON.

    Manté el mateix contracte que la versió legacy a `utils/llm_interface.py`
    però viu dins de V2 perquè el worker no depengui del directori `utils/`.
    """
    try:
        Path(LLM_LOGS_DIR).mkdir(parents=True, exist_ok=True)
        path = Path(config_file_path)
        if not path.exists():
            raise FileNotFoundError(f"Fitxer de configuració LLM '{config_file_path}' no trobat.")
        with path.open("r", encoding="utf-8") as handle:
            config = json.load(handle)
        if "openai_api_key_env_var" in config and config["openai_api_key_env_var"]:
            api_key_from_env = os.getenv(config["openai_api_key_env_var"])
            if not api_key_from_env:
                raise ValueError(f"Variable d'entorn '{config['openai_api_key_env_var']}' no trobada.")
            config["openai_api_key"] = api_key_from_env
        elif (
            "openai_api_key" not in config
            or not config["openai_api_key"]
            or "LA_TEVA_API_KEY_VA_AQUI" in str(config["openai_api_key"])
        ):
            raise ValueError("API Key d'OpenAI no configurada a llm_settings.json")
        return config
    except Exception:
        raise


def _log_llm_interaction(
    timestamp_str: str,
    model_name: str,
    prompt_text: str,
    response_text: str | None,
    error_message: str | None = None,
    context_info: Dict[str, Any] | None = None,
) -> None:
    """
    Desa la interacció amb l'LLM en un fitxer Markdown per a traçabilitat.
    """
    filename_parts: list[str] = [timestamp_str, model_name.replace(":", "-").replace("/", "_")]
    if context_info:
        task_type = context_info.get("task_type", "task")
        gen_num = context_info.get("generation_num", "N/A")
        filename_parts.extend([str(task_type), f"gen{gen_num}"])
        buggy_model_id = context_info.get("buggy_model_id")
        if buggy_model_id:
            filename_parts.append(f"fixing_{buggy_model_id}")

    filename = "_".join(map(str, filename_parts)) + ".md"
    filename = "".join(c for c in filename if c.isalnum() or c in ("_", "-", "."))
    filepath = Path(LLM_LOGS_DIR) / filename

    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with filepath.open("w", encoding="utf-8") as handle:
            handle.write(f"# Interacció amb LLM ({model_name})\n\n")
            handle.write(f"**Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            if context_info:
                for key, value in context_info.items():
                    handle.write(f"**{key.replace('_', ' ').title()}:** {value}\n")
            handle.write("\n## Prompt Enviada:\n```text\n" + prompt_text + "\n```\n")
            handle.write("\n## Resposta Rebuda:\n")
            if response_text:
                try:
                    formatted = json.dumps(json.loads(response_text), indent=2, ensure_ascii=False)
                    handle.write("```json\n" + formatted + "\n```\n")
                except json.JSONDecodeError:
                    handle.write("```text\n" + response_text + "\n```\n")
            else:
                handle.write("No s'ha rebut resposta.\n")
            if error_message:
                handle.write("\n## Error:\n```text\n" + str(error_message) + "\n```\n")
    except Exception:
        # En cas d'error de logging, no bloquegem el flux principal
        return


@retry(
    wait=wait_exponential(multiplier=2, min=3, max=45),
    stop=stop_after_attempt(3),
)
def _attempt_llm_call(llm_config: Dict[str, Any], prompt_text: str) -> str:
    """
    Fa un únic intent de crida a l'API d'OpenAI amb timeout i retorna el `content`.
    """
    api_key = llm_config.get("openai_api_key")
    api_url = llm_config.get("api_url", "https://api.openai.com/v1/chat/completions")
    model = llm_config.get("openai_model_name", "gpt-4-turbo-preview")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": llm_config.get("system_message", "Ets un assistent expert.")},
            {"role": "user", "content": prompt_text},
        ],
        "max_tokens": llm_config.get("max_tokens", 4096),
        "temperature": llm_config.get("temperature", 0.5),
        "response_format": {"type": "json_object"},
    }

    response = requests.post(api_url, headers=headers, json=payload, timeout=llm_config.get("timeout", 160))
    response.raise_for_status()
    response_json = response.json()
    content = response_json["choices"][0]["message"]["content"]
    if not content:
        raise ValueError("La resposta de l'LLM ha arribat però estava buida.")
    return content


def ask_openai(prompt_text: str, llm_provider_config: Dict[str, Any], context_for_log: Dict[str, Any] | None = None) -> str | None:
    """
    Funció principal utilitzada pel worker V2 per fer crides a l'LLM.
    Manté la signatura de `utils.llm_interface.ask_openai`.
    """
    model_name = llm_provider_config.get("openai_model_name", "gpt-3.5-turbo")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

    response_content: str | None = None
    error_message: str | None = None

    try:
        response_content = _attempt_llm_call(llm_provider_config, prompt_text)
        try:
            json.loads(response_content)
        except json.JSONDecodeError as error:
            error_message = f"La resposta de l'LLM no és un JSON vàlid: {error}"
    except RetryError as error:  # type: ignore[arg-type]
        last = getattr(error, "last_attempt", None)
        detail = getattr(last, "exception", lambda: error)()
        error_message = f"La crida a l'LLM ha fallat després de múltiples reintents. Error final: {detail}"
        response_content = None
    except Exception as error:
        error_message = f"Error inesperat durant la crida a l'LLM: {error}"
        response_content = None

    _log_llm_interaction(
        timestamp_str=timestamp,
        model_name=model_name,
        prompt_text=prompt_text,
        response_text=response_content,
        error_message=error_message,
        context_info=context_for_log or {},
    )

    return response_content

