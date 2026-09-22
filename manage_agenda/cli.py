import os
import sys
from runpy import run_module

import click

from .base import setup_logging
from .connections import (
    authorize,
    complete_desktop_oauth,
    credential_path,
    describe_auth_failure,
)
from .evaluation import evaluate_models
from .events import (
    clean_events_cli,
    copy_events_cli,
    delete_events_cli,
    move_events_cli,
    update_event_status_cli,
)
from .i18n import t
from .sources import (
    Args,
    add_events_cli,
    list_folder,
    list_restorable_identities_cli,
    restore_deleted_event_cli,
)

# Click builds --help text when each command decorator runs, i.e. at import time. The first
# t() call below is what triggers manage_agenda.i18n's language resolution, early enough that
# --help output is translated along with everything printed at runtime.


@click.group()
@click.version_option()
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help=t("cli.verbose_help"),
)
@click.pass_context
def cli(ctx, verbose):
    ctx.ensure_object(dict)
    ctx.obj["VERBOSE"] = verbose
    setup_logging(verbose)


cli.help = t("cli.app_help")


@cli.group()
@click.pass_context
def llm(ctx):
    pass


llm.help = t("cli.llm_group_help")


@llm.command()
@click.option(
    "-t",
    "--type",
    "type_",
    type=click.Choice(["email", "web", "txt"]),
    default="txt",
    help=t("cli.evaluate.type_help"),
)
@click.option(
    "-o",
    "--output",
    type=click.Choice(["calendar", "file"]),
    default="file",
    help=t("cli.output_help"),
)
@click.argument("prompt", required=False)
@click.pass_context
def evaluate(ctx, type_, output, prompt):
    if prompt:
        print(prompt)
    args = Args(
        interactive=False,
        delete=None,
        source=None,
        verbose=ctx.obj["VERBOSE"],
        destination=None,
        text=None,
        output=output,
    )

    evaluate_models(args, prompt=prompt, eval_type=type_ if not prompt else None)


evaluate.help = t("cli.evaluate.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.option(
    "-a",
    "--ai",
    default=None,
    help=t("cli.add.ai_help"),
)
@click.option(
    "-m",
    "--model",
    default=None,
    help=t("cli.add.model_help"),
)
@click.option(
    "-f",
    "--force-refresh",
    is_flag=True,
    default=False,
    help=t("cli.add.force_refresh_help"),
)
@click.option(
    "-s",
    "--source",
    type=click.Choice(["email", "gmail", "imap", "web", "text"]),
    default=None,
    help=t("cli.add.source_help"),
)
@click.option(
    "-d",
    "--destination",
    default=None,
    help=t("cli.add.destination_help"),
)
@click.option(
    "-o",
    "--output",
    type=click.Choice(["calendar", "file"]),
    default="calendar",
    help=t("cli.output_help"),
)
@click.option(
    "--rule",
    type=click.Choice(["auto", "review"]),
    default=None,
    help=t("cli.add.rule_help"),
)
@click.option(
    "--reconfigure",
    is_flag=True,
    default=False,
    help=t("cli.add.reconfigure_help"),
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help=t("cli.add.dry_run_help"),
)
@click.pass_context
def add(
    ctx, interactive, source, ai, model, force_refresh, destination, output, rule, reconfigure, dry_run
):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=source,
        ai=ai,
        model=model,
        verbose=verbose,
        destination=destination,
        text=None,
        output=output,
        force_refresh=force_refresh,
        rule=rule,
        reconfigure=reconfigure,
        dry_run=dry_run,
    )

    add_events_cli(args)


add.help = t("cli.add.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.pass_context
def auth(ctx, interactive):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=None,
        verbose=verbose,
        destination=None,
        text=None,
    )
    if verbose:
        print(t("cli.auth.args_debug", args=args))
    api_src = authorize(args)
    if api_src is not None and api_src.getClient():
        print(t("cli.auth.authorized_success"))
        return

    print(describe_auth_failure(api_src))
    if api_src is not None and os.path.isfile(credential_path(api_src)):
        print(t("cli.auth.opening_browser"))
        if complete_desktop_oauth(api_src):
            print(t("cli.auth.authorized_success"))
            return
        return
    print(t("cli.auth.create_oauth_client_instructions"))


