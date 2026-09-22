import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.append(".")

from manage_agenda.llm import (
    GeminiClient,
    LLMClient,
    MistralClient,
    OllamaClient,
    load_config,
)
from manage_agenda.sources import Args
from manage_agenda.user_config import load_user_config, save_user_config


class TestLoadConfig(unittest.TestCase):
    def test_load_config_file_exists(self):
        """Test loading a valid config file."""
        # config_content = "[section1]\napi_key=test_key_123\n"

        with patch("os.path.exists", return_value=True):
            with patch("configparser.ConfigParser.read") as mock_read:
                _ = load_config("/fake/path/config.ini")
                mock_read.assert_called_once_with("/fake/path/config.ini")

    def test_load_config_file_not_found(self):
        """Test loading a non-existent config file."""
        with patch("os.path.exists", return_value=False):
            with self.assertRaises(FileNotFoundError) as context:
                load_config("/fake/path/config.ini")
            self.assertIn("Config file not found", str(context.exception))


class TestLLMClient(unittest.TestCase):
    def test_init_base_class(self):
        """Test LLMClient base class initialization."""
        llm_client = LLMClient()
        self.assertIsInstance(llm_client, LLMClient)
        self.assertIsNone(llm_client.model_name)

    def test_generate_text_not_implemented(self):
        """Test that generate_text raises NotImplementedError."""
        llm_client = LLMClient()
        with self.assertRaises(NotImplementedError):
            llm_client.generate_text("test prompt")

    def test_get_name_not_implemented(self):
        """Test that get_name raises NotImplementedError."""
        llm_client = LLMClient()
        with self.assertRaises(NotImplementedError):
            llm_client.get_name()


class TestOllamaClient(unittest.TestCase):
    @patch("manage_agenda.llm.select_from_list")
    @patch("manage_agenda.llm.OllamaClient.list_models")
    def test_ollama_init_with_model_name(self, mock_list_models, mock_select):
        """Test OllamaClient initialization with model name."""
        client = OllamaClient(model_name="llama2")
        self.assertEqual(client.model_name, "llama2")
        mock_list_models.assert_not_called()
        mock_select.assert_not_called()

    @patch("manage_agenda.llm.select_from_list", return_value=(0, "llama2"))
    @patch("manage_agenda.llm.OllamaClient.list_models")
    def test_ollama_init_without_model_name(self, mock_list_models, mock_select):
        """Test OllamaClient initialization without model name."""
        mock_list_models.return_value = [{"model": "llama2"}, {"model": "mistral"}]

        client = OllamaClient(model_name="")

        mock_list_models.assert_called_once()
        mock_select.assert_called_once()
        self.assertIsNotNone(client.model_name)

    @patch("manage_agenda.llm.chat")
    def test_ollama_generate_text_success(self, mock_chat):
        """Test OllamaClient generate_text success."""
        mock_response = MagicMock()
        mock_response.message.content = "Generated response"
        mock_chat.return_value = mock_response

        client = OllamaClient(model_name="llama2")
        result = client.generate_text("test prompt")

        self.assertEqual(result, "Generated response")
        mock_chat.assert_called_once()

    @patch("manage_agenda.llm.chat", side_effect=Exception("API Error"))
    def test_ollama_generate_text_error(self, mock_chat):
        """Test OllamaClient generate_text error handling."""
        from manage_agenda.exceptions import LLMError

        client = OllamaClient(model_name="llama2")
        with self.assertRaises(LLMError):
            client.generate_text("test prompt")

    @patch("manage_agenda.llm.ollama.list")
    def test_ollama_list_models(self, mock_list):
        """Test OllamaClient list_models."""
        mock_list.return_value = {"models": [{"model": "llama2"}, {"model": "mistral"}]}

        models = OllamaClient.list_models()

        self.assertEqual(len(models), 2)
        self.assertEqual(models[0]["model"], "llama2")


