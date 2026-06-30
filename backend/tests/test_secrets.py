# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Unit tests for component credential encryption (app/services/secrets.py)."""

from app.services import secrets as s

KEY = "test-secret-key-0123456789-abcdefghij"


def test_is_secret_key_positive():
    for k in [
        "auth.password",
        "password",
        "token",
        "default_token",
        "api_key",
        "apikey",
        "aws_secret_access_key",
        "sasl.password",
        "tls.key_pass",
        "license_key",
        "passphrase",
        "credentials",
        "connection_string",  # Azure Blob / AMQP — embeds the credential
        "shared_key",  # Azure Monitor shared secret
        "auth.nkey",  # NATS nkey seed
    ]:
        assert s.is_secret_key(k), k


def test_is_secret_key_negative():
    # Structural / file-path / field-name keys are NOT secrets.
    for k in [
        "address",
        "key",  # object/blob key = a path template, not a credential
        "partition_key",
        "group_key",
        "message_key",
        "key_field",
        "tls.key_file",
        "tls.crt_file",
        "tls.ca_file",
        "secret_name",  # a reference, not the value
        "endpoint",
        "topic",
        "batch.max_bytes",
    ]:
        assert not s.is_secret_key(k), k


def test_split_create_then_reveal_roundtrip():
    cfg = {"endpoint": "http://x", "auth.password": "hunter2", "token": "abc"}
    public, enc = s.split_for_write(cfg, None, KEY)
    # Secrets are pulled out of the public config.
    assert public == {"endpoint": "http://x"}
    assert enc is not None
    # Revealed render restores the real values.
    revealed = s.merge_revealed(public, enc, KEY)
    assert revealed == cfg


def test_masked_hides_values_but_shows_keys():
    cfg = {"endpoint": "http://x", "auth.password": "hunter2"}
    public, enc = s.split_for_write(cfg, None, KEY)
    masked = s.merge_masked(public, enc, KEY)
    assert masked["endpoint"] == "http://x"
    assert masked["auth.password"] == s.MASK
    assert "hunter2" not in str(masked)


def test_update_mask_preserves_existing_secret():
    # Create with a secret, then "edit" sending the MASK back unchanged.
    public, enc = s.split_for_write({"token": "real"}, None, KEY)
    # Frontend GETs masked, edits nothing secret, PATCHes the masked value back.
    new_public, new_enc = s.split_for_write({"token": s.MASK}, enc, KEY)
    assert s.merge_revealed(new_public, new_enc, KEY) == {"token": "real"}


def test_update_real_value_replaces_secret():
    _, enc = s.split_for_write({"token": "old"}, None, KEY)
    new_public, new_enc = s.split_for_write({"token": "new"}, enc, KEY)
    assert s.merge_revealed(new_public, new_enc, KEY)["token"] == "new"


def test_empty_and_none():
    public, enc = s.split_for_write({"endpoint": "x"}, None, KEY)
    assert enc is None  # no secrets → no ciphertext
    assert s.merge_revealed(public, None, KEY) == {"endpoint": "x"}
    assert s.merge_masked(public, None, KEY) == {"endpoint": "x"}


def test_empty_string_secret_not_encrypted():
    # An empty secret value is "not set" — not stored.
    public, enc = s.split_for_write({"password": ""}, None, KEY)
    assert enc is None
    assert public == {"password": ""}


def test_mask_with_no_existing_is_dropped():
    # Masked sentinel but nothing stored → treated as unset.
    public, enc = s.split_for_write({"token": s.MASK}, None, KEY)
    assert enc is None
    assert "token" not in public
