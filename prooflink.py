# v0.2.16
# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
import json

# Claim lifecycle: PENDING -> VERIFIED, or FAILED (retry allowed) -> VERIFIED, or REVOKED
PENDING, VERIFIED, FAILED, REVOKED = "PENDING", "VERIFIED", "FAILED", "REVOKED"
MAX_ATTEMPTS = 5
MAX_URL = 300
MAX_CLAIMS_PER_OWNER = 20


def url_problem(url: str) -> str:
    """Return a reason the URL is not acceptable, or '' if it is fine.
    Validators fetch this URL, so only public https pages are allowed."""
    if not url.startswith("https://"):
        return "url must start with https://"
    if len(url) > MAX_URL:
        return "url is too long (max 300 characters)"
    if " " in url or "\n" in url or "\t" in url:
        return "url must not contain spaces"
    rest = url[len("https://"):]
    host = rest
    for sep in ("/", "?", "#"):
        host = host.split(sep)[0]
    if host == "":
        return "url has no host"
    if "@" in host or host.startswith("["):
        return "url must not contain credentials or IPv6 literals"
    host = host.split(":")[0].lower()
    if host == "" or "." not in host:
        return "url host must be a public domain name"
    if host == "localhost" or host.endswith(".local") or host.endswith(".internal"):
        return "url host must be public"
    parts = host.split(".")
    if all(p.isdigit() for p in parts):
        nums = [int(p) for p in parts]
        a, b = nums[0], nums[1] if len(nums) > 1 else 0
        if (a in (0, 10, 127) or (a == 169 and b == 254) or (a == 192 and b == 168)
                or (a == 172 and 16 <= b <= 31)):
            return "url host must be public"
    return ""


def contains_code(text: str, code: str) -> bool:
    """True if `code` appears in `text` as a whole token (case-insensitive).
    The character after the code must not be a letter or digit, so the code for
    claim 1 is not found inside the code for claim 10."""
    t = str(text).lower()
    c = code.lower()
    start = 0
    while True:
        i = t.find(c, start)
        if i < 0:
            return False
        j = i + len(c)
        if j >= len(t) or not t[j].isalnum():
            return True
        start = i + 1


class ProofLink(gl.Contract):
    claims: TreeMap[u256, str]       # claim_id -> JSON claim record
    by_owner: TreeMap[str, str]      # owner address (lowercase) -> JSON list of claim ids
    next_id: u256

    def __init__(self):
        self.next_id = u256(1)

    # ---------- helpers ----------
    def _sender(self) -> str:
        return gl.message.sender_address.as_hex.lower()

    def _load(self, claim_id: int) -> dict:
        raw = self.claims.get(u256(claim_id))
        if raw is None:
            raise Exception("claim not found")
        return json.loads(raw)

    def _save(self, claim_id: int, claim: dict):
        self.claims[u256(claim_id)] = json.dumps(claim)

    def _owner_ids(self, owner: str) -> list:
        raw = self.by_owner.get(owner.lower())
        return json.loads(raw) if raw else []

    # ---------- lifecycle ----------
    @gl.public.write
    def create_claim(self, url: str) -> int:
        url = url.strip()
        problem = url_problem(url)
        if problem:
            raise Exception(problem)
        owner = self._sender()
        existing = self._owner_ids(owner)
        if len(existing) >= MAX_CLAIMS_PER_OWNER:
            raise Exception("claim limit reached for this wallet")
        for cid in existing:
            old = self._load(cid)
            if old["url"] == url and old["status"] != REVOKED:
                raise Exception("you already have an active claim for this url")
        claim_id = int(self.next_id)
        self.next_id = u256(claim_id + 1)
        # The code is bound to the requesting wallet, so posting someone else's
        # code on a page does not let a different wallet claim that page.
        code = "prooflink-" + owner[2:12] + "-" + str(claim_id)
        claim = {
            "id": claim_id, "owner": owner, "url": url, "code": code,
            "status": PENDING, "attempts": 0,
        }
        self._save(claim_id, claim)
        ids = self._owner_ids(owner)
        ids.append(claim_id)
        self.by_owner[owner] = json.dumps(ids)
        return claim_id

    @gl.public.write
    def verify(self, claim_id: int):
        claim = self._load(claim_id)
        if self._sender() != claim["owner"]:
            raise Exception("only the claim owner can verify")
        if claim["status"] not in (PENDING, FAILED):
            raise Exception("claim cannot be verified in status " + claim["status"])
        if claim["attempts"] >= MAX_ATTEMPTS:
            raise Exception("too many attempts, create a new claim")

        url = claim["url"]
        code = claim["code"].lower()

        def check() -> bool:
            try:
                text = gl.nondet.web.render(url, mode="text")
            except Exception:
                return False
            return contains_code(text, code)

        # Every validator fetches the page itself; the boolean must match exactly.
        found = gl.eq_principle.strict_eq(check)

        claim["attempts"] += 1
        claim["status"] = VERIFIED if found else FAILED
        self._save(claim_id, claim)

    @gl.public.write
    def revoke(self, claim_id: int):
        claim = self._load(claim_id)
        if self._sender() != claim["owner"]:
            raise Exception("only the claim owner can revoke")
        if claim["status"] == REVOKED:
            raise Exception("already revoked")
        claim["status"] = REVOKED
        self._save(claim_id, claim)

    # ---------- composable read API ----------
    @gl.public.view
    def get_claim(self, claim_id: int) -> str:
        return json.dumps(self._load(claim_id))

    @gl.public.view
    def get_code(self, claim_id: int) -> str:
        return self._load(claim_id)["code"]

    @gl.public.view
    def get_claims_by_owner(self, owner: str) -> str:
        out = []
        for cid in self._owner_ids(owner):
            c = self._load(cid)
            out.append({"id": c["id"], "url": c["url"], "status": c["status"]})
        return json.dumps(out)

    @gl.public.view
    def is_verified(self, owner: str, url: str) -> bool:
        for cid in self._owner_ids(owner):
            c = self._load(cid)
            if c["url"] == url.strip() and c["status"] == VERIFIED:
                return True
        return False