class TestGeminiClient(unittest.TestCase):
    @patch("manage_agenda.llm.genai.Client")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_gemini_init_with_model_name(
        self, mock_exists, mock_load_config, mock_genai_client
    ):
        """Test GeminiClient initialization with model name."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        client = GeminiClient(model_name="gemini-pro")

        self.assertEqual(client.model_name, "gemini-pro")
        mock_genai_client.assert_called_once_with(api_key="fake_api_key")

    @patch("manage_agenda.llm.genai.Client")
    @patch("manage_agenda.llm.select_from_list", return_value=(0, "models/gemini-pro"))
    @patch("manage_agenda.llm.GeminiClient.list_models")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_gemini_init_without_model_name(
        self,
        mock_exists,
        mock_load_config,
        mock_list_models,
        mock_select,
        mock_genai_client,
    ):
        """Test GeminiClient initialization without model name."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        mock_model_obj = MagicMock()
        mock_model_obj.name = "models/gemini-pro"
        mock_list_models.return_value = [mock_model_obj]

        client = GeminiClient(model_name="")

        self.assertEqual(client.model_name, "gemini-pro")

    @patch("manage_agenda.llm.genai.Client")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_gemini_generate_text_success(
        self, mock_exists, mock_load_config, mock_genai_client
    ):
        """Test GeminiClient generate_text success."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        mock_client_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Gemini response"
        mock_client_instance.models.generate_content.return_value = mock_response
        mock_genai_client.return_value = mock_client_instance

        client = GeminiClient(model_name="gemini-pro")
        result = client.generate_text("test prompt")

        self.assertEqual(result, "Gemini response")

    @patch("manage_agenda.llm.genai.Client")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_gemini_generate_text_error(
        self, mock_exists, mock_load_config, mock_genai_client
    ):
        """Test GeminiClient generate_text error handling."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        mock_client_instance = MagicMock()
        mock_client_instance.models.generate_content.side_effect = Exception("API Error")
        mock_genai_client.return_value = mock_client_instance

        from manage_agenda.exceptions import LLMError

        client = GeminiClient(model_name="gemini-pro")
        with self.assertRaises(LLMError):
            client.generate_text("test prompt")

    @patch("manage_agenda.llm.genai.Client")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_gemini_list_models(self, mock_exists, mock_load_config, mock_genai_client):
        """Test GeminiClient list_models."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        mock_client_instance = MagicMock()
        mock_model1 = MagicMock()
        mock_model1.name = "gemini-pro"
        mock_model2 = MagicMock()
        mock_model2.name = "gemini-flash"
        mock_client_instance.models.list.return_value = [mock_model1, mock_model2]
        mock_genai_client.return_value = mock_client_instance

        client = GeminiClient(model_name="gemini-pro")

        models = client.list_models()

        self.assertEqual(len(models), 2)


class TestMistralClient(unittest.TestCase):
    @patch("manage_agenda.llm.select_from_list", return_value=(0, "mistral-small"))
    @patch("manage_agenda.llm.Mistral")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_mistral_init(self, mock_exists, mock_load_config, mock_mistral, mock_select):
        """Test MistralClient initialization."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        # Mock list_models
        mock_mistral_instance = MagicMock()
        mock_models = MagicMock()
        mock_models.data = [MagicMock(id="mistral-small")]
        mock_mistral_instance.models.list.return_value = mock_models
        mock_mistral.return_value = mock_mistral_instance

        _ = MistralClient(model_name="mistral-small")

    @patch("manage_agenda.llm.select_from_list")
    @patch("manage_agenda.llm.Mistral")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_mistral_with_a_model_name_does_not_prompt(
        self, mock_exists, mock_load_config, mock_mistral, mock_select
    ):
        """A given model_name used to be silently ignored (self.model_name was never set from
        it before the "do we need to prompt" check), so MistralClient always prompted even
        when told exactly which model to use."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        client = MistralClient(model_name="mistral-small-latest")

        mock_select.assert_not_called()
        self.assertEqual(client.model_name, "mistral-small-latest")

    @patch("manage_agenda.llm.select_from_list", return_value=(0, "mistral-small"))
    @patch("manage_agenda.llm.Mistral")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_mistral_generate_text_success(
        self, mock_exists, mock_load_config, mock_mistral_class, mock_select
    ):
        """Test MistralClient generate_text success."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        mock_mistral = MagicMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Mistral response"
        mock_mistral.chat.complete.return_value = mock_response
        mock_mistral_class.return_value = mock_mistral

        # Mock list_models
        mock_models = MagicMock()
        mock_models.data = [MagicMock(id="mistral-small")]
        mock_mistral.models.list.return_value = mock_models

        client = MistralClient(model_name="mistral-small")
        result = client.generate_text("test prompt")

        self.assertEqual(result, "Mistral response")

    @patch("manage_agenda.llm.select_from_list", return_value=(0, "mistral-small"))
    @patch("manage_agenda.llm.Mistral")
    @patch("manage_agenda.llm.load_config")
    @patch("os.path.exists", return_value=True)
    def test_mistral_generate_text_error(
        self, mock_exists, mock_load_config, mock_mistral_class, mock_select
    ):
        """Test MistralClient generate_text error handling."""
        mock_config = MagicMock()
        mock_config.sections.return_value = ["section1"]
        mock_config.get.return_value = "fake_api_key"
        mock_load_config.return_value = mock_config

        mock_mistral = MagicMock()
        mock_mistral.chat.complete.side_effect = Exception("API Error")
        mock_mistral_class.return_value = mock_mistral

        # Mock list_models
        mock_models = MagicMock()
        mock_models.data = [MagicMock(id="mistral-small")]
        mock_mistral.models.list.return_value = mock_models

        from manage_agenda.exceptions import LLMError

        client = MistralClient(model_name="mistral-small")
        with self.assertRaises(LLMError):
            client.generate_text("test prompt")