auth.help = t("cli.auth.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.pass_context
def gcalendar(ctx, interactive):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=None,
        verbose=verbose,
        destination=None,
        text=None,
    )
    list_folder(args, "gcalendar")


gcalendar.help = t("cli.gcalendar.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.pass_context
def gmail(ctx, interactive):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=None,
        verbose=verbose,
        destination=None,
        text=None,
    )
    list_folder(args, "gmail")


gmail.help = t("cli.gmail.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.option(
    "-s",
    "--source",
    default=None,
    help=t("cli.select_source_calendar_help"),
)
@click.option(
    "-d",
    "--destination",
    default=None,
    help=t("cli.select_destination_calendar_help"),
)
@click.option(
    "-t",
    "--text",
    default=None,
    help=t("cli.select_text_help"),
)
@click.pass_context
def copy(ctx, interactive, source, destination, text):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=source,
        verbose=verbose,
        destination=destination,
        text=text,
    )

    copy_events_cli(args)


copy.help = t("cli.copy.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.option(
    "-s",
    "--source",
    default=None,
    help=t("cli.select_source_calendar_help"),
)
@click.option(
    "-d",
    "--destination",
    default=None,
    help=t("cli.select_destination_calendar_help"),
)
@click.option(
    "-t",
    "--text",
    default=None,
    help=t("cli.select_text_help"),
)
@click.pass_context
def clean(ctx, interactive, source, destination, text):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=source,
        verbose=verbose,
        destination=destination,
        text=text,
    )

    clean_events_cli(args)


clean.help = t("cli.clean.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.option(
    "-s",
    "--source",
    default=None,
    help=t("cli.select_source_calendar_help"),
)
@click.option(
    "-t",
    "--text",
    default=None,
    help=t("cli.select_text_help"),
)
@click.pass_context
def delete(ctx, interactive, source, text):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=source,
        verbose=verbose,
        destination=None,
        text=text,
    )

    delete_events_cli(args)


delete.help = t("cli.delete.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.option(
    "-s",
    "--source",
    default=None,
    help=t("cli.select_source_calendar_help"),
)
@click.option(
    "-d",
    "--destination",
    default=None,
    help=t("cli.select_destination_calendar_help"),
)
@click.option(
    "-t",
    "--text",
    default=None,
    help=t("cli.select_text_help"),
)
@click.pass_context
def move(ctx, interactive, source, destination, text):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=source,
        verbose=verbose,
        destination=destination,
        text=text,
    )

    move_events_cli(args)


move.help = t("cli.move.help")


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help=t("cli.interactive_help"),
)
@click.option(
    "-s",
    "--source",
    default=None,
    help=t("cli.select_source_calendar_help"),
)
@click.option(
    "-t",
    "--text",
    default=None,
    help=t("cli.select_text_help"),
)
@click.pass_context
def update_status(ctx, interactive, source, text):
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=source,
        verbose=verbose,
        destination=None,
        text=text,
    )

    update_event_status_cli(args)


update_status.help = t("cli.update_status.help")


@cli.command()
@click.argument("identity", required=False)
@click.option(
    "--list",
    "list_only",
    is_flag=True,
    default=False,
    help=t("cli.restore.list_help"),
)
@click.option(
    "-s",
    "--source",
    default=None,
    help=t("cli.select_source_calendar_help"),
)
@click.pass_context
def restore(ctx, identity, list_only, source):
    if list_only:
        list_restorable_identities_cli()
        return
    if not identity:
        print(t("cli.restore.identity_required"))
        return
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=False,
        delete=None,
        source=source,
        verbose=verbose,
        destination=None,
        text=None,
    )

    restore_deleted_event_cli(args, identity)


restore.help = t("cli.restore.help")

BROWSERS = ("chromium", "firefox", "webkit", "chrome", "chrome-beta")

@cli.command()
@click.option(
    "--browser",
    "-b",
    default="firefox",
    type=click.Choice(BROWSERS, case_sensitive=False),
    help=t("cli.install.browser_help"),
)
def install(browser):
    sys.argv = ["playwright", "install", browser]
    run_module("playwright", run_name="__main__")


install.help = t("cli.install.help")
