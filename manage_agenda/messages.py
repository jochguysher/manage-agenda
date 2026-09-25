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
    "cli.add.dry_run_ledger_help": {
        "en": (
            "Preview deleted-event reconciliation, legacy-event migration, and ledger "
            "purging without writing them (scoped to the ledger only - scanning/"
            "extraction/publishing/mailbox marking still run normally, so this is NOT a safe "
            "preview; use 'reconcile --dry-run-ledger' for that)"
        ),
        "fr": (
            "Prévisualise la réconciliation des événements supprimés, la migration des "
            "événements existants et la purge du registre sans les écrire (limité au "
            "registre - l'analyse, l'extraction, la publication et le marquage des messages "
            "s'exécutent normalement : ce n'est PAS une prévisualisation sûre, utilisez "
            "« reconcile --dry-run-ledger » pour cela)"
        ),
    },
    "cli.add.debug_log_extractions_help": {
        "en": (
            "Write per-message debug artifacts (raw LLM prompt/response, extracted event "
            "JSON - plaintext, includes message content) under MSG_TXT_DIR/log/. Off by "
            "default: nothing is written there at all unless this is passed. When on, "
            "files are created 0600 and directories 0700, and old ones are purged per "
            "--debug-log-retention-days on each run"
        ),
        "fr": (
            "Écrit des artefacts de débogage par message (prompt/réponse LLM bruts, JSON "
            "de l'événement extrait - texte en clair, contient le contenu du message) sous "
            "MSG_TXT_DIR/log/. Désactivé par défaut : rien n'y est écrit sans cette option. "
            "Une fois activé, les fichiers sont créés en 0600 et les dossiers en 0700, et "
            "les anciens sont purgés selon --debug-log-retention-days à chaque exécution"
        ),
    },
    "cli.add.debug_log_retention_days_help": {
        "en": "How many days to keep --debug-log-extractions files before purging them",
        "fr": "Nombre de jours de conservation des fichiers de --debug-log-extractions avant purge",
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
    "cli.restore.help": {
        "en": (
            "Manually attempt to restore a manually-deleted event (identity from "
            "'restore --list'). Never automatic - see on_user_delete."
        ),
        "fr": (
            "Tente manuellement de restaurer un événement supprimé manuellement "
            "(identité obtenue via « restore --list »). Jamais automatique - voir on_user_delete."
        ),
    },
    "cli.restore.list_help": {
        "en": "List identities with a deleted event that could be restored",
        "fr": "Lister les identités ayant un événement supprimé restaurable",
    },
    "cli.restore.identity_required": {
        "en": "An identity is required (see 'restore --list' to find one)",
        "fr": "Une identité est requise (voir « restore --list » pour en trouver une)",
    },
    "cli.migrate_ledger.help": {
        "en": (
            "Migrate the ledger's existing Calendar events for the configured calendar "
            "account (extendedProperties + event end date). Until this has run once for an "
            "account, 'add' skips ledger reconcile and purge."
        ),
        "fr": (
            "Migre les événements Calendar existants du registre pour le compte de calendrier "
            "configuré (extendedProperties + date de fin). Tant que cette commande n'a pas été "
            "exécutée une fois pour un compte, « add » saute la réconciliation et la purge du "
            "registre."
        ),
    },
    "cli.migrate_ledger.dry_run_ledger_help": {
        "en": (
            "Preview only: read the events and log what would be migrated, without patching "
            "any event, writing the ledger, or marking the account as migrated"
        ),
        "fr": (
            "Prévisualisation uniquement : lit les événements et journalise ce qui serait "
            "migré, sans modifier aucun événement, sans écrire le registre et sans marquer le "
            "compte comme migré"
        ),
    },
    "cli.ledger_account_interactive_help": {
        "en": (
            "Choose the calendar account, even when one is saved. The saved account is never "
            "changed"
        ),
        "fr": (
            "Choisir le compte de calendrier, même si un compte est sauvegardé. Le compte "
            "sauvegardé n'est jamais modifié"
        ),
    },
    "cli.reconcile.help": {
        "en": (
            "Run only the ledger side of 'add' for the configured calendar account: Calendar "
            "sync, deleted-event reconciliation, migration retries and ledger purge. No mailbox "
            "is read, nothing is extracted, published or marked. Requires 'migrate-ledger' to "
            "have run once for the account."
        ),
        "fr": (
            "N'exécute que la partie registre de « add » pour le compte de calendrier "
            "configuré : synchronisation Calendar, réconciliation des événements supprimés, "
            "reprise de la migration et purge du registre. Aucune boîte aux lettres n'est lue, "
            "rien n'est extrait, publié ni marqué. Nécessite que « migrate-ledger » ait été "
            "exécuté une fois pour ce compte."
        ),
    },
    "cli.reconcile.dry_run_ledger_help": {
        "en": (
            "Preview only: make the same read-only Calendar calls and log what would change, "
            "without writing the ledger, its .bak, or the Calendar sync tokens"
        ),
        "fr": (
            "Prévisualisation uniquement : effectue les mêmes appels Calendar en lecture seule "
            "et journalise ce qui changerait, sans écrire le registre, sa copie .bak ni les "
            "jetons de synchronisation Calendar"
        ),
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
    "connections.calendar_account_choice_required": {
        "en": (
            "Several calendar accounts are configured ({accounts}) and none is saved: run "
            "with -i to choose the one to work on. Nothing was connected."
        ),
        "fr": (
            "Plusieurs comptes de calendrier sont configurés ({accounts}) et aucun n'est "
            "sauvegardé : relancez avec -i pour choisir celui à traiter. Aucune connexion "
            "n'a été ouverte."
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
    "sources.restore_list_entry": {
        "en": "{identity}: {event_ids}",
        "fr": "{identity} : {event_ids}",
    },
    "sources.restore_list_empty": {
        "en": "No identity has a deleted event that could be restored",
        "fr": "Aucune identité n'a d'événement supprimé restaurable",
    },
    "sources.restore_unknown_identity": {
        "en": "{identity}: unknown identity (see 'restore --list')",
        "fr": "{identity} : identité inconnue (voir « restore --list »)",
    },
    "sources.restore_nothing_to_restore": {
        "en": "{identity}: no deleted event to restore for this identity",
        "fr": "{identity} : aucun événement supprimé à restaurer pour cette identité",
    },
    "sources.restore_select_calendar_title": {
        "en": "Select the calendar to restore the event on",
        "fr": "Sélectionnez le calendrier sur lequel restaurer l'événement",
    },
    "sources.restore_succeeded": {
        "en": "Restored {event_id} on {calendar_id}",
        "fr": "Événement {event_id} restauré sur {calendar_id}",
    },
    "sources.restore_failed": {
        "en": "Could not restore {event_id} on {calendar_id}",
        "fr": "Impossible de restaurer {event_id} sur {calendar_id}",
    },
    "sources.restore_failed_hint": {
        "en": (
            "Calendar did not confirm the restore - this is a known unknown (see "
            "docs/investigation-limite1.md, probe b). Use requeue to recreate the event "
            "under a new id instead."
        ),
        "fr": (
            "Calendar n'a pas confirmé la restauration - c'est une inconnue documentée (voir "
            "docs/investigation-limite1.md, sonde b). Utilisez requeue pour recréer "
            "l'événement sous un nouvel identifiant à la place."
        ),
    },
    "sources.marker_migration_required": {
        "en": (
            "Refusing to scan {account}: it was previously marked with 'mark: seen' and is "
            "now configured for {mode} mode. Switching without first migrating already-marked "
            "messages (see docs/investigation-limite1.md §6, not yet implemented) risks "
            "recreating events as duplicates. Revert processed_marker, or apply the {mode} "
            "marker to every message still tracked in the ledger by hand before retrying."
        ),
        "fr": (
            "Analyse de {account} refusée : ce compte était marqué avec « mark: seen » et est "
            "maintenant configuré en mode {mode}. Changer sans d'abord migrer les messages "
            "déjà marqués (voir docs/investigation-limite1.md §6, non implémentée) risque de "
            "recréer des événements en double. Revenez à processed_marker précédent, ou "
            "appliquez manuellement le marqueur {mode} à chaque message encore suivi dans le "
            "ledger avant de réessayer."
        ),
    },
    "sources.ledger_migration_required": {
        "en": (
            "Ledger reconcile and purge skipped: the ledger has not been migrated yet for "
            "calendar account {account}. Preview with 'manage-agenda migrate-ledger "
            "--dry-run-ledger', then run 'manage-agenda migrate-ledger'. Already-handled "
            "messages are still skipped."
        ),
        "fr": (
            "Réconciliation et purge du registre sautées : le registre n'a pas encore été "
            "migré pour le compte de calendrier {account}. Prévisualisez avec « manage-agenda "
            "migrate-ledger --dry-run-ledger », puis lancez « manage-agenda migrate-ledger ». "
            "Les messages déjà traités restent ignorés."
        ),
    },
    "sources.migrate_ledger_no_calendar": {
        "en": "No calendar account available - nothing migrated, account not marked as migrated.",
        "fr": "Aucun compte de calendrier disponible - rien n'a été migré, compte non marqué comme migré.",
    },
    "sources.migrate_ledger_calendar_list_failed": {
        "en": (
            "Could not read the calendar list of calendar account {account} - nothing migrated, "
            "account not marked as migrated. Check the connection ('manage-agenda auth') and "
            "retry."
        ),
        "fr": (
            "Impossible de lire la liste des calendriers du compte {account} - rien n'a été "
            "migré, compte non marqué comme migré. Vérifiez la connexion (« manage-agenda "
            "auth ») et réessayez."
        ),
    },
    "sources.migrate_ledger_dry_run_done": {
        "en": (
            "DRY RUN for calendar account {account}: {count} event(s) would be migrated or are "
            "already migrated; {skipped} left alone (another account, or a calendar this "
            "account can't see - retried later); {attached} legacy 'primary' ref(s) would be "
            "attached to this account. Nothing was written and the account is not marked as "
            "migrated. Details: {log_file}"
        ),
        "fr": (
            "SIMULATION pour le compte de calendrier {account} : {count} événement(s) seraient "
            "migrés ou le sont déjà ; {skipped} laissés de côté (autre compte, ou calendrier "
            "invisible depuis ce compte - retentés plus tard) ; {attached} référence(s) "
            "« primary » anciennes seraient rattachées à ce compte. Rien n'a été écrit et le "
            "compte n'est pas marqué comme migré. Détails : {log_file}"
        ),
    },
    "sources.migrate_ledger_done": {
        "en": (
            "Ledger migrated for calendar account {account}: {count} event(s) migrated or "
            "already migrated; {skipped} left alone (another account, or a calendar this "
            "account can't see - retried later); {attached} legacy 'primary' ref(s) attached "
            "to this account. 'add' now runs ledger reconcile and purge automatically for this "
            "account. Details: {log_file}"
        ),
        "fr": (
            "Registre migré pour le compte de calendrier {account} : {count} événement(s) "
            "migrés ou déjà migrés ; {skipped} laissés de côté (autre compte, ou calendrier "
            "invisible depuis ce compte - retentés plus tard) ; {attached} référence(s) "
            "« primary » anciennes rattachées à ce compte. « add » réconcilie et purge "
            "désormais le registre automatiquement pour ce compte. Détails : {log_file}"
        ),
    },
    "sources.reconcile_no_calendar": {
        "en": "No calendar account available - nothing reconciled.",
        "fr": "Aucun compte de calendrier disponible - rien n'a été réconcilié.",
    },
    "sources.reconcile_migration_required": {
        "en": (
            "Nothing reconciled: the ledger has not been migrated yet for calendar account "
            "{account}. Preview with 'manage-agenda migrate-ledger --dry-run-ledger', then run "
            "'manage-agenda migrate-ledger'."
        ),
        "fr": (
            "Rien n'a été réconcilié : le registre n'a pas encore été migré pour le compte de "
            "calendrier {account}. Prévisualisez avec « manage-agenda migrate-ledger "
            "--dry-run-ledger », puis lancez « manage-agenda migrate-ledger »."
        ),
    },
    "sources.reconcile_dry_run_done": {
        "en": (
            "DRY RUN for calendar account {account}: reconcile ran on Calendar's answers; "
            "{migrated} event(s) would be migrated or are already migrated; {purged} ledger "
            "entry(ies) would be purged. Nothing was written (ledger, .bak, sync tokens). "
            "Each would-be change is logged with a 'DRY RUN' prefix in {log_file}"
        ),
        "fr": (
            "SIMULATION pour le compte de calendrier {account} : réconciliation calculée sur "
            "les réponses de Calendar ; {migrated} événement(s) seraient migrés ou le sont "
            "déjà ; {purged} entrée(s) du registre seraient purgées. Rien n'a été écrit "
            "(registre, .bak, jetons de synchronisation). Chaque changement prévu est "
            "journalisé avec le préfixe « DRY RUN » dans {log_file}"
        ),
    },
    "sources.reconcile_done": {
        "en": (
            "Ledger reconciled for calendar account {account}: {migrated} event(s) migrated or "
            "already migrated; {purged} ledger entry(ies) purged. Details: {log_file}"
        ),
        "fr": (
            "Registre réconcilié pour le compte de calendrier {account} : {migrated} "
            "événement(s) migrés ou déjà migrés ; {purged} entrée(s) du registre purgées. "
            "Détails : {log_file}"
        ),
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
        "en": "Cleaning after the occupation",
        "fr": "Entretien après l'occupation",
    },
    # --- UI port: prompts that used to be inline input()/select_from_list calls ---
    "cli.gui.help": {
        "en": "Open the desktop window (needs the 'gui' extra: pip install 'manage-agenda[gui]')",
        "fr": "Ouvre la fenêtre de bureau (nécessite l'extra 'gui' : pip install 'manage-agenda[gui]')",
    },
    "cli.gui.not_installed": {
        "en": (
            "The desktop window needs PySide6, which is not installed: "
            "pip install 'manage-agenda[gui]' ({error})"
        ),
        "fr": (
            "La fenêtre de bureau nécessite PySide6, qui n'est pas installé : "
            "pip install 'manage-agenda[gui]' ({error})"
        ),
    },
    "cli.install.failed": {
        "en": "Browser installation failed (exit code {code}).",
        "fr": "L'installation du navigateur a échoué (code de sortie {code}).",
    },
    "llm.starting_ollama": {
        "en": "Ollama is not running; starting `ollama serve`...",
        "fr": "Ollama ne tourne pas ; lancement de `ollama serve`...",
    },
    "llm.ollama_unreachable": {
        "en": "Could not reach Ollama after starting it: {error}",
        "fr": "Impossible de joindre Ollama après l'avoir lancé : {error}",
    },
    "llm.no_ollama_models": {
        "en": "Ollama has no models installed (try `ollama pull <model>`).",
        "fr": "Ollama n'a aucun modèle installé (essayez `ollama pull <modèle>`).",
    },
    "llm.no_model_selected": {
        "en": "No model selected.",
        "fr": "Aucun modèle sélectionné.",
    },
    "connections.selected_rule": {
        "en": "Selected rule: {rule}",
        "fr": "Règle sélectionnée : {rule}",
    },
    "extraction.action_retry": {
        "en": "Retry with the same text",
        "fr": "Réessayer avec le même texte",
    },
    "extraction.action_provide_snippet": {
        "en": "Provide a text snippet for the LLM to focus on",
        "fr": "Fournir un extrait de texte sur lequel le LLM doit se concentrer",
    },
    "extraction.action_skip": {
        "en": "Skip this item",
        "fr": "Ignorer cet élément",
    },
    # --- gui: the desktop window (manage_agenda.gui) and its dialogs ---
    'events.review_title': {
        "en": 'Review the event',
        "fr": "Relire l'événement",
    },
    'events.review_summary': {
        "en": 'Title',
        "fr": 'Titre',
    },
    'events.review_location': {
        "en": 'Location',
        "fr": 'Lieu',
    },
    'events.review_description': {
        "en": 'Description',
        "fr": 'Description',
    },
    'events.review_start': {
        "en": 'Start (local time)',
        "fr": 'Début (heure locale)',
    },
    'events.review_end': {
        "en": 'End (local time)',
        "fr": 'Fin (heure locale)',
    },
    'events.review_datetime_hint': {
        "en": 'Format: {format}',
        "fr": 'Format : {format}',
    },
    'events.review_accept': {
        "en": 'Accept',
        "fr": 'Accepter',
    },
    'events.review_retry': {
        "en": 'Ask the model again',
        "fr": 'Redemander au modèle',
    },
    'events.review_invalid_datetime': {
        "en": 'Start and end must follow the format {format}.',
        "fr": 'Le début et la fin doivent suivre le format {format}.',
    },
    'gui.window_title': {
        "en": 'manage-agenda',
        "fr": 'manage-agenda',
    },
    'gui.nav.add': {
        "en": 'Add (advanced)',
        "fr": 'Ajouter (avancé)',
    },
    'gui.nav.calendar_ops': {
        "en": 'Calendar operations',
        "fr": 'Opérations sur le calendrier',
    },
    'gui.nav.ledger': {
        "en": 'Ledger',
        "fr": 'Registre',
    },
    'gui.nav.evaluate': {
        "en": 'Evaluate models',
        "fr": 'Évaluer les modèles',
    },
    'gui.nav.auth': {
        "en": 'Authentication',
        "fr": 'Authentification',
    },
    'gui.nav.lists': {
        "en": 'Lists',
        "fr": 'Listes',
    },
    'gui.nav.install': {
        "en": 'Install browser',
        "fr": 'Installer le navigateur',
    },
    'gui.nav.settings': {
        "en": 'Settings',
        "fr": 'Réglages',
    },
    'gui.nav.unknown': {
        "en": 'Screen',
        "fr": 'Écran',
    },
    'gui.menu.view': {
        "en": '&View',
        "fr": '&Affichage',
    },
    'gui.menu.theme': {
        "en": '&Theme',
        "fr": '&Thème',
    },
    'gui.theme.light': {
        "en": 'Light',
        "fr": 'Clair',
    },
    'gui.theme.dark': {
        "en": 'Dark',
        "fr": 'Sombre',
    },
    'gui.theme.system': {
        "en": 'System',
        "fr": 'Système',
    },
    'gui.log_panel_title': {
        "en": 'Log',
        "fr": 'Journal',
    },
    'gui.run': {
        "en": 'Run',
        "fr": 'Lancer',
    },
    'gui.cancel': {
        "en": 'Cancel',
        "fr": 'Annuler',
    },
    'gui.cancel_tooltip': {
        "en": 'Stops the running job at its next question. A call in progress (model, mailbox, browser consent) is not interrupted.',
        "fr": "Arrête le job en cours à sa prochaine question. Un appel en cours (modèle, boîte mail, consentement navigateur) n'est pas interrompu.",
    },
    'gui.job_busy': {
        "en": 'A job is already running.',
        "fr": 'Un job est déjà en cours.',
    },
    'gui.job_started': {
        "en": 'Running: {name}',
        "fr": 'En cours : {name}',
    },
    'gui.job_finished': {
        "en": 'Done.',
        "fr": 'Terminé.',
    },
    'gui.job_finished_with_code': {
        "en": 'Done with exit code {code}.',
        "fr": 'Terminé avec le code {code}.',
    },
    'gui.job_failed': {
        "en": 'Failed: {error}',
        "fr": 'Échec : {error}',
    },
    'gui.job_failed_title': {
        "en": 'The job failed',
        "fr": 'Le job a échoué',
    },
    'gui.job_cancelled': {
        "en": 'Cancelled.',
        "fr": 'Annulé.',
    },
    'gui.close_while_running': {
        "en": 'A job is still running. Close anyway? It stops at its next question; a call in progress finishes on its own.',
        "fr": "Un job est encore en cours. Fermer quand même ? Il s'arrête à sa prochaine question ; un appel en cours se termine seul.",
    },
    'gui.close_job_still_running': {
        "en": 'The job is still inside a call that cannot be interrupted; close again once it returns.',
        "fr": "Le job est encore dans un appel qu'on ne peut pas interrompre ; refermez une fois qu'il aura rendu la main.",
    },
    'gui.port_called_outside_job': {
        "en": 'A prompt was requested on the GUI thread: core code must run through the job runner.',
        "fr": "Une question a été demandée sur le thread de l'interface : le cœur doit passer par le lanceur de jobs.",
    },
    'gui.dialog.choose_one_title': {
        "en": 'Choose one',
        "fr": 'Choisissez',
    },
    'gui.dialog.choose_many_title': {
        "en": 'Choose one or more',
        "fr": 'Choisissez un ou plusieurs',
    },
    'gui.dialog.confirm_title': {
        "en": 'Confirm',
        "fr": 'Confirmer',
    },
    'gui.dialog.ask_text_title': {
        "en": 'Input',
        "fr": 'Saisie',
    },
    'gui.dialog.ask_multiline_title': {
        "en": 'Text',
        "fr": 'Texte',
    },
    'gui.dialog.ask_multiline_hint': {
        "en": 'Leave empty to give nothing.',
        "fr": 'Laissez vide pour ne rien fournir.',
    },
    'gui.dialog.action_title': {
        "en": 'What next?',
        "fr": 'Que faire ?',
    },
    'gui.dialog.select_events_title': {
        "en": 'Select events',
        "fr": 'Sélectionnez des événements',
    },
    'gui.dialog.select_all': {
        "en": 'Select all',
        "fr": 'Tout sélectionner',
    },
    'gui.dialog.select_none': {
        "en": 'Select none',
        "fr": 'Tout désélectionner',
    },
    'gui.dialog.ok': {
        "en": 'OK',
        "fr": 'OK',
    },
    'gui.dialog.cancel': {
        "en": 'Cancel',
        "fr": 'Annuler',
    },
    'gui.dialog.yes': {
        "en": 'Yes',
        "fr": 'Oui',
    },
    'gui.dialog.no': {
        "en": 'No',
        "fr": 'Non',
    },
    'gui.lists.service': {
        "en": 'Service',
        "fr": 'Service',
    },
    'gui.lists.account': {
        "en": 'Account',
        "fr": 'Compte',
    },
    'gui.lists.refresh': {
        "en": 'Fetch',
        "fr": 'Charger',
    },
    'gui.lists.job': {
        "en": 'Listing',
        "fr": 'Listage',
    },
    'gui.lists.column_title': {
        "en": 'Title',
        "fr": 'Titre',
    },
    'gui.lists.column_date': {
        "en": 'Date',
        "fr": 'Date',
    },
    'gui.lists.empty': {
        "en": 'Nothing to show.',
        "fr": 'Rien à afficher.',
    },
    'gui.lists.no_account': {
        "en": 'No account configured for this service (see ~/.mySocial/config/.rssBlogs).',
        "fr": 'Aucun compte configuré pour ce service (voir ~/.mySocial/config/.rssBlogs).',
    },
    'gui.auth.service': {
        "en": 'Service',
        "fr": 'Service',
    },
    'gui.auth.account': {
        "en": 'Account',
        "fr": 'Compte',
    },
    'gui.auth.check': {
        "en": 'Check',
        "fr": 'Vérifier',
    },
    'gui.auth.run_oauth': {
        "en": 'Authorize in the browser',
        "fr": 'Autoriser dans le navigateur',
    },
    'gui.auth.job_check': {
        "en": 'Authentication check',
        "fr": "Vérification de l'authentification",
    },
    'gui.auth.job_oauth': {
        "en": 'Browser consent',
        "fr": 'Consentement navigateur',
    },
    'gui.auth.browser_note': {
        "en": 'Authorizing opens your browser; the window waits until the consent is finished and cannot cancel it.',
        "fr": "L'autorisation ouvre votre navigateur ; la fenêtre attend la fin du consentement et ne peut pas l'annuler.",
    },
    'gui.auth.status_ok': {
        "en": 'Authorized.',
        "fr": 'Autorisé.',
    },
    'gui.auth.status_failed': {
        "en": 'Not authorized.',
        "fr": 'Non autorisé.',
    },
    'gui.auth.no_account': {
        "en": 'No account configured for this service.',
        "fr": 'Aucun compte configuré pour ce service.',
    },
    # --- gui: the Add and Settings screens ---
    'gui.add.source': {
        "en": 'Source',
        "fr": 'Source',
    },
    'gui.add.urls': {
        "en": 'URLs',
        "fr": 'URL',
    },
    'gui.add.urls_placeholder': {
        "en": 'Space-separated URLs; empty: the links found in ~/notes',
        "fr": 'URL séparées par des espaces ; vide : les liens trouvés dans ~/notes',
    },
    'gui.add.files': {
        "en": 'Files',
        "fr": 'Fichiers',
    },
    'gui.add.files_placeholder': {
        "en": 'Space-separated file names; empty: every .txt in the text directory',
        "fr": 'Noms de fichiers séparés par des espaces ; vide : tous les .txt du dossier texte',
    },
    'gui.add.model_box': {
        "en": 'Model',
        "fr": 'Modèle',
    },
    'gui.add.provider': {
        "en": 'Provider',
        "fr": 'Fournisseur',
    },
    'gui.add.model': {
        "en": 'Model name',
        "fr": 'Nom du modèle',
    },
    'gui.add.saved_or_default': {
        "en": '(saved configuration, or default)',
        "fr": '(configuration enregistrée, ou défaut)',
    },
    'gui.add.calendars': {
        "en": 'Destination calendars',
        "fr": 'Calendriers de destination',
    },
    'gui.add.account': {
        "en": 'Account',
        "fr": 'Compte',
    },
    'gui.add.load_calendars': {
        "en": 'Load calendars…',
        "fr": 'Charger les calendriers…',
    },
    'gui.add.calendars_note': {
        "en": 'Check the calendars to write to. None checked: the saved choice is used, or you are asked when the run starts.',
        "fr": 'Cochez les calendriers à alimenter. Aucun coché : le choix enregistré est utilisé, ou la question est posée au lancement.',
    },
    'gui.add.calendars_none': {
        "en": 'No calendar chosen: the saved choice is used, or you are asked when the run starts.',
        "fr": 'Aucun calendrier choisi : le choix enregistré est utilisé, ou la question est posée au lancement.',
    },
    'gui.add.calendars_chosen': {
        "en": 'Calendars: {names}',
        "fr": 'Calendriers : {names}',
    },
    'gui.add.advanced_options': {
        "en": 'Advanced options',
        "fr": 'Options avancées',
    },
    'gui.add.no_calendar_account': {
        "en": 'No calendar account configured.',
        "fr": 'Aucun compte de calendrier configuré.',
    },
    'gui.add.job_calendars': {
        "en": 'Loading calendars',
        "fr": 'Chargement des calendriers',
    },
    'gui.add.options': {
        "en": 'Options',
        "fr": 'Options',
    },
    'gui.add.output': {
        "en": 'Output',
        "fr": 'Sortie',
    },
    'gui.add.rule_mode': {
        "en": 'IMAP rule mode',
        "fr": 'Mode de règle IMAP',
    },
    'gui.add.rule_default': {
        "en": '(default)',
        "fr": '(défaut)',
    },
    'gui.add.dry_run_ledger': {
        "en": 'Dry-run the ledger maintenance (reconcile, migrate, purge)',
        "fr": 'Simuler la maintenance du registre (reconcile, migrate, purge)',
    },
    'gui.add.debug_log': {
        "en": 'Keep debug extraction logs (prompts, model replies)',
        "fr": "Conserver les journaux de debug de l'extraction (prompts, réponses du modèle)",
    },
    'gui.add.retention_days': {
        "en": 'Debug log retention (days)',
        "fr": 'Rétention des journaux de debug (jours)',
    },
    'gui.add.run': {
        "en": 'Add events',
        "fr": 'Ajouter les événements',
    },
    'gui.add.no_source': {
        "en": 'Choose a source first.',
        "fr": "Choisissez d'abord une source.",
    },
    'gui.add.job': {
        "en": 'Adding events',
        "fr": 'Ajout des événements',
    },
    'gui.settings.provider': {
        "en": 'Provider',
        "fr": 'Fournisseur',
    },
    'gui.settings.unset': {
        "en": '(not set)',
        "fr": '(non défini)',
    },
    'gui.settings.model': {
        "en": 'Model',
        "fr": 'Modèle',
    },
    'gui.settings.calendar_account': {
        "en": 'Calendar account',
        "fr": 'Compte de calendrier',
    },
    'gui.settings.calendars': {
        "en": 'Calendars',
        "fr": 'Calendriers',
    },
    'gui.settings.calendar_ids': {
        "en": 'Calendar ids',
        "fr": 'Identifiants de calendrier',
    },
    'gui.settings.calendar_ids_placeholder': {
        "en": 'Comma-separated calendar ids (filled from the list above)',
        "fr": 'Identifiants de calendrier séparés par des virgules (remplis depuis la liste ci-dessus)',
    },
    'gui.settings.calendar_names': {
        "en": 'Named: {names}',
        "fr": 'Soit : {names}',
    },
    'gui.settings.language': {
        "en": 'Interface language',
        "fr": "Langue de l'interface",
    },
    'gui.settings.language_auto': {
        "en": '(system locale)',
        "fr": '(locale du système)',
    },
    'gui.settings.restart_note': {
        "en": 'The language applies the next time manage-agenda starts.',
        "fr": "La langue s'applique au prochain démarrage de manage-agenda.",
    },
    'gui.settings.save': {
        "en": 'Save',
        "fr": 'Enregistrer',
    },
    'gui.settings.reload': {
        "en": 'Reload',
        "fr": 'Recharger',
    },
    'gui.settings.saved': {
        "en": 'Saved.',
        "fr": 'Enregistré.',
    },
    # --- gui: calendar operations, ledger, evaluate, install ---
    'gui.calendar_ops.operation': {
        "en": 'Operation',
        "fr": 'Opération',
    },
    'gui.calendar_ops.source_calendar': {
        "en": 'Source calendar id',
        "fr": 'Identifiant du calendrier source',
    },
    'gui.calendar_ops.destination_calendar': {
        "en": 'Destination calendar id',
        "fr": 'Identifiant du calendrier de destination',
    },
    'gui.calendar_ops.text_filter': {
        "en": 'Title filter',
        "fr": 'Filtre sur le titre',
    },
    'gui.calendar_ops.ask_placeholder': {
        "en": '(empty: asked when the run starts)',
        "fr": '(vide : demandé au lancement)',
    },
    'gui.calendar_ops.note': {
        "en": 'The account, the calendars, the filter and the events are asked in dialogs when not given here, as `-i` does on the terminal.',
        "fr": "Le compte, les calendriers, le filtre et les événements sont demandés dans des dialogues s'ils ne sont pas donnés ici, comme `-i` sur le terminal.",
    },
    'gui.calendar_ops.run': {
        "en": 'Run',
        "fr": 'Lancer',
    },
    'gui.calendar_ops.job': {
        "en": 'Calendar {operation}',
        "fr": 'Calendrier : {operation}',
    },
    'gui.ledger.maintenance': {
        "en": 'Maintenance',
        "fr": 'Maintenance',
    },
    'gui.ledger.dry_run': {
        "en": 'Dry run: report, change nothing',
        "fr": 'Simulation : rapporter sans rien changer',
    },
    'gui.ledger.choose_account': {
        "en": 'Choose the calendar account (otherwise the saved one, or the only one configured)',
        "fr": 'Choisir le compte de calendrier (sinon celui enregistré, ou le seul configuré)',
    },
    'gui.ledger.reconcile': {
        "en": 'Reconcile',
        "fr": 'Réconcilier',
    },
    'gui.ledger.migrate': {
        "en": 'Migrate ledger',
        "fr": 'Migrer le registre',
    },
    'gui.ledger.exit_code_note': {
        "en": "The command's exit code is shown in the status bar: 0 ran, 3 no account, 4 choose an account, 5 migration required, 6 calendar list unreadable.",
        "fr": "Le code de sortie de la commande s'affiche dans la barre d'état : 0 exécuté, 3 aucun compte, 4 choisir un compte, 5 migration requise, 6 liste des calendriers illisible.",
    },
    'gui.ledger.job': {
        "en": 'Ledger {command}',
        "fr": 'Registre : {command}',
    },
    'gui.ledger.restore': {
        "en": 'Restore a deleted event',
        "fr": 'Restaurer un événement supprimé',
    },
    'gui.ledger.column_identity': {
        "en": 'Identity',
        "fr": 'Identité',
    },
    'gui.ledger.column_events': {
        "en": 'Cancelled events',
        "fr": 'Événements annulés',
    },
    'gui.ledger.restore_list': {
        "en": 'Reload',
        "fr": 'Recharger',
    },
    'gui.ledger.restore_run': {
        "en": 'Restore selected',
        "fr": 'Restaurer la sélection',
    },
    'gui.ledger.restore_select_one': {
        "en": 'Select an identity first.',
        "fr": "Sélectionnez d'abord une identité.",
    },
    'gui.evaluate.type': {
        "en": 'Input',
        "fr": 'Entrée',
    },
    'gui.evaluate.output': {
        "en": 'Output',
        "fr": 'Sortie',
    },
    'gui.evaluate.prompt': {
        "en": 'Prompt',
        "fr": 'Prompt',
    },
    'gui.evaluate.prompt_placeholder': {
        "en": 'Text to send to every Ollama model',
        "fr": 'Texte à envoyer à chaque modèle Ollama',
    },
    'gui.evaluate.run': {
        "en": 'Evaluate',
        "fr": 'Évaluer',
    },
    'gui.evaluate.job': {
        "en": 'Model evaluation',
        "fr": 'Évaluation des modèles',
    },
    'gui.install.browser': {
        "en": 'Browser',
        "fr": 'Navigateur',
    },
    'gui.install.note': {
        "en": 'Downloads the browser engine Playwright uses for web pages; progress goes to the log.',
        "fr": 'Télécharge le moteur de navigateur que Playwright utilise pour les pages web ; la progression va dans le journal.',
    },
    'gui.install.run': {
        "en": 'Install',
        "fr": 'Installer',
    },
    'gui.install.job': {
        "en": 'Browser installation',
        "fr": 'Installation du navigateur',
    },
    # --- accounts: the editor of socialModules' .rssBlogs / .rssImap (manage_agenda.accounts) ---
    'accounts.error_name_required': {
        "en": 'Give the account a name (the section name in .rssBlogs).',
        "fr": 'Donnez un nom au compte (le nom de section dans .rssBlogs).',
    },
    'accounts.error_name_invalid': {
        "en": "'{name}' cannot be a section name (no brackets, not DEFAULT).",
        "fr": '« {name} » ne peut pas être un nom de section (pas de crochets, pas DEFAULT).',
    },
    'accounts.error_name_duplicate': {
        "en": "An account named '{name}' already exists.",
        "fr": 'Un compte nommé « {name} » existe déjà.',
    },
    'accounts.error_service_unknown': {
        "en": "Unknown service '{service}': gmail, imap or gcalendar.",
        "fr": 'Service inconnu « {service} » : gmail, imap ou gcalendar.',
    },
    'accounts.error_address_required': {
        "en": "Give the account's address.",
        "fr": "Indiquez l'adresse du compte.",
    },
    'accounts.error_google_address': {
        "en": 'A Google account needs an address with an @ (it names the OAuth client file).',
        "fr": 'Un compte Google demande une adresse avec un @ (elle nomme le fichier client OAuth).',
    },
    'accounts.error_imap_server_required': {
        "en": 'Give the IMAP server.',
        "fr": 'Indiquez le serveur IMAP.',
    },
    'accounts.error_imap_user_required': {
        "en": 'Give the IMAP login.',
        "fr": "Indiquez l'identifiant IMAP.",
    },
    'accounts.error_imap_password_required': {
        "en": 'Give the IMAP password: none is stored for this account.',
        "fr": "Indiquez le mot de passe IMAP : aucun n'est enregistré pour ce compte.",
    },
    'accounts.error_imap_port': {
        "en": "'{port}' is not a port (1 to 65535).",
        "fr": "« {port} » n'est pas un port (1 à 65535).",
    },
    'accounts.error_imap_mode': {
        "en": "Unknown IMAP mode '{mode}': auto or review.",
        "fr": 'Mode IMAP inconnu « {mode} » : auto ou review.',
    },
    'accounts.error_multiline_value': {
        "en": "The value of '{name}' spans several lines; a section value must be one line.",
        "fr": 'La valeur de « {name} » tient sur plusieurs lignes ; une valeur de section tient sur une seule.',
    },
    'accounts.error_google_client_invalid': {
        "en": '{file} is not an OAuth client JSON: {error}',
        "fr": "{file} n'est pas un client OAuth (JSON) : {error}",
    },
    # --- gui: the Accounts screen and the screen headers ---
    'gui.nav.accounts': {
        "en": 'Accounts',
        "fr": 'Comptes',
    },
    'gui.add.subtitle': {
        "en": 'Every option of `add` on one form - web pages and text files too. The home screen runs the same with the saved configuration.',
        "fr": "Toutes les options de `add` sur un formulaire - pages web et fichiers texte compris. L'accueil lance la même analyse avec la configuration enregistrée.",
    },
    'gui.calendar_ops.subtitle': {
        "en": 'Copy, move, delete, clean or update the status of events between calendars.',
        "fr": "Copier, déplacer, supprimer, nettoyer ou mettre à jour le statut d'événements entre calendriers.",
    },
    'gui.ledger.subtitle': {
        "en": 'Reconcile and migrate the ledger; restore events that were cancelled.',
        "fr": 'Réconcilier et migrer le registre ; restaurer des événements annulés.',
    },
    'gui.evaluate.subtitle': {
        "en": 'Compare every installed Ollama model on a prompt or a source workflow.',
        "fr": 'Comparer tous les modèles Ollama installés sur une consigne ou un flux source.',
    },
    'gui.auth.subtitle': {
        "en": 'Check the Google authorization of an account, or run the browser consent.',
        "fr": "Vérifier l'autorisation Google d'un compte, ou lancer le consentement dans le navigateur.",
    },
    'gui.lists.subtitle': {
        "en": 'Browse a mail folder or a calendar as a table.',
        "fr": 'Parcourir un dossier de courrier ou un calendrier sous forme de table.',
    },
    'gui.install.subtitle': {
        "en": 'Download the browser Playwright uses to read web pages.',
        "fr": 'Télécharger le navigateur que Playwright utilise pour lire les pages web.',
    },
    'gui.settings.subtitle': {
        "en": "The saved configuration the command line's wizard writes: provider, model, calendars, language.",
        "fr": "La configuration enregistrée qu'écrit l'assistant de la ligne de commande : fournisseur, modèle, calendriers, langue.",
    },
    'gui.accounts.subtitle': {
        "en": "The mail and calendar accounts the other screens select from (socialModules' .rssBlogs).",
        "fr": 'Les comptes de courrier et de calendrier que les autres écrans proposent (le .rssBlogs de socialModules).',
    },
    'gui.accounts.column_name': {
        "en": 'Name',
        "fr": 'Nom',
    },
    'gui.accounts.column_service': {
        "en": 'Service',
        "fr": 'Service',
    },
    'gui.accounts.column_address': {
        "en": 'Address',
        "fr": 'Adresse',
    },
    'gui.accounts.column_details': {
        "en": 'Details',
        "fr": 'Détails',
    },
    'gui.accounts.add': {
        "en": 'Add…',
        "fr": 'Ajouter…',
    },
    'gui.accounts.edit': {
        "en": 'Edit…',
        "fr": 'Modifier…',
    },
    'gui.accounts.remove': {
        "en": 'Remove',
        "fr": 'Supprimer',
    },
    'gui.accounts.reload': {
        "en": 'Reload',
        "fr": 'Recharger',
    },
    'gui.accounts.empty': {
        "en": 'No account yet: Add… creates the first section of {file}.',
        "fr": 'Aucun compte : Ajouter… crée la première section de {file}.',
    },
    'gui.accounts.select_one': {
        "en": 'Select an account first.',
        "fr": "Sélectionnez d'abord un compte.",
    },
    'gui.accounts.remove_confirm': {
        "en": (
            "Remove the account '{name}' from {file}?\n\n"
            'Its IMAP credentials are removed with it; a Google OAuth client file and its token are kept.'
        ),
        "fr": (
            'Supprimer le compte « {name} » de {file} ?\n\n'
            'Ses identifiants IMAP sont supprimés avec lui ; un fichier client OAuth Google et son jeton sont conservés.'
        ),
    },
    'gui.accounts.saved': {
        "en": "Account '{name}' saved. The other screens pick it up when they are shown.",
        "fr": 'Compte « {name} » enregistré. Les autres écrans le prennent en compte à leur affichage.',
    },
    'gui.accounts.removed': {
        "en": "Account '{name}' removed.",
        "fr": 'Compte « {name} » supprimé.',
    },
    'gui.accounts.details_imap': {
        "en": '{server} · {folder} · mode {mode} · senders: {senders}',
        "fr": '{server} · {folder} · mode {mode} · expéditeurs : {senders}',
    },
    'gui.accounts.senders_none': {
        "en": 'none (selects nothing)',
        "fr": 'aucun (ne sélectionne rien)',
    },
    'gui.accounts.client_found': {
        "en": 'OAuth client file found',
        "fr": 'Fichier client OAuth présent',
    },
    'gui.accounts.client_missing': {
        "en": 'OAuth client file missing: {file}',
        "fr": 'Fichier client OAuth absent : {file}',
    },
    'gui.accounts.dialog_add_title': {
        "en": 'New account',
        "fr": 'Nouveau compte',
    },
    'gui.accounts.dialog_edit_title': {
        "en": 'Edit account',
        "fr": 'Modifier le compte',
    },
    'gui.accounts.name': {
        "en": 'Name',
        "fr": 'Nom',
    },
    'gui.accounts.name_hint': {
        "en": (
            'The section name; it identifies the account everywhere (rule key, ledger, mailbox '
            'history). Renaming starts a new history.'
        ),
        "fr": (
            'Le nom de la section ; il identifie le compte partout (clé de règle, registre, '
            'historique de la boîte). Le renommer démarre un nouvel historique.'
        ),
    },
    'gui.accounts.service': {
        "en": 'Service',
        "fr": 'Service',
    },
    'gui.accounts.address': {
        "en": 'Address',
        "fr": 'Adresse',
    },
    'gui.accounts.address_hint': {
        "en": 'The mailbox address (IMAP) or the Google account (gmail, gcalendar).',
        "fr": "L'adresse de la boîte (IMAP) ou le compte Google (gmail, gcalendar).",
    },
    'gui.accounts.imap_box': {
        "en": 'IMAP connection and scan',
        "fr": 'Connexion et analyse IMAP',
    },
    'gui.accounts.server': {
        "en": 'Server',
        "fr": 'Serveur',
    },
    'gui.accounts.port': {
        "en": 'Port (993, or 1143 for a local Proton Mail Bridge)',
        "fr": 'Port (993, ou 1143 pour un Proton Mail Bridge local)',
    },
    'gui.accounts.login': {
        "en": 'Login',
        "fr": 'Identifiant',
    },
    'gui.accounts.password': {
        "en": 'Password',
        "fr": 'Mot de passe',
    },
    'gui.accounts.password_unchanged': {
        "en": '(unchanged)',
        "fr": '(inchangé)',
    },
    'gui.accounts.folder': {
        "en": 'Folder',
        "fr": 'Dossier',
    },
    'gui.accounts.mode': {
        "en": 'Mode',
        "fr": 'Mode',
    },
    'gui.accounts.mode_hint': {
        "en": 'auto is what `add -s imap` selects; review is what `add -s imap -i` selects.',
        "fr": 'auto est ce que sélectionne `add -s imap` ; review, ce que sélectionne `add -s imap -i`.',
    },
    'gui.accounts.mark_seen': {
        "en": 'Flag processed messages as read',
        "fr": 'Marquer comme lus les messages traités',
    },
    'gui.accounts.max_age': {
        "en": 'Maximum age (days)',
        "fr": 'Âge maximal (jours)',
    },
    'gui.accounts.include_older': {
        "en": 'Include older mail',
        "fr": 'Inclure les messages plus anciens',
    },
    'gui.accounts.senders': {
        "en": 'Senders',
        "fr": 'Expéditeurs',
    },
    'gui.accounts.senders_hint': {
        "en": (
            'Comma-separated: an address, a @domain, a name:"…", or a name with an address or a '
            'domain. Empty selects nothing.'
        ),
        "fr": (
            'Séparés par des virgules : une adresse, un @domaine, un name:"…", ou un nom avec une '
            'adresse ou un domaine. Vide : ne sélectionne rien.'
        ),
    },
    'gui.accounts.google_box': {
        "en": 'Google authorization',
        "fr": 'Autorisation Google',
    },
    'gui.accounts.google_client': {
        "en": 'OAuth client',
        "fr": 'Client OAuth',
    },
    'gui.accounts.import_client': {
        "en": 'Import OAuth client JSON…',
        "fr": 'Importer le client OAuth (JSON)…',
    },
    'gui.accounts.import_client_title': {
        "en": 'OAuth client JSON',
        "fr": 'Client OAuth (JSON)',
    },
    'gui.accounts.client_imported': {
        "en": 'Copied to {file}',
        "fr": 'Copié dans {file}',
    },
    'gui.accounts.google_hint': {
        "en": (
            'Download the desktop OAuth client from the Google Cloud console, import it here, '
            'then run the consent on the Authentication screen.'
        ),
        "fr": (
            'Téléchargez le client OAuth (application de bureau) depuis la console Google Cloud, '
            "importez-le ici, puis lancez le consentement sur l'écran Authentification."
        ),
    },
    'gui.accounts.save': {
        "en": 'Save',
        "fr": 'Enregistrer',
    },
    # --- gui: the home screen (the task: scan, propose, plan) ---
    'gui.nav.home': {
        "en": 'Home',
        "fr": 'Accueil',
    },
    'gui.home.subtitle': {
        "en": 'Read a mailbox, extract the dates and put the events on your calendar. This screen is the task; the others are its settings.',
        "fr": 'Lire une boîte mail, en extraire les dates et mettre les événements dans votre calendrier. Cet écran est la tâche ; les autres en sont les réglages.',
    },
    'gui.home.run_box': {
        "en": 'Look for appointments in the mail',
        "fr": 'Chercher des rendez-vous dans le courrier',
    },
    'gui.home.source': {
        "en": 'Mailbox',
        "fr": 'Boîte mail',
    },
    'gui.home.mode': {
        "en": 'Mode',
        "fr": 'Mode',
    },
    'gui.home.mode_review': {
        "en": 'Propose each event to me',
        "fr": 'Me proposer chaque événement',
    },
    'gui.home.mode_auto': {
        "en": 'Plan without asking',
        "fr": 'Planifier sans demander',
    },
    'gui.home.mode_hint': {
        "en": (
            'Proposals appear below, one at a time: accept it (after correcting it if needed) '
            'or ask the model again. Without asking, old or unclear messages are skipped and '
            'the events are created as extracted.'
        ),
        "fr": (
            "Les propositions s'affichent ci-dessous, une à la fois : acceptez (après "
            'correction si besoin) ou redemandez au modèle. Sans demander, les messages anciens '
            'ou ambigus sont ignorés et les événements sont créés tels quels.'
        ),
    },
    'gui.home.destination': {
        "en": 'Destination',
        "fr": 'Destination',
    },
    'gui.home.destination_text': {
        "en": '{calendars} · model: {model}',
        "fr": '{calendars} · modèle : {model}',
    },
    'gui.home.no_calendar': {
        "en": 'no calendar saved yet: it is asked at the first run, then remembered',
        "fr": 'aucun calendrier enregistré : il est demandé à la première analyse, puis mémorisé',
    },
    'gui.home.model_default': {
        "en": 'saved or default',
        "fr": 'enregistré ou par défaut',
    },
    'gui.home.run': {
        "en": 'Scan the mail',
        "fr": 'Analyser le courrier',
    },
    'gui.home.open_advanced': {
        "en": 'Advanced…',
        "fr": 'Options avancées…',
    },
    'gui.home.open_settings': {
        "en": 'Settings…',
        "fr": 'Réglages…',
    },
    'gui.home.no_source': {
        "en": 'Configure a mail account first (Accounts).',
        "fr": "Configurez d'abord un compte de courrier (Comptes).",
    },
    'gui.home.job': {
        "en": 'Mail scan',
        "fr": 'Analyse du courrier',
    },
    'gui.home.run_done': {
        "en": 'Scan finished: {events} new event(s) added to the calendar.',
        "fr": 'Analyse terminée : {events} nouvel(s) événement(s) ajouté(s) au calendrier.',
    },
    'gui.home.run_done_none': {
        "en": 'Scan finished: nothing new (no message retained, or nothing extracted - see the log).',
        "fr": "Analyse terminée : rien de nouveau (aucun message retenu, ou rien d'extrait - voir le journal).",
    },
    'gui.home.mailbox_unreachable': {
        "en": (
            'The mailbox {account} does not answer: nothing was scanned. Check that its server '
            'is up (a local bridge must be running for 127.0.0.1) and its credentials in '
            'Accounts, then scan again.'
        ),
        "fr": (
            "La boîte {account} ne répond pas : rien n'a été analysé. Vérifiez que son serveur "
            'est joignable (un pont local doit tourner pour 127.0.0.1) et ses identifiants dans '
            'Comptes, puis relancez.'
        ),
    },
    'gui.home.inert_mailbox': {
        "en": (
            'This mailbox is configured to select no message (empty sender filter, see '
            'Accounts): a scan of it finds nothing, on purpose.'
        ),
        "fr": (
            'Cette boîte est configurée pour ne sélectionner aucun message (filtre expéditeurs '
            "vide, voir Comptes) : une analyse n'y trouve rien, volontairement."
        ),
    },
    'gui.home.review_box': {
        "en": 'Proposal',
        "fr": 'Proposition',
    },
    'gui.home.review_from': {
        "en": 'Found in message {label}',
        "fr": 'Trouvé dans le message {label}',
    },
    'gui.home.review_accept': {
        "en": 'Add to the calendar',
        "fr": 'Ajouter au calendrier',
    },
    'gui.home.review_stop': {
        "en": 'Stop the scan',
        "fr": "Arrêter l'analyse",
    },
    'gui.home.planned_box': {
        "en": 'Already on the calendar',
        "fr": 'Déjà au calendrier',
    },
    'gui.home.column_when': {
        "en": 'When',
        "fr": 'Quand',
    },
    'gui.home.column_title': {
        "en": 'Title',
        "fr": 'Titre',
    },
    'gui.home.column_calendar': {
        "en": 'Calendar',
        "fr": 'Calendrier',
    },
    'gui.home.column_origin': {
        "en": 'Origin',
        "fr": 'Origine',
    },
    'gui.home.origin_tool': {
        "en": 'planned from the mail',
        "fr": 'planifié depuis le courrier',
    },
    'gui.home.origin_new': {
        "en": 'planned by this scan',
        "fr": 'planifié par cette analyse',
    },
    'gui.home.refresh': {
        "en": 'Refresh',
        "fr": 'Actualiser',
    },
    'gui.home.job_planned': {
        "en": 'Calendar reading',
        "fr": 'Lecture du calendrier',
    },
    'gui.home.no_calendar_account': {
        "en": 'No calendar account saved: choose it in Settings.',
        "fr": 'Aucun compte de calendrier enregistré : choisissez-le dans Réglages.',
    },
    'gui.home.planned_empty': {
        "en": 'Nothing upcoming on these calendars.',
        "fr": 'Rien à venir sur ces calendriers.',
    },
    'gui.home.planned_hint': {
        "en": (
            'What the calendar already holds, not the result of a scan. Refresh reads the '
            'upcoming events (it connects to the account); double-click opens one in the browser.'
        ),
        "fr": (
            "Ce que le calendrier contient déjà, pas le résultat d'une analyse. Actualiser lit les "
            'événements à venir (se connecte au compte) ; un double-clic en ouvre un dans le navigateur.'
        ),
    },
    'gui.home.ledger_summary': {
        "en": '{messages} message(s) handled, {events} event(s) created by the tool; last on {last}.',
        "fr": "{messages} message(s) traité(s), {events} événement(s) créé(s) par l'outil ; dernier le {last}.",
    },
    'gui.home.ledger_empty': {
        "en": 'No message handled yet.',
        "fr": 'Aucun message traité pour l\'instant.',
    },
    # --- the source message named next to an event under review (ui.describe_source) ---
    'events.review_source': {
        "en": 'Source message: {details}',
        "fr": "Message d'origine : {details}",
    },
    'events.review_source_subject': {
        "en": '“{subject}”',
        "fr": '« {subject} »',
    },
    'events.review_source_from': {
        "en": 'from {sender}',
        "fr": 'de {sender}',
    },
    'events.review_source_date': {
        "en": 'received {date}',
        "fr": 'reçu le {date}',
    },
    'events.review_source_id': {
        "en": 'id {identifier}',
        "fr": 'id {identifier}',
    },
    'events.review_nature_cleaning': {
        "en": (
            'Cleaning proposed after the occupation of {room} from {first} to {last}: the first '
            'free slot on your configured days and hours. The message gives the occupation, not '
            'the cleaning.'
        ),
        "fr": (
            "Entretien proposé après l'occupation de {room} du {first} au {last} : premier créneau "
            "libre selon vos jours et heures configurés. Le message donne l'occupation, pas "
            "l'entretien."
        ),
    },
    'events.review_nature_deadline': {
        "en": 'The message asks for it before {when}.',
        "fr": 'Le message le demande avant le {when}.',
    },
    'events.review_nature_cleaning_day': {
        "en": (
            'Cleaning proposed after the occupation of {room} on {day}: the first free slot on '
            'your configured days and hours. The message gives the occupation, not the cleaning.'
        ),
        "fr": (
            "Entretien proposé après l'occupation de {room} le {day} : premier créneau libre selon "
            "vos jours et heures configurés. Le message donne l'occupation, pas l'entretien."
        ),
    },
}
