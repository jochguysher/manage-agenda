"""Workflows for evaluating configured LLM models."""

import time

from manage_agenda.config import msg_txt_dir
from manage_agenda.i18n import t
from manage_agenda.llm import OllamaClient
from manage_agenda.sources import process_email_cli, process_txt_cli, process_web_cli


def evaluate_models(args, prompt=None, eval_type=None):
    """Evaluate available Ollama models against a prompt or source workflow."""
    results = []
    models = OllamaClient.list_models()
    if not models:
        print(t("evaluation.no_models_available"))
    for model_info in models:
        model_name = model_info["model"]
        print(t("evaluation.evaluating_model", model_name=model_name))
        client = OllamaClient(model_name=model_name)

        if eval_type == "email":
            print(t("evaluation.cli_email_result", result=process_email_cli(args, client)))
        elif eval_type == "web":
            print(t("evaluation.cli_web_result", result=process_web_cli(args, client)))
        elif eval_type == "txt":
            print(
                t(
                    "evaluation.cli_txt_result",
                    result=process_txt_cli(args, client, source_name=msg_txt_dir()),
                )
            )
        elif prompt:
            print(t("evaluation.prompt_label", prompt=prompt))
            start_time = time.time()
            response = client.generate_text(prompt)
            duration = time.time() - start_time
            results.append({"model": model_name, "response": response, "duration": duration})

    if results:
        print(t("evaluation.results_header"))
        for result in results:
            print(t("evaluation.result_model", model=result["model"]))
            print(t("evaluation.result_time_taken", duration=f"{result['duration']:.2f}"))
            print(t("evaluation.result_response", response=result["response"]))
            print(t("evaluation.result_separator"))