class TestSelectLlm(unittest.TestCase):
    """select_llm's precedence: -a/-m flags > saved config > interactive wizard > hardcoded
    default. config_path is always overridden here so these tests never touch the real
    ~/.config/manage-agenda/config.yaml (binding that path at import time, or defaulting to
    it silently in tests, would make results depend on whatever happens to be on this machine).
    """

    def setUp(self):
        self.config_path = Path("/tmp") / (self.id().replace(".", "_") + "_config.yaml")
        self.config_path.unlink(missing_ok=True)
        self.addCleanup(lambda: self.config_path.unlink(missing_ok=True))
        self.addCleanup(lambda: Path(str(self.config_path) + ".tmp").unlink(missing_ok=True))

    @patch("manage_agenda.llm.select_one", return_value="ollama")
    @patch("manage_agenda.llm.OllamaClient")
    def test_interactive_with_nothing_saved_prompts_and_saves(self, mock_ollama_client, mock_select_one):
        from manage_agenda.llm import select_llm

        mock_ollama_client.return_value.model_name = "granite4:latest"
        args = Args(interactive=True)

        model = select_llm(args, config_path=self.config_path)

        mock_select_one.assert_called_once()
        mock_ollama_client.assert_called_once_with()
        self.assertEqual(model, mock_ollama_client.return_value)
        saved = load_user_config(self.config_path)
        self.assertEqual(saved, {"provider": "ollama", "model": "granite4:latest"})

    @patch("manage_agenda.llm.select_one", return_value="mistral")
    @patch("manage_agenda.llm.MistralClient")
    def test_interactive_mistral_is_saved_too(self, mock_mistral_client, mock_select_one):
        from manage_agenda.llm import select_llm

        mock_mistral_client.return_value.model_name = "mistral-small-latest"
        args = Args(interactive=True)

        model = select_llm(args, config_path=self.config_path)

        mock_mistral_client.assert_called_once_with()
        self.assertEqual(model, mock_mistral_client.return_value)
        self.assertEqual(load_user_config(self.config_path)["provider"], "mistral")

    @patch("manage_agenda.llm.select_one")
    @patch("manage_agenda.llm.GeminiClient")
    def test_saved_config_is_reused_without_prompting_even_when_interactive(
        self, mock_gemini_client, mock_select_one
    ):
        from manage_agenda.llm import select_llm

        save_user_config({"provider": "gemini", "model": "gemini-2.0-flash"}, self.config_path)
        args = Args(interactive=True)

        model = select_llm(args, config_path=self.config_path)

        mock_select_one.assert_not_called()
        mock_gemini_client.assert_called_once_with("gemini-2.0-flash")
        self.assertEqual(model, mock_gemini_client.return_value)

    @patch("manage_agenda.llm.select_one")
    @patch("manage_agenda.llm.GeminiClient")
    def test_explicit_flags_override_saved_config_without_touching_it(
        self, mock_gemini_client, mock_select_one
    ):
        from manage_agenda.llm import select_llm

        save_user_config({"provider": "ollama", "model": "granite4:latest"}, self.config_path)
        args = Args(interactive=False, ai="gemini", model="gemini-2.5-pro")

        model = select_llm(args, config_path=self.config_path)

        mock_select_one.assert_not_called()
        mock_gemini_client.assert_called_once_with("gemini-2.5-pro")
        self.assertEqual(model, mock_gemini_client.return_value)
        # The flag override must not have overwritten the saved config.
        self.assertEqual(load_user_config(self.config_path)["provider"], "ollama")

    @patch("manage_agenda.llm.select_one")
    @patch("manage_agenda.llm.OllamaClient")
    def test_non_interactive_with_nothing_saved_and_no_flags_uses_hardcoded_default(
        self, mock_ollama_client, mock_select_one
    ):
        from manage_agenda.llm import select_llm

        args = Args(interactive=False)

        select_llm(args, config_path=self.config_path)

        mock_select_one.assert_not_called()
        mock_ollama_client.assert_called_once_with("granite4:latest")
        self.assertEqual(load_user_config(self.config_path), {})

    @patch("manage_agenda.llm.select_one", return_value="mistral")
    @patch("manage_agenda.llm.MistralClient")
    def test_reconfigure_re_prompts_even_with_a_saved_config_and_overwrites_it(
        self, mock_mistral_client, mock_select_one
    ):
        from manage_agenda.llm import select_llm

        mock_mistral_client.return_value.model_name = "mistral-small-latest"
        save_user_config({"provider": "ollama", "model": "granite4:latest"}, self.config_path)
        args = Args(interactive=False, reconfigure=True)

        select_llm(args, config_path=self.config_path)

        mock_select_one.assert_called_once()
        mock_mistral_client.assert_called_once_with()
        self.assertEqual(load_user_config(self.config_path)["provider"], "mistral")

    @patch("manage_agenda.llm.select_one")
    @patch("manage_agenda.llm.GeminiClient")
    def test_model_from_saved_config_is_ignored_when_the_provider_changed(
        self, mock_gemini_client, mock_select_one
    ):
        """The saved model was picked for the saved provider - reusing it under a different,
        explicitly-requested provider would hand that provider a nonsensical model name."""
        from manage_agenda.llm import select_llm

        save_user_config({"provider": "ollama", "model": "granite4:latest"}, self.config_path)
        args = Args(interactive=False, ai="gemini")

        select_llm(args, config_path=self.config_path)

        mock_select_one.assert_not_called()
        mock_gemini_client.assert_called_once_with("gemini-3.8-flash")

    def test_invalid_provider_logs_and_returns_none(self):
        from manage_agenda.llm import select_llm

        args = Args(interactive=False, ai="not-a-provider")

        self.assertIsNone(select_llm(args, config_path=self.config_path))


if __name__ == "__main__":
    unittest.main()
