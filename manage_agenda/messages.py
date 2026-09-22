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
    # --- connections.py ---
    "connections.choose_service_to_authorize": {
        "en": "Choose the Google service to authorize.",
        "fr": "Choisissez le service Google à autoriser.",
    },
    "connections.gcalendar_service_description": {
        "en": "  gcalendar — write events to Google Calendar (required by add)",
        "fr": "  gcalendar — écrire des événements dans Google Calendar (requis par add)",
    },
    "connections.gmail_service_description": {
        "en": "  gmail     — read a Gmail mailbox",
        "fr": "  gmail     — lire une boîte de messagerie Gmail",
    },
    "connections.google_service_title": {
        "en": "Google service",
        "fr": "Service Google",
    },
    "connections.account_title": {
        "en": "Account",
        "fr": "Compte",
    },
    "connections.select_calendar_title": {
        "en": "Select Calendar",
        "fr": "Sélectionnez le calendrier",
    },
    "connections.select_calendars_title": {
        "en": "Select calendar(s)",
        "fr": "Sélectionnez le(s) calendrier(s)",
    },
    "connections.google_token_saved": {
        "en": "Google token saved: {token_path}",
        "fr": "Jeton Google sauvegardé : {token_path}",
    },
    "connections.oauth_path_undetermined": {
        "en": "The OAuth client file path could not be determined.",
        "fr": "Le chemin du fichier client OAuth n'a pas pu être déterminé.",
    },
    "connections.expected_credentials_file": {
        "en": "Expected credentials file: {expected}",
        "fr": "Fichier d'identifiants attendu : {expected}",
    },
    "connections.file_does_not_exist": {
        "en": "That file does not exist, so Google was not contacted.",
        "fr": "Ce fichier n'existe pas, Google n'a donc pas été contacté.",
    },
    "connections.same_name_without_dot": {
        "en": "A file with the same name, without the leading dot, is here: {neighbor}",
        "fr": "Un fichier du même nom, sans le point initial, se trouve ici : {neighbor}",
    },
    "connections.only_reads_dot_name": {
        "en": "The program only reads the name that starts with a dot.",
        "fr": "Le programme ne lit que le nom qui commence par un point.",
    },
    "connections.no_client_json_found": {
        "en": "No client JSON was found under that name.",
        "fr": "Aucun JSON client n'a été trouvé sous ce nom.",
    },
    "connections.file_cannot_be_read": {
        "en": "The file cannot be read: {error_type}: {error}",
        "fr": "Le fichier ne peut pas être lu : {error_type} : {error}",
    },
    "connections.wrong_client_type": {
        "en": (
            "Google client type is 'web'. This program needs a Desktop app client, "
            "whose JSON starts with \"installed\"."
        ),
        "fr": (
            "Le type de client Google est 'web'. Ce programme a besoin d'un client "
            "d'application de bureau, dont le JSON commence par \"installed\"."
        ),
    },
    "connections.client_library_rejected": {
        "en": "Google client library rejected the file: {error_type}: {error}",
        "fr": "La bibliothèque client Google a rejeté le fichier : {error_type} : {error}",
    },
    "connections.consent_not_finished": {
        "en": (
            "The client file is readable, but the browser consent did not finish "
            "and no token was saved."
        ),
        "fr": (
            "Le fichier client est lisible, mais le consentement dans le navigateur ne s'est "
            "pas terminé et aucun jeton n'a été sauvegardé."
        ),
    },
    "connections.for_account": {
        "en": " for {user}",
        "fr": " pour {user}",
    },
    "connections.missing_calendar_message": {
        "en": (
            "Google Calendar is not authorized{account}.\n"
            "Create an OAuth desktop client in Google Cloud, with the Calendar API enabled, "
            "and save the downloaded JSON as:\n  {credential}\n"
            "Then run: uv run manage-agenda auth -i"
        ),
        "fr": (
            "Google Calendar n'est pas autorisé{account}.\n"
            "Créez un client OAuth d'application de bureau dans Google Cloud, avec l'API "
            "Calendar activée, et enregistrez le JSON téléchargé sous :\n  {credential}\n"
            "Puis exécutez : uv run manage-agenda auth -i"
        ),
    },
    "connections.no_calendars_found": {
        "en": "No calendars found in your Google Calendar account",
        "fr": "Aucun calendrier trouvé dans votre compte Google Calendar",
    },
    "connections.no_writable_calendars_found": {
        "en": "No writable calendars found. Check your calendar permissions.",
        "fr": "Aucun calendrier accessible en écriture. Vérifiez vos permissions de calendrier.",
    },
    "connections.non_interactive_message": {
        "en": (
            "No calendar configured for non-interactive use. Run with -i once (or "
            "--reconfigure) to choose one, or pass -d/--destination with a calendar id."
        ),
        "fr": (
            "Aucun calendrier configuré pour une utilisation non interactive. Exécutez avec -i "
            "une fois (ou --reconfigure) pour en choisir un, ou passez -d/--destination avec un "
            "identifiant de calendrier."
        ),
    },
    "connections.no_calendar_selected": {
        "en": "No calendar was selected.",
        "fr": "Aucun calendrier n'a été sélectionné.",
    },
    "connections.failed_to_select_calendar": {
        "en": "Failed to select calendar: {error}",
        "fr": "Échec de la sélection du calendrier : {error}",
    },
    "connections.unexpected_error_selecting_calendar": {
        "en": "Unexpected error selecting calendar: {error}",
        "fr": "Erreur inattendue lors de la sélection du calendrier : {error}",
    },
    # --- evaluation.py ---
    "evaluation.no_models_available": {
        "en": "No models available",
        "fr": "Aucun modèle disponible",
    },
    "evaluation.evaluating_model": {
        "en": "Evaluating model: {model_name}",
        "fr": "Évaluation du modèle : {model_name}",
    },
    "evaluation.cli_email_result": {
        "en": "Cli (email): {result}",
        "fr": "Cli (email) : {result}",
    },
    "evaluation.cli_web_result": {
        "en": "Cli (web): {result}",
        "fr": "Cli (web) : {result}",
    },
    "evaluation.cli_txt_result": {
        "en": "Cli (txt): {result}",
        "fr": "Cli (txt) : {result}",
    },
    "evaluation.prompt_label": {
        "en": "Prompt: {prompt}",
        "fr": "Prompt : {prompt}",
    },
    "evaluation.results_header": {
        "en": "\n--- Evaluation Results ---",
        "fr": "\n--- Résultats de l'évaluation ---",
    },
    "evaluation.result_model": {
        "en": "Model: {model}",
        "fr": "Modèle : {model}",
    },
    "evaluation.result_time_taken": {
        "en": "Time taken: {duration} seconds",
        "fr": "Temps écoulé : {duration} secondes",
    },
    "evaluation.result_response": {
        "en": "Response: {response}",
        "fr": "Réponse : {response}",
    },
    "evaluation.result_separator": {
        "en": "--------------------",
        "fr": "--------------------",
    },
    # --- web.py ---
    "web.orig_debug": {
        "en": "Orig: {result}",
        "fr": "Orig : {result}",
    },
    "web.end_orig_debug": {
        "en": "End Orig",
        "fr": "Fin Orig",
    },
    "web.res_debug": {
        "en": "Res: {result}",
        "fr": "Res : {result}",
    },
    "web.end_res_debug": {
        "en": "End Res",
        "fr": "Fin Res",
    },
    # --- interactive.py ---
    "interactive.comma_separated_selection": {
        "en": "Selection (comma-separated numbers)",
        "fr": "Sélection (numéros séparés par des virgules)",
    },
    # --- base.py ---
    "base.setting_logging": {
        "en": "Setting logging",
        "fr": "Configuration de la journalisation",
    },
    # --- sources.py ---
    "sources.first_n_lines_header": {
        "en": "First {n} lines of {content_type}",
        "fr": "Les {n} premières lignes de {content_type}",
    },
    "sources.section_header": {
        "en": "\n--- {header} ---",
        "fr": "\n--- {header} ---",
    },
    "sources.no_such_directory": {
        "en": "There is no {target_dir} directory",
        "fr": "Le répertoire {target_dir} n'existe pas",
    },
    "sources.no_posts_in_directory": {
        "en": "There are no posts in {target_dir}",
        "fr": "Il n'y a aucun message dans {target_dir}",
    },
    "sources.imap_not_connected": {
        "en": "IMAP is not connected",
        "fr": "IMAP n'est pas connecté",
    },
    "sources.could_not_open_folder": {
        "en": "Could not open {folder}",
        "fr": "Impossible d'ouvrir {folder}",
    },
    "sources.no_messages_match": {
        "en": "No messages match {criteria}",
        "fr": "Aucun message ne correspond à {criteria}",
    },
    "sources.skipped_handled_messages": {
        "en": "Skipped {skipped} message(s) already handled",
        "fr": "{skipped} message(s) déjà traité(s) ignoré(s)",
    },
    "sources.no_sender_rules": {
        "en": "No sender rules for {folder}. Nothing is read.",
        "fr": "Aucune règle d'expéditeur pour {folder}. Rien n'est lu.",
    },
    "sources.no_posts_with_label": {
        "en": "There are no posts tagged with label {folder}",
        "fr": "Aucun message étiqueté avec le label {folder}",
    },
    "sources.select_mail_account": {
        "en": "Select mail account",
        "fr": "Sélectionnez le compte de messagerie",
    },
    "sources.select_calendar_account": {
        "en": "Select calendar account",
        "fr": "Sélectionnez le compte de calendrier",
    },
    "sources.confirm_remove_label": {
        "en": "Do you want to remove the label from the email? (y/n): ",
        "fr": "Voulez-vous retirer l'étiquette de l'email ? (y/n) : ",
    },
    "sources.service_debug": {
        "en": "Service: {service}",
        "fr": "Service : {service}",
    },
    "sources.label_debug": {
        "en": "label: {label}",
        "fr": "label : {label}",
    },
    "sources.confirm_process_old_post": {
        "en": "The post has {days} days. Do you want to process it? (y/n): ",
        "fr": "Le message a {days} jours. Voulez-vous le traiter ? (y/n) : ",
    },
    "sources.too_old_skipping": {
        "en": "Too old ({days} days), skipping.",
        "fr": "Trop ancien ({days} jours), ignoré.",
    },
    "sources.processing_title": {
        "en": "Processing Title: {post_title}",
        "fr": "Traitement du titre : {post_title}",
    },
    "sources.stopping_scan": {
        "en": "Stopping this scan. Unfinished messages will be tried again.",
        "fr": "Arrêt de cette analyse. Les messages non terminés seront retentés.",
    },
    "sources.enter_filenames": {
        "en": "Enter filenames separated by spaces (leave empty to use {msg_txt_dir}): ",
        "fr": "Entrez les noms de fichiers séparés par des espaces (laissez vide pour utiliser {msg_txt_dir}) : ",
    },
    "sources.no_filenames_entered": {
        "en": "No filenames entered. Extracting texts from {msg_txt_dir}...",
        "fr": "Aucun nom de fichier saisi. Extraction des textes depuis {msg_txt_dir}...",
    },
    "sources.no_message_read_fix_calendar": {
        "en": "No message was read. Fix the calendar connection, then run the scan again.",
        "fr": "Aucun message n'a été lu. Corrigez la connexion au calendrier, puis relancez l'analyse.",
    },
    "sources.urls_debug": {
        "en": "Urls: {urls}",
        "fr": "URLs : {urls}",
    },
    "sources.no_posts_with_urls": {
        "en": "There are no posts with these urls {urls}",
        "fr": "Il n'y a aucun message pour ces URLs {urls}",
    },
    "sources.enter_urls": {
        "en": "Enter URLs separated by spaces (leave empty to use ~/notes): ",
        "fr": "Entrez les URLs séparées par des espaces (laissez vide pour utiliser ~/notes) : ",
    },
    "sources.no_urls_entered": {
        "en": "No URLs entered. Extracting links from ~/notes...",
        "fr": "Aucune URL saisie. Extraction des liens depuis ~/notes...",
    },
    "sources.no_links_found": {
        "en": "No links found in ~/notes.",
        "fr": "Aucun lien trouvé dans ~/notes.",
    },
    "sources.found_notes": {
        "en": "Found notes: {url_to_notes}",
        "fr": "Notes trouvées : {url_to_notes}",
    },
    "sources.found_total_links": {
        "en": "Found total of links: {count}",
        "fr": "Nombre total de liens trouvés : {count}",
    },
    "sources.found_links": {
        "en": "Found links: {urls}",
        "fr": "Liens trouvés : {urls}",
    },
    "sources.could_not_process_url": {
        "en": "Could not process {url}, skipping.",
        "fr": "Impossible de traiter {url}, ignoré.",
    },
    "sources.deleting_note": {
        "en": "Deleting note: {note_title}",
        "fr": "Suppression de la note : {note_title}",
    },
    "sources.selected_model": {
        "en": "Selected model: {model_name}",
        "fr": "Modèle sélectionné : {model_name}",
    },
    "sources.source_debug": {
        "en": "Source: {source}",
        "fr": "Source : {source}",
    },
    "sources.sources_of_information_title": {
        "en": "Sources of information",
        "fr": "Sources d'information",
    },
    "sources.selected_source": {
        "en": "Selected source: {selected}",
        "fr": "Source sélectionnée : {selected}",
    },
    # --- events.py ---
    "events.action_copy": {
        "en": "Copy",
        "fr": "Copier",
    },
    "events.action_delete": {
        "en": "Delete",
        "fr": "Supprimer",
    },
    "events.action_move": {
        "en": "Move",
        "fr": "Déplacer",
    },
    "events.all_option": {
        "en": "{index}) All",
        "fr": "{index}) Tout",
    },
    "events.copied_event": {
        "en": "Copied event: {summary}",
        "fr": "Événement copié : {summary}",
    },
    "events.could_not_parse_end_time": {
        "en": "Could not parse end time, using empty value",
        "fr": "Impossible d'analyser l'heure de fin, utilisation d'une valeur vide",
    },
    "events.could_not_parse_start_time": {
        "en": "Could not parse start time, using empty value",
        "fr": "Impossible d'analyser l'heure de début, utilisation d'une valeur vide",
    },
    "events.current_value": {
        "en": "Current: {value}",
        "fr": "Actuel : {value}",
    },
    "events.date_confirm_prompt": {
        "en": (
            "Are the dates correct? Ye(s), (r)etry with LLM, (Y)ear, (M)onth, (D)ay, (h)our, "
            "m(i)nute, (f)ull date/time: "
        ),
        "fr": (
            "Les dates sont-elles correctes ? Oui (s), (r)éessayer avec le LLM, (Y) année, "
            "(M) mois, (D) jour, (h) heure, m(i)nute, date/heure complète (f) : "
        ),
    },
    "events.date_label": {
        "en": "Date: {value}",
        "fr": "Date : {value}",
    },
    "events.datetime_input_prompt": {
        "en": "Enter new {field} time (YYYY-MM-DD HH:MM:SS) or leave empty: ",
        "fr": "Entrez la nouvelle heure {field} (AAAA-MM-JJ HH:MM:SS) ou laissez vide : ",
    },
    "events.default_end_time_prompt": {
        "en": "Default end time will be {new_end_str_default}. Do you want to modify it? (y/n): ",
        "fr": "L'heure de fin par défaut sera {new_end_str_default}. Voulez-vous la modifier ? (y/n) : ",
    },
    "events.deleted_event": {
        "en": "Deleted event: {summary}",
        "fr": "Événement supprimé : {summary}",
    },
    "events.end_label": {
        "en": "End: {value}",
        "fr": "Fin : {value}",
    },
    "events.end_not_after_start_warning": {
        "en": "Validation Warning: End time is not after start time. Adjusting end time.",
        "fr": (
            "Avertissement de validation : l'heure de fin n'est pas après l'heure de début. "
            "Ajustement de l'heure de fin."
        ),
    },
    "events.event_line": {
        "en": "- {title} ({date})",
        "fr": "- {title} ({date})",
    },
    "events.invalid_start_time_format": {
        "en": "Invalid start time format. Please use YYYY-MM-DD HH:MM:SS.",
        "fr": "Format d'heure de début invalide. Veuillez utiliser AAAA-MM-JJ HH:MM:SS.",
    },
    "events.invalid_value": {
        "en": "Invalid value: {error}. Keeping original time.",
        "fr": "Valeur invalide : {error}. Conservation de l'heure d'origine.",
    },
    "events.missing_start_or_end_datetime": {
        "en": "{label}Event is missing valid start or end dateTime",
        "fr": "{label}L'événement n'a pas de date/heure de début ou de fin valide",
    },
    "events.modifying_component": {
        "en": "\nModifying {component} for {time_label} time:",
        "fr": "\nModification de {component} pour l'heure {time_label} :",
    },
    "events.new_component_prompt": {
        "en": "New {component} ({current}): ",
        "fr": "Nouveau {component} ({current}) : ",
    },
    "events.new_time_label": {
        "en": "New {time_label} time: {value}",
        "fr": "Nouvelle heure {time_label} : {value}",
    },
    "events.no_busy_events_found": {
        "en": "No busy events found matching the criteria.",
        "fr": "Aucun événement occupé trouvé correspondant aux critères.",
    },
    "events.no_events_found": {
        "en": "No events found matching the criteria.",
        "fr": "Aucun événement trouvé correspondant aux critères.",
    },
    "events.no_title": {
        "en": "No Title",
        "fr": "Sans titre",
    },
    "events.not_available": {
        "en": "N/A",
        "fr": "N/A",
    },
    "events.select_calendar_title": {
        "en": "Select calendar",
        "fr": "Sélectionnez le calendrier",
    },
    "events.select_destination_calendar": {
        "en": "Select destination calendar",
        "fr": "Sélectionnez le calendrier de destination",
    },
    "events.select_events_to": {
        "en": "Select events to {action_verb}:",
        "fr": "Sélectionnez les événements à {action_verb} :",
    },
    "events.select_operation_title": {
        "en": "Select operation:",
        "fr": "Sélectionnez l'opération :",
    },
    "events.select_rule_lower_title": {
        "en": "Select rule",
        "fr": "Sélectionnez la règle",
    },
    "events.select_rule_title": {
        "en": "Select Rule",
        "fr": "Sélectionnez la règle",
    },
    "events.start_label": {
        "en": "Start: {value}",
        "fr": "Début : {value}",
    },
    "events.text_filter_prompt": {
        "en": "Text to filter by (leave empty for no filter): ",
        "fr": "Texte pour filtrer (laisser vide pour aucun filtre) : ",
    },
    "events.time_far_in_the_future": {
        "en": "{label}Event {field_name} time ({formatted_time}) is unreasonably far in the future (> 5 years)",
        "fr": (
            "{label}L'heure {field_name} de l'événement ({formatted_time}) est anormalement "
            "loin dans le futur (> 5 ans)"
        ),
    },
    "events.time_far_in_the_past": {
        "en": "{label}Event {field_name} time ({formatted_time}) is unreasonably far in the past (> 2 years)",
        "fr": (
            "{label}L'heure {field_name} de l'événement ({formatted_time}) est anormalement "
            "loin dans le passé (> 2 ans)"
        ),
    },
    "events.unknown_component": {
        "en": "Unknown component: {component}. Keeping original time.",
        "fr": "Composant inconnu : {component}. Conservation de l'heure d'origine.",
    },
    "events.upcoming_events_title": {
        "en": "Upcoming events (up to 20):",
        "fr": "Événements à venir (jusqu'à 20) :",
    },
    "events.updated_status_available": {
        "en": "Updated event status to available: {title}",
        "fr": "Statut de l'événement mis à jour sur disponible : {title}",
    },
    "events.updated_times_footer": {
        "en": "---------------------------",
        "fr": "---------------------------",
    },
    "events.updated_times_header": {
        "en": "--- Updated Event Times ---",
        "fr": "--- Heures de l'événement mises à jour ---",
    },
    "events.warning_prefix": {
        "en": "WARNING: {warning}",
        "fr": "AVERTISSEMENT : {warning}",
    },
    "events.which_events_prompt": {
        "en": "Which event(s) to {action_verb}? (comma-separated numbers, text to match, or 'all') ",
        "fr": "Quel(s) événement(s) {action_verb} ? (numéros séparés par des virgules, texte à rechercher, ou 'all') ",
    },
    # --- extraction.py ---
    "extraction.paste_text_prompt": {
        "en": "Paste the relevant part of the text here (finish with Ctrl-D):",
        "fr": "Collez ici la partie pertinente du texte (terminez avec Ctrl-D) :",
    },
    "extraction.source_text_content_type": {
        "en": "source text",
        "fr": "texte source",
    },
    "extraction.calling_llm": {
        "en": "Calling LLM {model}",
        "fr": "Appel du LLM {model}",
    },
    "extraction.llm_api_error": {
        "en": "LLM API error: {error}",
        "fr": "Erreur de l'API du LLM : {error}",
    },
    "extraction.ai_call_took": {
        "en": "AI call took {duration} ({seconds} seconds)",
        "fr": "L'appel à l'IA a pris {duration} ({seconds} secondes)",
    },
    "extraction.failed_to_get_response": {
        "en": "Failed to get response from LLM.",
        "fr": "Échec de la récupération de la réponse du LLM.",
    },
    "extraction.llm_insufficient_memory": {
        "en": (
            "LLM failed due to insufficient memory. Model requires more "
            "system memory than available."
        ),
        "fr": (
            "Le LLM a échoué par manque de mémoire. Le modèle nécessite plus de mémoire "
            "système que disponible."
        ),
    },
    "extraction.title_reply": {
        "en": "Reply",
        "fr": "Réponse",
    },
    "extraction.title_json": {
        "en": "Json",
        "fr": "Json",
    },
    "extraction.switching_llm_memory": {
        "en": "Switching to a different LLM due to memory constraints...",
        "fr": "Changement de LLM en raison de contraintes de mémoire...",
    },
    "extraction.trying_lighter_model": {
        "en": "Trying to switch to a lighter model automatically...",
        "fr": "Tentative de passage automatique à un modèle plus léger...",
    },
    "extraction.source_debug": {
        "en": "Source: {source}",
        "fr": "Source : {source}",
    },
    "extraction.selected_new_ai_model": {
        "en": "Selected new AI model: {model}",
        "fr": "Nouveau modèle d'IA sélectionné : {model}",
    },
    "extraction.switched_lighter_ai_model": {
        "en": "Switched to lighter AI model: {model}",
        "fr": "Passage à un modèle d'IA plus léger : {model}",
    },
    "extraction.no_alternative_model": {
        "en": "No alternative model selected. Skipping event processing.",
        "fr": "Aucun modèle alternatif sélectionné. Traitement de l'événement ignoré.",
    },
    "extraction.could_not_switch_model": {
        "en": "Could not switch to a lighter model. Skipping event processing.",
        "fr": "Impossible de passer à un modèle plus léger. Traitement de l'événement ignoré.",
    },
    "extraction.json_generation_error": {
        "en": "Error in generated Json...",
        "fr": "Erreur dans le Json généré...",
    },
    "extraction.max_retries_reached": {
        "en": "Max retries reached. Skipping event processing.",
        "fr": "Nombre maximal de tentatives atteint. Traitement de l'événement ignoré.",
    },
    "extraction.title_prompt": {
        "en": "Prompt",
        "fr": "Prompt",
    },
    "extraction.title_event": {
        "en": "Event",
        "fr": "Événement",
    },
    "extraction.title_single_event": {
        "en": "Single event",
        "fr": "Événement unique",
    },
    "extraction.title_proc_event": {
        "en": "Proc event",
        "fr": "Événement traité",
    },
    "extraction.llm_failed_extract": {
        "en": "\nLLM failed to extract event information.",
        "fr": "\nLe LLM n'a pas réussi à extraire les informations de l'événement.",
    },
    "extraction.retry_options_prompt": {
        "en": "Options: (r)etry, (p)rovide relevant text snippet, (s)kip item: ",
        "fr": "Options : (r)éessayer, (p)fournir un extrait de texte pertinent, (s)ignorer l'élément : ",
    },
    "extraction.display_summary": {
        "en": "Summary: {summary}",
        "fr": "Résumé : {summary}",
    },
    "extraction.display_file": {
        "en": "File: {post_identifier}",
        "fr": "Fichier : {post_identifier}",
    },
    "extraction.display_start": {
        "en": "Start: {start}",
        "fr": "Début : {start}",
    },
    "extraction.display_end": {
        "en": "End: {end}",
        "fr": "Fin : {end}",
    },
    "extraction.display_model": {
        "en": "Model: {model}",
        "fr": "Modèle : {model}",
    },
    "extraction.display_time": {
        "en": "Time: {duration} ({seconds} seconds)",
        "fr": "Temps : {duration} ({seconds} secondes)",
    },
    "extraction.max_date_validation_retries_reached": {
        "en": (
            "Max date validation retries ({max_retries}) "
            "reached for {post_identifier}. Skipping event processing."
        ),
        "fr": (
            "Nombre maximal de tentatives de validation de date ({max_retries}) atteint pour "
            "{post_identifier}. Traitement de l'événement ignoré."
        ),
    },
    "extraction.model_api_no_answer": {
        "en": "The model API did not answer. This message stays pending.",
        "fr": "L'API du modèle n'a pas répondu. Ce message reste en attente.",
    },
    "extraction.no_visit_fits": {
        "en": "No visit fits the hours, the weekdays, and the next room occupation.",
        "fr": "Aucune visite ne correspond aux horaires, aux jours de la semaine et à la prochaine occupation de la salle.",
    },
    "extraction.event_fallback_title": {
        "en": "Event",
        "fr": "Événement",
    },
    "extraction.no_calendar_selected": {
        "en": "No calendar selected, skipping event creation.",
        "fr": "Aucun calendrier sélectionné, création de l'événement ignorée.",
    },
    "extraction.date_validation_errors_header": {
        "en": "Date validation errors for {post_identifier}:",
        "fr": "Erreurs de validation de date pour {post_identifier} :",
    },
    "extraction.calendar_not_updated": {
        "en": "The calendar was not updated. This message stays pending.",
        "fr": "Le calendrier n'a pas été mis à jour. Ce message reste en attente.",
    },
    "extraction.already_on_calendar": {
        "en": "Already on the calendar, skipped: {summary}",
        "fr": "Déjà présent dans le calendrier, ignoré : {summary}",
    },
    "extraction.calendar_event_created": {
        "en": "Calendar event created",
        "fr": "Événement de calendrier créé",
    },
    "extraction.file_created": {
        "en": "File {filename} created",
        "fr": "Fichier {filename} créé",
    },
    "extraction.success_debug": {
        "en": "Success: {success}",
        "fr": "Succès : {success}",
    },
    "extraction.events_debug": {
        "en": "Events: {events}",
        "fr": "Événements : {events}",
    },
    "extraction.results_debug": {
        "en": "Results: {results}",
        "fr": "Résultats : {results}",
    },
    "extraction.select_calendar_title": {
        "en": "Select Calendar",
        "fr": "Sélectionnez le calendrier",
    },
    "extraction.visit_title": {
        # The original source hardcoded the French word "Visite" here regardless of language -
        # a latent bug (the room-visit feature's prompt title never actually said "Visit" in
        # English), fixed here rather than preserved, since nothing depends on that literal.
        "en": "Visit",
        "fr": "Visite",
    },
}
