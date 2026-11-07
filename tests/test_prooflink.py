"""Local tests for ProofLink (no GenLayer node needed).

They run the contract's real logic against a small stand-in for the genlayer
library. The web fetch is replaced by a dictionary of pages, so the tests check
the rules around it: who can verify, what counts as the code being on the page,
which URLs are refused, and the limits.

Run:  python3 tests/test_prooflink.py      (or: pytest tests)
"""
import importlib.util
import json
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT = os.path.join(HERE, "..", "prooflink.py")

ALICE = "0x" + "a1" * 20
BOB = "0x" + "b2" * 20
URL = "https://example.com/alice"


class _Addr:
    def __init__(self, h):
        self.as_hex = h


class _Message:
    sender_address = _Addr(ALICE)


class _Web:
    pages = {}

    @classmethod
    def render(cls, url, mode="text"):
        if url not in cls.pages:
            raise Exception("fetch failed")
        return cls.pages[url]


class _Nondet:
    web = _Web


class _Eq:
    @staticmethod
    def strict_eq(fn):
        return fn()


class _Public:
    write = staticmethod(lambda f: f)
    view = staticmethod(lambda f: f)


class _Contract:
    pass


class _TreeMap(dict):
    def __class_getitem__(cls, item):
        return dict


gl = types.SimpleNamespace(Contract=_Contract, message=_Message, nondet=_Nondet,
                           eq_principle=_Eq, public=_Public)
stub = types.ModuleType("genlayer")
stub.gl, stub.TreeMap, stub.u256 = gl, _TreeMap, int
stub.__all__ = ["gl", "TreeMap", "u256"]
sys.modules["genlayer"] = stub

spec = importlib.util.spec_from_file_location("prooflink", CONTRACT)
pl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pl)


def as_sender(address):
    _Message.sender_address = _Addr(address)


def new_contract():
    c = pl.ProofLink.__new__(pl.ProofLink)
    c.claims, c.by_owner, c.next_id = {}, {}, 1
    _Web.pages = {}
    as_sender(ALICE)
    return c


def claim(c):
    return json.loads(c.get_claim(1))


def raises(fn, *args):
    try:
        fn(*args)
    except Exception as e:
        return str(e)
    return None


# ---------- creating claims ----------
def test_code_is_bound_to_the_wallet_and_claim():
    c = new_contract()
    a = c.create_claim(URL)
    as_sender(BOB)
    b = c.create_claim(URL)
    code_a, code_b = c.get_code(a), c.get_code(b)
    assert code_a != code_b
    assert ALICE[2:12] in code_a and BOB[2:12] in code_b


def test_unsafe_urls_are_refused():
    c = new_contract()
    bad = [
        "http://example.com/a", "ftp://example.com/a", "https://", "https:///x",
        "https://exa mple.com/a", "https://localhost/a", "https://127.0.0.1/a",
        "https://10.0.0.5/a", "https://192.168.1.1/a", "https://172.20.0.1/a",
        "https://169.254.169.254/latest", "https://user:pw@example.com/a",
        "https://[::1]/a", "https://intranet/a", "https://printer.local/a",
        "https://example.com/" + "a" * 400,
    ]
    for u in bad:
        assert raises(c.create_claim, u), u


def test_public_urls_are_accepted():
    c = new_contract()
    for u in ["https://example.com/a", "https://raw.githubusercontent.com/x/y/main/README.md",
              "https://172.15.0.1/a", "https://sub.domain.org:8443/p?q=1#f"]:
        as_sender("0x" + "%040x" % abs(hash(u)))
        c.create_claim(u)


def test_one_active_claim_per_url_and_a_claim_cap():
    c = new_contract()
    c.create_claim(URL)
    assert "already have an active claim" in raises(c.create_claim, URL)
    c.revoke(1)
    c.create_claim(URL)                      # allowed again after revoking
    c2 = new_contract()
    for i in range(pl.MAX_CLAIMS_PER_OWNER):
        c2.create_claim("https://example.com/p%d" % i)
    assert "claim limit" in raises(c2.create_claim, "https://example.com/extra")


# ---------- verifying ----------
def test_missing_code_fails_and_present_code_verifies():
    c = new_contract()
    cid = c.create_claim(URL)
    _Web.pages[URL] = "nothing to see"
    c.verify(cid)
    assert claim(c)["status"] == "FAILED"
    _Web.pages[URL] = "hello " + c.get_code(cid).upper() + " bye"     # case-insensitive
    c.verify(cid)
    assert claim(c)["status"] == "VERIFIED" and claim(c)["attempts"] == 2
    assert c.is_verified(ALICE, URL) is True


def test_unreachable_page_is_a_failed_attempt_not_a_crash():
    c = new_contract()
    cid = c.create_claim(URL)
    c.verify(cid)                            # URL is not in the page dictionary
    assert claim(c)["status"] == "FAILED"


def test_code_must_be_a_whole_token():
    c = new_contract()
    for i in range(10):
        c.create_claim("https://example.com/p%d" % i)    # claim ids 1..10
    code1, code10 = c.get_code(1), c.get_code(10)
    assert code1 in code10                    # claim 1's code is a prefix of claim 10's
    _Web.pages["https://example.com/p0"] = "only " + code10
    c.verify(1)
    assert json.loads(c.get_claim(1))["status"] == "FAILED"
    _Web.pages["https://example.com/p0"] = "ok " + code1 + "."
    c.verify(1)
    assert json.loads(c.get_claim(1))["status"] == "VERIFIED"


def test_someone_elses_code_does_not_verify_my_claim():
    c = new_contract()
    cid_a = c.create_claim("https://example.com/shared")
    as_sender(BOB)
    cid_b = c.create_claim("https://example.com/other")
    _Web.pages["https://example.com/other"] = c.get_code(cid_a)    # Alice's code on Bob's page
    c.verify(cid_b)
    assert json.loads(c.get_claim(cid_b))["status"] == "FAILED"
    assert c.is_verified(BOB, "https://example.com/other") is False


# ---------- permissions, attempts, revoking ----------
def test_only_the_owner_can_verify_or_revoke():
    c = new_contract()
    cid = c.create_claim(URL)
    as_sender(BOB)
    assert "owner" in raises(c.verify, cid)
    assert "owner" in raises(c.revoke, cid)


def test_attempts_are_capped():
    c = new_contract()
    cid = c.create_claim(URL)
    for _ in range(pl.MAX_ATTEMPTS):
        c.verify(cid)
    assert "too many attempts" in raises(c.verify, cid)


def test_verified_claim_cannot_be_reverified_and_revoke_clears_it():
    c = new_contract()
    cid = c.create_claim(URL)
    _Web.pages[URL] = c.get_code(cid)
    c.verify(cid)
    assert "cannot be verified" in raises(c.verify, cid)
    c.revoke(cid)
    assert c.is_verified(ALICE, URL) is False
    assert "already revoked" in raises(c.revoke, cid)
    assert "cannot be verified" in raises(c.verify, cid)


def test_read_api():
    c = new_contract()
    c.create_claim(URL)
    listing = json.loads(c.get_claims_by_owner(ALICE.upper()))
    assert listing == [{"id": 1, "url": URL, "status": "PENDING"}]
    assert "claim not found" in raises(c.get_claim, 99)
    assert c.is_verified(BOB, URL) is False


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print("PASS", name)
        except Exception as e:  # noqa: BLE001
            failed += 1
            print("FAIL", name, "->", repr(e))
    print("\n%d passed, %d failed" % (len(tests) - failed, failed))
    sys.exit(1 if failed else 0)
