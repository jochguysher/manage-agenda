"""English/French message catalog for manage_agenda.i18n.t().

Keys are grouped by the module whose user-facing text they translate (print(), click.echo(),
input()/click.prompt() prompts, Click --help text, and messages raised as CalendarError/
LLMError that reach the user via print(error)). Keys follow "<module>.<snake_case_summary>".
Internal logging.*() calls are not covered - they are diagnostics, not "the interface".
"""

TRANSLATIONS = {
    # --- cli.py ---
    "cli.app_help": {
        "en": "An app for adding entries to my calendar",
        "fr": "Une application pour ajouter des entrées à mon agenda",
    },
    "cli.verbose_help": {
        "en": "Enable verbose output.",
        "fr": "Active la sortie détaillée.",
    },
    "cli.interactive_help": {
        "en": "Running in interactive mode",
        "fr": "Exécution en mode interactif",
    },
    "cli.output_help": {
        "en": "Output destination: calendar or file",
        "fr": "Destination de sortie : calendar ou file",
    },
    "cli.select_source_calendar_help": {
        "en": "Select source calendar",
        "fr": "Sélectionnez le calendrier source",
    },
    "cli.select_destination_calendar_help": {
        "en": "Select destination calendar",
        "fr": "Sélectionnez le calendrier de destination",
    },
    "cli.select_text_help": {
        "en": "Select text in title",
        "fr": "Sélectionnez le texte dans le titre",
    },
    "cli.llm_group_help": {
        "en": "LLM related operations",
        "fr": "Opérations liées au LLM",
    },
    "cli.evaluate.help": {
        "en": "Evaluate different LLM models",
        "fr": "Évaluer différents modèles de LLM",
    },
    "cli.evaluate.type_help": {
        "en": "Type of evaluation to run (email, web, txt)",
        "fr": "Type d'évaluation à exécuter (email, web, txt)",
    },
    "cli.add.help": {
        "en": "Add entries to the calendar.",
        "fr": "Ajouter des entrées à l'agenda.",
    },
    "cli.add.ai_help": {
        "en": "Select LLM for this run only, without changing the saved configuration",
        "fr": "Sélectionnez le LLM pour cette exécution uniquement, sans modifier la configuration sauvegardée",
    },
    "cli.add.model_help": {
        "en": "Select model for this run only, without changing the saved configuration",
        "fr": "Sélectionnez le modèle pour cette exécution uniquement, sans modifier la configuration sauvegardée",
    },
    "cli.add.force_refresh_help": {
        "en": "Force refresh web content to bypass cache",
        "fr": "Force le rafraîchissement du contenu web pour contourner le cache",
    },
    "cli.add.source_help": {
        "en": "Source of data: email, gmail, imap, web, or text files",
        "fr": "Source des données : email, gmail, imap, web, ou fichiers texte",
    },
    "cli.add.destination_help": {
        "en": "Destination calendar id for this run only, without changing the saved configuration",
        "fr": "Identifiant du calendrier de destination pour cette exécution uniquement, sans modifier la configuration sauvegardée",
    },
    "cli.add.rule_help": {
        "en": "IMAP sender rule. Default is auto, or review when -s imap -i",
        "fr": "Règle d'expéditeur IMAP. Par défaut auto, ou review avec -s imap -i",
    },
    "cli.add.reconfigure_help": {
        "en": "Reopen the interactive setup for provider, model, and calendar, and save the result",
        "fr": "Rouvre l'assistant interactif pour le fournisseur, le modèle et le calendrier, et sauvegarde le résultat",
    },
    "cli.auth.help": {
        "en": "Auth related operations",
        "fr": "Opérations liées à l'authentification",
    },
    "cli.auth.args_debug": {
        "en": "Args: {args}",
        "fr": "Arguments : {args}",
    },
    "cli.auth.authorized_success": {
        "en": "This account has been correctly authorized",
        "fr": "Ce compte a été correctement autorisé",
    },
    "cli.auth.opening_browser": {
        "en": "Opening the browser for Google consent.",
        "fr": "Ouverture du navigateur pour le consentement Google.",
    },
    "cli.auth.create_oauth_client_instructions": {
        "en": (
            "Create a Desktop app OAuth client and save the JSON under the expected name, "
            "then run: uv run manage-agenda auth -i"
        ),
        "fr": (
            "Créez un client OAuth d'application de bureau et sauvegardez le JSON sous le nom "
            "attendu, puis exécutez : uv run manage-agenda auth -i"
        ),
    },
    "cli.gcalendar.help": {
        "en": "List events from Google Calendar",
        "fr": "Lister les événements de Google Calendar",
    },
    "cli.gmail.help": {
        "en": "List emails from Gmail",
        "fr": "Lister les emails de Gmail",
    },
    "cli.copy.help": {
        "en": "Copy entries from one calendar to another",
        "fr": "Copier des entrées d'un calendrier à un autre",
    },
    "cli.clean.help": {
        "en": "Clean calendar entries (select between copy or delete)",
        "fr": "Nettoyer les entrées du calendrier (choix entre copier ou supprimer)",
    },
    "cli.delete.help": {
        "en": "Delete entries from a calendar",
        "fr": "Supprimer des entrées d'un calendrier",
    },
    "cli.move.help": {
        "en": "Move entries from one calendar to another",
        "fr": "Déplacer des entrées d'un calendrier à un autre",
    },
    "cli.update_status.help": {
        "en": "Update event status from busy to available",
        "fr": "Mettre à jour le statut d'un événement d'occupé à disponible",
    },
    "cli.install.help": {
        "en": (
            "Install the Playwright browser needed by this tool.\n\n"
            "Usage:\n\n"
            "    manage-agenda install\n\n"
            "Or for browsers other than the Firefox default:\n\n"
            "    manage-agenda install -b chromium"
        ),
        "fr": (
            "Installe le navigateur Playwright requis par cet outil.\n\n"
            "Utilisation :\n\n"
            "    manage-agenda install\n\n"
            "Ou pour un navigateur autre que Firefox par défaut :\n\n"
            "    manage-agenda install -b chromium"
        ),
    },
    "cli.install.browser_help": {
        "en": "Which browser to install",
        "fr": "Quel navigateur installer",
    },
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
