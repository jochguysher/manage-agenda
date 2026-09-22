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
from .sources import (
    Args,
    add_events_cli,
    list_folder,
)


@click.group()
@click.version_option()
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    default=False,
    help="Enable verbose output.",
)
@click.pass_context
def cli(ctx, verbose):
    """An app for adding entries to my calendar"""
    ctx.ensure_object(dict)
    ctx.obj["VERBOSE"] = verbose
    setup_logging(verbose)


@cli.group()
@click.pass_context
def llm(ctx):
    """LLM related operations"""
    pass


@llm.command()
@click.option(
    "-t",
    "--type",
    "type_",
    type=click.Choice(["email", "web", "txt"]),
    default="txt",
    help="Type of evaluation to run (email, web, txt)",
)
@click.option(
    "-o",
    "--output",
    type=click.Choice(["calendar", "file"]),
    default="file",
    help="Output destination: calendar or file",
)
@click.argument("prompt", required=False)
@click.pass_context
def evaluate(ctx, type_, output, prompt):
    """Evaluate different LLM models"""
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


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.option(
    "-a",
    "--ai",
    default="ollama",
    help="Select LLM",
)
@click.option(
    "-f",
    "--force-refresh",
    is_flag=True,
    default=False,
    help="Force refresh web content to bypass cache",
)
@click.option(
    "-s",
    "--source",
    type=click.Choice(["email", "gmail", "imap", "web", "text"]),
    default=None,
    help="Source of data: email, gmail, imap, web, or text files",
)
@click.option(
    "-d",
    "--destination",
    default=None,
    help="Select destination calendar",
)
@click.option(
    "-o",
    "--output",
    type=click.Choice(["calendar", "file"]),
    default="calendar",
    help="Output destination: calendar or file",
)
@click.option(
    "--rule",
    type=click.Choice(["auto", "review"]),
    default=None,
    help="IMAP sender rule. Default is auto, or review when -s imap -i",
)
@click.pass_context
def add(ctx, interactive, source, ai, force_refresh, destination, output, rule):
    """Add entries to the calendar."""
    verbose = ctx.obj["VERBOSE"]
    args = Args(
        interactive=interactive,
        delete=None,
        source=source,
        ai=ai,
        verbose=verbose,
        destination=destination,
        text=None,
        output=output,
        force_refresh=force_refresh,
        rule=rule,
    )

    add_events_cli(args)


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.pass_context
def auth(ctx, interactive):
    """Auth related operations"""
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
        print(f"Args: {args}")
    api_src = authorize(args)
    if api_src is not None and api_src.getClient():
        print("This account has been correctly authorized")
        return

    print(describe_auth_failure(api_src))
    if api_src is not None and os.path.isfile(credential_path(api_src)):
        print("Opening the browser for Google consent.")
        if complete_desktop_oauth(api_src):
            print("This account has been correctly authorized")
            return
        return
    print(
        "Create a Desktop app OAuth client and save the JSON under the expected name, "
        "then run: uv run manage-agenda auth -i"
    )


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.pass_context
def gcalendar(ctx, interactive):
    """List events from Google Calendar"""
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


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.pass_context
def gmail(ctx, interactive):
    """List emails from Gmail"""
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


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.option(
    "-s",
    "--source",
    default=None,
    help="Select source calendar",
)
@click.option(
    "-d",
    "--destination",
    default=None,
    help="Select destination calendar",
)
@click.option(
    "-t",
    "--text",
    default=None,
    help="Select text in title",
)
@click.pass_context
def copy(ctx, interactive, source, destination, text):
    """Copy entries from one calendar to another"""
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


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.option(
    "-s",
    "--source",
    default=None,
    help="Select source calendar",
)
@click.option(
    "-d",
    "--destination",
    default=None,
    help="Select destination calendar",
)
@click.option(
    "-t",
    "--text",
    default=None,
    help="Select text in title",
)
@click.pass_context
def clean(ctx, interactive, source, destination, text):
    """Clean calendar entries (select between copy or delete)"""
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


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.option(
    "-s",
    "--source",
    default=None,
    help="Select source calendar",
)
@click.option(
    "-t",
    "--text",
    default=None,
    help="Select text in title",
)
@click.pass_context
def delete(ctx, interactive, source, text):
    """Delete entries from a calendar"""
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


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.option(
    "-s",
    "--source",
    default=None,
    help="Select source calendar",
)
@click.option(
    "-d",
    "--destination",
    default=None,
    help="Select destination calendar",
)
@click.option(
    "-t",
    "--text",
    default=None,
    help="Select text in title",
)
@click.pass_context
def move(ctx, interactive, source, destination, text):
    """Move entries from one calendar to another"""
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


@cli.command()
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    help="Running in interactive mode",
)
@click.option(
    "-s",
    "--source",
    default=None,
    help="Select source calendar",
)
@click.option(
    "-t",
    "--text",
    default=None,
    help="Select text in title",
)
@click.pass_context
def update_status(ctx, interactive, source, text):
    """Update event status from busy to available"""
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

BROWSERS = ("chromium", "firefox", "webkit", "chrome", "chrome-beta")

@cli.command()
@click.option(
    "--browser",
    "-b",
    default="firefox",
    type=click.Choice(BROWSERS, case_sensitive=False),
    help="Which browser to install",
)
def install(browser):
    """
    Install the Playwright browser needed by this tool.

    Usage:

        manage-agenda install

    Or for browsers other than the Firefox default:

        manage-agenda install -b chromium
    """
    sys.argv = ["playwright", "install", browser]
    run_module("playwright", run_name="__main__")
