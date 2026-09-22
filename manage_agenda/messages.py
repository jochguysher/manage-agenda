"""English/French message catalog for manage_agenda.i18n.t().

Keys are grouped by the module whose user-facing text they translate (print(), click.echo(),
input()/click.prompt() prompts, Click --help text, and messages raised as CalendarError/
LLMError that reach the user via print(error)). Keys follow "<module>.<snake_case_summary>".
Internal logging.*() calls are not covered - they are diagnostics, not "the interface".
"""

TRANSLATIONS = {
    # --- llm.py ---
    "llm.available_models": {
        "en": "Available models",
        "fr": "Modèles disponibles",
    },
    "llm.select_provider_title": {
        "en": "Select model provider",
        "fr": "Sélectionnez le fournisseur de modèle",
    },
    "llm.selected_ai": {
        "en": "Selected AI: {ai}",
        "fr": "IA sélectionnée : {ai}",
    },
}
