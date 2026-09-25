"""The UI port itself (manage_agenda.ui): the holder, label_for, the dispatchers, and the
contract of ScriptedUI that every migrated test relies on."""

import pytest

from manage_agenda import ui as ui_module
from manage_agenda.exceptions import UserCancelled
from manage_agenda.ui import echo, get_ui, label_for, select_many, select_one, set_ui, use_ui
from manage_agenda.ui.console import ConsoleUI
from manage_agenda.ui.fake import Call, ScriptedUI


def test_default_ui_is_a_console_created_once():
    set_ui(None)
    first = get_ui()
    assert isinstance(first, ConsoleUI)
    assert get_ui() is first


def test_use_ui_installs_for_the_block_and_restores_what_was_there():
    outer = ScriptedUI()
    set_ui(outer)
    inner = ScriptedUI()
    with use_ui(inner) as installed:
        assert installed is inner
        assert get_ui() is inner
    assert get_ui() is outer


def test_use_ui_restores_even_when_the_block_raises():
    set_ui(None)
    with pytest.raises(RuntimeError), use_ui(ScriptedUI()):
        raise RuntimeError("boom")
    assert isinstance(get_ui(), ConsoleUI)


def test_user_cancelled_passes_through_except_exception():
    """The reason it is a BaseException: connections.select_calendar() wraps its prompt in
    `except Exception`, and an ordinary exception would come out as a CalendarError."""
    assert not issubclass(UserCancelled, Exception)
    with pytest.raises(UserCancelled):
        try:
            raise UserCancelled()
        except Exception:  # pragma: no cover - the assertion is that this is never reached
            pytest.fail("UserCancelled must not be caught by `except Exception`")


class TestLabelFor:
    def test_dict_by_identifier(self):
        assert label_for({"summary": "Work", "id": "w1"}, "summary") == "Work"

    def test_object_attribute_by_identifier(self):
        class Model:
            model = "llama3"

        assert label_for(Model(), "model") == "llama3"

    def test_missing_identifier_falls_back_to_str(self):
        assert label_for({"id": "w1"}, "summary") == "{'id': 'w1'}"

    def test_plain_string_is_itself(self):
        assert label_for("gemini") == "gemini"

    def test_tuple_rule_key_becomes_a_string(self):
        key = ("imap", "set", "me@host", "posts")
        assert label_for(key) == str(key)
        assert isinstance(label_for(key), str)

    def test_non_string_value_is_stringified(self):
        assert label_for({"n": 3}, "n") == "3"


class TestDispatchers:
    def test_module_level_functions_go_through_the_current_ui(self):
        scripted = ScriptedUI([("choose_one", 1), ("choose_many", [0, 1])])
        with use_ui(scripted):
            assert select_one(["a", "b"], title="t") == "b"
            assert select_many(["a", "b"]) == ["a", "b"]
            echo("hello", "world", sep="-")
        assert [call.kind for call in scripted.calls] == ["choose_one", "choose_many"]
        assert scripted.calls[0].payload["title"] == "t"
        assert scripted.output == ["hello-world"]

    def test_echo_accepts_prints_keyword_arguments(self):
        scripted = ScriptedUI()
        with use_ui(scripted):
            ui_module.echo("x", flush=True, end="")
        assert scripted.output == ["x"]


