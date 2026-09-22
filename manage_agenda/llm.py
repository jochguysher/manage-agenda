import configparser
import logging
import os
import subprocess
import time
import types

from socialModules.configMod import CONFIGDIR

from manage_agenda.exceptions import LLMError
from manage_agenda.i18n import t
from manage_agenda.ui import echo, get_ui, label_for, select_one

logger = logging.getLogger(__name__)

# How long OllamaClient waits for a freshly spawned `ollama serve` to answer before giving up:
# OLLAMA_START_ATTEMPTS polls, OLLAMA_START_DELAY_SECONDS apart. Module-level so a test can
# shrink them; the old code looped forever, respawning the server on every failed poll.
OLLAMA_START_ATTEMPTS = 10
OLLAMA_START_DELAY_SECONDS = 1.0

# Optional providers: each import below falls back to a stub when the SDK isn't installed,
# so they sit after the unconditional imports (E402 applies to plain imports only).
try:
    from google import genai
except Exception:
    genai = types.SimpleNamespace(
        configure=lambda *args, **kwargs: None,
        GenerativeModel=lambda *args, **kwargs: None,
        Client=lambda *args, **kwargs: None,
        list_models=lambda: [],
    )
try:
    import ollama
except Exception:
    ollama = types.SimpleNamespace(list=lambda: {"models": []})

try:
    from ollama import ChatResponse, chat
except Exception:
    ChatResponse = object

    def chat(*args, **kwargs):
        return None

try:
    from mistralai.client import Mistral
except Exception:
    class Mistral:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("mistralai is not installed")


# This shouln't go here?
def load_config(config_file):
    """Loads configuration from a file.

    Args:
        config_file (str): Path to the configuration file.

    Returns:
        configparser.ConfigParser: The configuration object.
    """
    config = configparser.ConfigParser()
    if os.path.exists(config_file):
        config.read(config_file)
    else:
        logger.error(f"Configuration file not found: {config_file}")
        raise FileNotFoundError(f"Config file not found: {config_file}")
    return config


# --- API Abstraction ---
class LLMClient:
    """Abstracts interactions with LLMs (Ollama, Gemini, Mistral)."""

    def __init__(self, name_class=None):
        if hasattr(self, "config") and self.config:
            try:
                config_file = f"{CONFIGDIR}/.rss{name_class[:-6]}"
                config = load_config(config_file)
            except FileNotFoundError:
                raise FileNotFoundError(
                    f"Configuration file: {config_file} does not exist\n"
                    f"You need to create it and add the API key"
                ) from None
            except Exception as e:
                raise Exception(e) from e

            section = config.sections()[0]
            self.api_key = config.get(section, "api_key")
        self.model_name = None

    def generate_text(self, prompt):
        raise NotImplementedError("Subclasses must implement this method")

    def get_name(self):
        raise NotImplementedError("Subclasses must implement this method")


class OllamaClient(LLMClient):
    def __init__(self, model_name=""):
        name_class = self.__class__.__name__
        self.config = False
        super().__init__(name_class)

        iss = isinstance(model_name, int)
        if not iss and not model_name:
            models = self._models_or_start_server()
            chosen = get_ui().choose_one(
                models, identifier="model", title=t("llm.available_models")
            )
            if chosen is None:
                raise LLMError(t("llm.no_model_selected"))
            self.model_name = label_for(chosen, "model")
        else:
            if isinstance(model_name, int):
                self.model_name = self.list_models()[0].model
            else:
                self.model_name = model_name

    @classmethod
    def _models_or_start_server(cls):
        """The installed models, starting `ollama serve` once when the first listing fails
        and polling a bounded number of times for it to come up - LLMError past that, so a
        missing binary or a server that never answers stops the flow instead of hanging it."""
        try:
            models = cls.list_models()
        except Exception as error:
            logger.info(f"Ollama not reachable ({error}); starting `ollama serve`.")
            echo(t("llm.starting_ollama"))
            try:
                subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except OSError as spawn_error:
                raise LLMError(t("llm.ollama_unreachable", error=spawn_error)) from spawn_error
            models = None
            last_error = error
            for _attempt in range(OLLAMA_START_ATTEMPTS):
                time.sleep(OLLAMA_START_DELAY_SECONDS)
                try:
                    models = cls.list_models()
                    break
                except Exception as retry_error:
                    last_error = retry_error
            if models is None:
                raise LLMError(t("llm.ollama_unreachable", error=last_error)) from last_error
        if not models:
            raise LLMError(t("llm.no_ollama_models"))
        return models

    def generate_text(self, prompt):
        try:
            response: ChatResponse = chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                options={"num_ctx": len(prompt),
                },
                keep_alive=0,
            )
            # To unload a model from memory in Ollama, you must use the
            # keep_alive parameter with a value of 0 via the API.
            # curl http://localhost:11434/api/generate -d '{"model": "llama3.2", "keep_alive": 0}'
            return response.message.content
        except Exception as e:
            logger.error(f"Error generating text with Ollama: {e}")
            if "model requires more system memory" in str(e) or "out of memory" in str(e).lower():
                logger.error(f"Ollama model {self.model_name} requires more memory than available: {e}")
                return "Memory"
            raise LLMError(str(e)) from e

    @staticmethod
    def list_models():
        return ollama.list()["models"]


