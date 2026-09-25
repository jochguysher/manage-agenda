"""manage_agenda.compat: the IMAP port shim on socialModules' moduleImap - `port` read from
the .rssImap section by getKeys(), used by makeConnection(), 993 without it."""

import configparser
from unittest.mock import MagicMock, patch

import pytest

from manage_agenda import compat


def _config(**section):
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_dict({"royal": {"server": "127.0.0.1", "user": "info@x", "token": "pw", **section}})
    return parser


def _module():
    from socialModules.moduleImap import moduleImap

    compat.install_socialmodules_shims()
    instance = moduleImap.__new__(moduleImap)
    instance.user = "royal"  # the section name, as socialModules sets it before getKeys()
    instance.indent = ""
    instance.service = "Imap"
    return instance


def test_port_from_config_defaults_to_993():
    assert compat.imap_port_from_config(_config(), "royal") == 993
    assert compat.imap_port_from_config(_config(port="1143"), "royal") == 1143
    assert compat.imap_port_from_config(_config(port="abc"), "royal") == 993
    assert compat.imap_port_from_config(_config(port="70000"), "royal") == 993
    assert compat.imap_port_from_config(_config(), "missing") == 993


def test_get_keys_still_reads_the_section_and_keeps_the_port():
    instance = _module()
    assert instance.getKeys(_config(port="1143")) == "pw"
    assert (instance.server, instance.user, instance.port) == ("127.0.0.1", "info@x", 1143)
    instance.user = "royal"
    instance.getKeys(_config())
    assert instance.port == 993


@pytest.mark.parametrize("port", [None, 1143])
def test_make_connection_uses_the_port_and_logs_in(port):
    instance = _module()
    if port is not None:
        instance.port = port
    client = MagicMock()
    with patch.object(compat.imaplib, "IMAP4_SSL", return_value=client) as connect:
        assert instance.makeConnection("127.0.0.1", "info@x", "pw") is client
    host, used_port = connect.call_args.args
    assert (host, used_port) == ("127.0.0.1", port or 993)
    assert connect.call_args.kwargs["ssl_context"] is not None
    client.login.assert_called_once_with("info@x", "pw")


def test_a_refused_connection_raises_for_initapi_to_catch():
    instance = _module()
    with patch.object(compat.imaplib, "IMAP4_SSL", side_effect=ConnectionRefusedError()):
        with pytest.raises(ConnectionRefusedError):
            instance.makeConnection("127.0.0.1", "info@x", "pw")


def test_install_is_idempotent():
    from socialModules.moduleImap import moduleImap

    compat.install_socialmodules_shims()
    get_keys, make_connection = moduleImap.getKeys, moduleImap.makeConnection
    compat.install_socialmodules_shims()
    assert moduleImap.getKeys is get_keys and moduleImap.makeConnection is make_connection
    assert get_keys.__wrapped__.__name__ == "getKeys"
