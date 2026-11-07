# ProofLink (Intelligent Contract)

Prove that a wallet controls a public web page, with GenLayer validators as the witnesses.

Anyone can say "this page is mine". ProofLink makes the claim checkable: the contract gives you a short code tied to your wallet, you put the code on the page, and every validator fetches the page itself and must agree the code is there. The result is an on-chain **verified link** that other contracts can read.

- **Contract (GenLayer Studio):** `0x1D306073Ff5867995b2d8E4458CDe97a9def985C`
- **Contract source:** [`prooflink.py`](./prooflink.py)
- **Tests:** [`tests/test_prooflink.py`](./tests/test_prooflink.py)

## How it works

```
create_claim(url) --> PENDING --verify--> VERIFIED
                          |                   |
                          +--> FAILED (retry, up to 5 attempts)
                          any status --revoke--> REVOKED
```

1. `create_claim(url)` stores a claim and returns your code, for example `prooflink-b2b565655d-1`. The code contains part of your wallet address and the claim number.
2. You add the code to the page.
3. `verify(claim_id)` makes every validator fetch the page (`gl.nondet.web.render`). They reach consensus with `gl.eq_principle.strict_eq`, so the true/false result must match exactly.
4. `is_verified(owner, url)` lets anyone, including other contracts, check the result.

## What it protects against

| Risk | How ProofLink handles it |
|---|---|
| Claiming a page you do not control | The page must contain a code that only your wallet's claim has. Someone else's code on the page does not verify your claim. |
| Only the claimant should verify or revoke | `verify` and `revoke` are rejected for any other wallet. |
| One claim's code matching inside another's (`...-1` in `...-10`) | The code must appear as a whole token: the character after it cannot be a letter or digit. |
| Validators fetching internal addresses | Only `https` links to public hosts. `localhost`, private and link-local IP ranges, `.local`/`.internal` hosts, links with credentials and IPv6 literals are refused. |
| Endless retries and spam | Up to 5 verify attempts per claim, 20 claims per wallet, one active claim per URL per wallet. |
| Unreachable page | Counts as a failed attempt, never a crash. |
| Stale links | `revoke` removes a claim from `is_verified`. |

## Read API (composable)

- `get_claim(claim_id)` returns the claim as JSON
- `get_code(claim_id)` returns the code to post
- `get_claims_by_owner(owner)` returns that wallet's claims
- `is_verified(owner, url)` returns `true` only for an active, verified claim by that wallet for that exact URL

## Tests

`tests/test_prooflink.py` runs the contract's real logic against a small stand-in for the `genlayer` library, with the web fetch replaced by a dictionary of pages. No node is needed:

```
python3 tests/test_prooflink.py
```

It covers code binding, URL refusal, whole-token matching, other wallets' codes, ownership checks, attempt and claim limits, revoking, and the read API (12 tests).

## Limits

- Proof is only as good as the page: if anyone else can edit the page (for example a comment section), they could add your code. Use a page only you can edit.
- The fetch sees the page as validators see it. Pages that need a login are not supported.
- Studio test network only. This is a verification primitive, with no payments or enforcement. A web app for it lives in its own project repository.