class GeminiClient(LLMClient):
    # def __init__(self, model_name="gemini-1.5-flash-latest"):
    def __init__(self, model_name=""):
        name_class = self.__class__.__name__
        self.config = True

        super().__init__(name_class)

        self.client = genai.Client(api_key=self.api_key)
        if not model_name:
            # Only the Gemini models (what select_from_list's selector="gemini" filtered).
            models = [m for m in self.list_models() if "gemini" in label_for(m, "name")]
            chosen = get_ui().choose_one(
                models,
                identifier="name",
                title=t("llm.available_models"),
                default="models/gemini-2.0-flash",
            )
            if chosen is None:
                raise LLMError(t("llm.no_model_selected"))
            name = label_for(chosen, "name")
            echo(name)
            self.model_name = name.split("/")[1]
        else:
            self.model_name = model_name

        #self.client = genai.GenerativeModel(self.model_name)

    def generate_text(self, prompt):
        try:
            #response = self.client.generate_content(prompt)
            response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt
                    )
            return response.text
        except Exception as e:
            logger.error(f"Error generating text with Gemini: {e}")
            raise LLMError(str(e)) from e

    #@staticmethod
    def list_models(self):
        #return list(genai.list_models())
        return list(self.client.models.list())


class MistralClient(LLMClient):
    def __init__(self, model_name=""):
        name_class = self.__class__.__name__
        self.config = True

        super().__init__(name_class)

        self.client = Mistral(api_key=self.api_key)
        if model_name:
            self.model_name = model_name
        if not self.model_name:
            models = self.list_models(self).data
            chosen = get_ui().choose_one(
                models,
                identifier="id",
                title=t("llm.available_models"),
                default="mistral-small-latest",
            )
            if chosen is None:
                raise LLMError(t("llm.no_model_selected"))
            self.model_name = label_for(chosen, "id")

    def generate_text(self, prompt):
        try:
            response = self.client.chat.complete(
                model=self.model_name, messages=[{"content": prompt, "role": "user"}]
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Error generating text with Mistral: {e}")
            raise LLMError(str(e)) from e

    @staticmethod
    def list_models(self):
        return self.client.models.list()


DEFAULT_MODEL_BY_PROVIDER = {
    "ollama": "granite4:latest",
    "gemini": "gemini-3.8-flash",
    "mistral": "mistral-small-latest",
}


def select_llm(args, config_path=None):
    """Selects and initializes the appropriate LLM client.

    Precedence: -a/--ai and -m/--model flags (one-off, never saved) > saved user config >
    interactive wizard > a hardcoded default provider/model, same as before this feature
    existed. --reconfigure re-opens the wizard even when a config is already saved; whatever
    it picks is saved for next time, exactly like the very first interactive selection is.
    """
    from manage_agenda.user_config import load_user_config, update_user_config

    saved = load_user_config(config_path)
    reconfigure = getattr(args, "reconfigure", False)
    explicit_provider = getattr(args, "ai", None)
    explicit_model = getattr(args, "model", None)
    prompted = False

    if explicit_provider:
        ai = explicit_provider
    elif not reconfigure and saved.get("provider"):
        ai = saved["provider"]
    elif args.interactive or reconfigure:
        ai = select_one(
            ["ollama", "gemini", "mistral"], title=t("llm.select_provider_title"), default="ollama"
        )
        prompted = True
    else:
        ai = "ollama"
    echo(t("llm.selected_ai", ai=ai))

    if explicit_model:
        model_name = explicit_model
    elif not reconfigure and not explicit_provider and saved.get("provider") == ai:
        model_name = saved.get("model")
    else:
        model_name = None

    ask_for_model = not model_name and (args.interactive or reconfigure)
    if ask_for_model:
        prompted = True

    if ai == "ollama":
        if ask_for_model:
            model = None
            while not model:
                model = OllamaClient()
        else:
            model = OllamaClient(model_name or DEFAULT_MODEL_BY_PROVIDER["ollama"])
    elif ai == "gemini":
        if ask_for_model:
            model = GeminiClient()
        else:
            model = GeminiClient(model_name or DEFAULT_MODEL_BY_PROVIDER["gemini"])
    elif ai == "mistral":
        if ask_for_model:
            model = MistralClient()
        else:
            model = MistralClient(model_name or DEFAULT_MODEL_BY_PROVIDER["mistral"])
    else:
        logger.error(f"Invalid LLM source: {ai}")
        return None

    if prompted and not explicit_provider and not explicit_model:
        update_user_config({"provider": ai, "model": model.model_name}, config_path)

    return model