class TestScriptedUI:
    def test_strict_with_nothing_queued_fails_the_prompt(self):
        scripted = ScriptedUI()
        with pytest.raises(AssertionError, match="no scripted answer for confirm"):
            scripted.confirm("sure?")

    def test_kind_mismatch_names_both_kinds(self):
        scripted = ScriptedUI([("ask_text", "x")])
        with pytest.raises(AssertionError, match="expected the flow to ask 'ask_text'.*'confirm'"):
            scripted.confirm("sure?")

    def test_every_prompt_is_recorded_with_its_payload(self):
        scripted = ScriptedUI([("confirm", True)])
        assert scripted.confirm("sure?") is True
        assert scripted.calls == [Call("confirm", {"text": "sure?", "default": False})]

    def test_choose_one_index_or_item(self):
        scripted = ScriptedUI([("choose_one", 1), ("choose_one", "zzz"), ("choose_one", None)])
        assert scripted.choose_one(["a", "b"]) == "b"
        assert scripted.choose_one(["a", "b"]) == "zzz"
        assert scripted.choose_one(["a", "b"]) is None

    def test_choose_many_indices_or_items(self):
        scripted = ScriptedUI([("choose_many", [1, 0]), ("choose_many", ["x"]), ("choose_many", [])])
        assert scripted.choose_many(["a", "b"]) == ["b", "a"]
        assert scripted.choose_many(["a", "b"]) == ["x"]
        assert scripted.choose_many(["a", "b"]) == []

    def test_select_events_all_indices_or_items(self):
        events = [{"id": 1}, {"id": 2}]
        scripted = ScriptedUI([("select_events", "all"), ("select_events", [1]), ("select_events", [])])
        assert scripted.select_events(events, ["a", "b"]) == events
        assert scripted.select_events(events, ["a", "b"]) == [{"id": 2}]
        assert scripted.select_events(events, ["a", "b"]) == []

    def test_review_event_decision_or_decision_with_edited_event(self):
        event = {"summary": "x"}
        edited = {"summary": "y"}
        scripted = ScriptedUI([("review_event", "retry"), ("review_event", ("accept", edited))])
        assert scripted.review_event(event) == (event, "retry")
        assert scripted.review_event(event, label="[1] ", context={"subject": "s"}) == (edited, "accept")
        assert scripted.calls[1].payload["label"] == "[1] "
        assert scripted.calls[1].payload["context"] == {"subject": "s"}
        assert scripted.calls[0].payload["context"] is None

    def test_text_prompts_return_the_scripted_string(self):
        scripted = ScriptedUI([("ask_text", "u1 u2"), ("ask_multiline", "a\nb"), ("choose_action", "r")])
        assert scripted.ask_text("urls? ") == "u1 u2"
        assert scripted.ask_multiline("paste") == "a\nb"
        assert scripted.choose_action([("r", "Retry")], "r/p/s? ") == "r"

    def test_cancel_injection_as_class_or_instance(self):
        scripted = ScriptedUI([("confirm", UserCancelled), ("ask_text", UserCancelled("closed"))])
        with pytest.raises(UserCancelled):
            scripted.confirm("?")
        with pytest.raises(UserCancelled, match="closed"):
            scripted.ask_text("?")

    def test_lenient_defaults(self):
        scripted = ScriptedUI(lenient=True)
        assert scripted.choose_one(["a", "b"]) == "a"
        assert scripted.choose_one([]) is None
        assert scripted.choose_many(["a"]) == []
        assert scripted.confirm("?") is False
        assert scripted.confirm("?", default=True) is True
        assert scripted.ask_text("?") == ""
        assert scripted.ask_text("?", default="d") == "d"
        assert scripted.ask_multiline("?") == ""
        assert scripted.choose_action([("0", "Delete"), ("1", "Copy")], "?") == "0"
        assert scripted.review_event({"e": 1}) == ({"e": 1}, "accept")
        assert scripted.select_events([1, 2], ["a", "b"]) == []
        assert len(scripted.calls) == 11

    def test_queue_chains_and_assert_consumed(self):
        scripted = ScriptedUI().queue("confirm", True).queue("confirm", False)
        assert scripted.confirm("?") is True
        with pytest.raises(AssertionError, match="unconsumed"):
            scripted.assert_consumed()
        assert scripted.confirm("?") is False
        scripted.assert_consumed()


def test_scripted_ui_fixture_is_installed_and_checked(scripted_ui):
    scripted_ui.queue("confirm", True)
    assert get_ui() is scripted_ui
    assert get_ui().confirm("?") is True


class TestDescribeNature:
    def test_cleaning_context_is_named_and_extracted_events_are_not(self):
        from manage_agenda.ui import describe_nature

        week = describe_nature(
            {"kind": "cleaning", "room": "Salle 1", "occupied_from": "2026-09-27", "occupied_to": "2026-10-03"}
        )
        assert "Salle 1" in week and "2026-09-27" in week and "2026-10-03" in week
        day = describe_nature({"kind": "cleaning", "room": "Salle 1", "occupied_from": "2026-09-27", "occupied_to": "2026-09-27"})
        assert "2026-09-27" in day and day != week
        assert describe_nature({"subject": "x"}) == ""
        assert describe_nature(None) == ""

    def test_a_deadline_is_said(self):
        from manage_agenda.ui import describe_nature

        text = describe_nature(
            {"kind": "cleaning", "room": "Salle 1", "occupied_from": "2026-05-30 14:00", "occupied_to": "2026-05-31 02:00", "clean_before": "2026-05-31 08:00"}
        )
        assert "2026-05-31 08:00" in text and "2026-05-30 14:00" in text
