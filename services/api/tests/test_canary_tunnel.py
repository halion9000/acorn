"""The Cloudflare tunnel token CORE hands over: only a real token is accepted, it is kept for the update script, and nothing ever returns it."""

import asyncio
import base64
import json
import os
import stat
import uuid
from types import SimpleNamespace

import pytest
from app.api.v1.endpoints import canary_tunnel as ep
from app.services import canary_tunnel as tunnel
from fastapi import HTTPException


def make_token(**over):
    data = {"a": "acct123", "t": "11111111-2222-3333-4444-555555555555", "s": "c2VjcmV0c2VjcmV0"}
    data.update(over)
    return base64.b64encode(json.dumps(data).encode()).decode()


TOKEN = make_token()


def test_a_real_tunnel_token_is_accepted_and_trimmed():
    assert tunnel.check_token(f"  {TOKEN}\n") == TOKEN


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "not a token",
        "abc$def",
        TOKEN + "\nOTHER=1",  # a second .env line
        'eyJh"; rm -rf /',
        base64.b64encode(b"not json").decode(),
        base64.b64encode(json.dumps({"a": "x", "t": "y"}).encode()).decode(),  # no secret
        base64.b64encode(json.dumps(["a", "t", "s"]).encode()).decode(),
        make_token(s=""),
        "A" * 3000,
    ],
)
def test_anything_else_is_refused(bad):
    with pytest.raises(tunnel.TokenRefused):
        tunnel.check_token(bad)


def test_the_refusal_never_repeats_the_text():
    secret = "supersecretvalue$"
    with pytest.raises(tunnel.TokenRefused) as err:
        tunnel.check_token(secret)
    assert secret not in str(err.value)


def test_storing_writes_a_private_file_and_says_whether_it_changed(tmp_path):
    assert tunnel.store_token(tmp_path, TOKEN) is True
    target = tmp_path / tunnel.TOKEN_FILE
    assert target.read_text().strip() == TOKEN
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert tunnel.store_token(tmp_path, TOKEN) is False, "the same token again changes nothing"
    other = make_token(s="b3RoZXI=")
    assert tunnel.store_token(tmp_path, other) is True
    assert target.read_text().strip() == other
    assert [p.name for p in tmp_path.iterdir()] == [tunnel.TOKEN_FILE], "no temporary file is left behind"


def test_there_is_no_folder_to_keep_it_in():
    with pytest.raises(RuntimeError):
        tunnel.store_token(None, TOKEN)


def test_the_state_names_the_tunnel_and_never_the_token(tmp_path):
    assert tunnel.state(tmp_path).stored is False
    tunnel.store_token(tmp_path, TOKEN)
    s = tunnel.state(tmp_path)
    assert s.stored and s.tunnel_id == "11111111-2222-3333-4444-555555555555" and s.changed_at is not None
    assert TOKEN not in repr(s)


# --- the route ---------------------------------------------------------------


@pytest.fixture
def wired(monkeypatch, tmp_path):
    audits = []
    owner = uuid.uuid4()

    async def verify(db, token):
        if token != "good-feed-token":
            raise HTTPException(status_code=401, detail="Invalid or revoked inbox token")
        return owner

    async def adopt(db, tid):
        return None

    async def audit(**kw):
        audits.append(kw)

    class Db:
        async def commit(self):
            return None

    monkeypatch.setattr(ep, "_verify_core_feed_token", verify)
    monkeypatch.setattr(ep, "adopt_tenant", adopt)
    monkeypatch.setattr(ep, "emit_audit", audit)
    monkeypatch.setattr(ep, "control_dir", lambda: tmp_path)
    return SimpleNamespace(audits=audits, owner=owner, db=Db(), dir=tmp_path)


def call(w, token, feed="good-feed-token"):
    return asyncio.run(ep.receive_tunnel_token(feed, ep.TunnelIn(token=token), w.db, SimpleNamespace()))


def test_a_wrong_feed_token_is_refused_and_nothing_is_written(wired):
    with pytest.raises(HTTPException) as err:
        call(wired, TOKEN, feed="nope")
    assert err.value.status_code == 401
    assert not (wired.dir / tunnel.TOKEN_FILE).exists()


def test_a_bad_tunnel_token_is_a_422_and_nothing_is_written(wired):
    with pytest.raises(HTTPException) as err:
        call(wired, "garbage value")
    assert err.value.status_code == 422 and "garbage" not in str(err.value.detail)
    assert not (wired.dir / tunnel.TOKEN_FILE).exists()


def test_a_good_token_is_kept_audited_without_the_token_and_not_echoed(wired):
    out = call(wired, TOKEN)
    assert (out.stored, out.changed) == (True, True)
    assert TOKEN not in out.model_dump_json()
    assert len(wired.audits) == 1 and wired.audits[0]["action"] == "honeytokens:tunnel_token_changed"
    assert TOKEN not in json.dumps(wired.audits[0], default=str)
    again = call(wired, TOKEN)
    assert (again.stored, again.changed) == (True, False)
    assert len(wired.audits) == 1, "sending the same token again is not a change and is not audited"


def test_no_hand_off_folder_is_a_503(wired, monkeypatch):
    monkeypatch.setattr(ep, "control_dir", lambda: None)
    with pytest.raises(HTTPException) as err:
        call(wired, TOKEN)
    assert err.value.status_code == 503
