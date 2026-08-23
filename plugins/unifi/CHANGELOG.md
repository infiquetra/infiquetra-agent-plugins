# Changelog

## [Unreleased]

## [2.0.5] - 2026-08-23

### Fixed

- **An innocent key no longer eats the line break before a strict one.** The
  whitespace around the assignment delimiter was `\s*`, which spans a newline. A
  `notes` key at the end of one line therefore matched, consumed the line break
  with it, and left the strict assignment on the next line with no preceding
  character to begin a fresh match against — so a credential written that way was
  accepted. The repository gate splits lines before scanning and refused the same
  text, which is how the two copies came to disagree. This is fail-open in the
  copy operators load, and it is the residual half of the swallow defect 2.0.4
  repaired along a single line.

  An assignment is now one line in both copies: the whitespace around the
  delimiter is horizontal only, and the value stops at a newline.

- **An assignment split across two lines is matched by neither copy.** The
  reference already said so; before this release the loaders matched it and only
  the gate did not, so the documented guarantee was false in the direction that
  flatters the loader.

### Testing

- A shared verdict corpus of twenty-seven lines is pinned in the loader suite and,
  in the portable catalog, across all three copies of the rule. The two defects
  above were invisible to per-part agreement tests: every constant and helper
  matched while the verdicts differed.

## [2.0.4] - 2026-08-22

### Changed

- **The value rule now grades the key, not the value.** A strict secret-bearing
  key assigned a single substantive literal is a credential whatever that literal
  looks like, and the entropy floor, the digit test and the length bar are gone.
  Those graded the value, and could not tell a technical word from a password in
  either direction: `oauth2` carries a digit and 2.585 bits of entropy, which is
  *less* than `rainbowtrout` at 3.085, so the rule refused the harmless word and
  accepted the real password. Which keys are strict is derived from
  `CREDENTIAL_NAME_FRAGMENTS`, the same taxonomy that grades property names, so
  the two halves of one rule can no longer drift into two dialects.

### Fixed

- **Digit-free passwords are no longer accepted.** A `password` key assigned
  `rainbowtrout` or `sunshine`, or an `api_key` assigned
  `correcthorsebattery`, all shipped accepted, because the retired rule required
  a digit or twenty-four characters before a value counted. Under a strict key
  there is now no floor below which a literal stops being a credential, so a
  `password` assigned the word `secret` is refused too.
- **Ordinary technical prose is no longer refused.** A `credentials` key
  followed by `oauth2 is configured at the controller`, a `token` followed by
  `base64 of the site identifier`, and a `secret` followed by
  `sha256 checksum recorded in the manifest` were all rejected as credentials.
  A strict key followed by several substantive words is a sentence about a
  credential rather than a credential, and in `description` and `notes` —
  the two fields the schema keeps for prose — that is allowed. Every other field
  in the contract holds an identifier or an enumerated value, so the allowance
  does not reach them.
- **A reference written across several pieces is read as one placeholder.**
  `token: {{ lookup }}` split into three tokens and the bare inner word was
  graded. Template expressions are collapsed before the value is split.

### Security

- The guarantee is now stated as it behaves. What it still does not do: a literal
  padded out with prose under a strict key in a prose field is not reported, and
  the rule reads one line at a time, so an assignment split across lines is not
  matched. Both limits are written down rather than left to be discovered.

## [2.0.3] - 2026-08-22

### Fixed

- **A credential standing behind a placeholder is no longer cleared.**
  `authorization: Bearer <redacted> <token>` passed: the rule graded a fixed
  window of two tokens, found the placeholder in the second slot, saw that it
  names a secret rather than being one, and never examined the real credential
  in the third. The rule now walks the value, stepping over auth scheme words and
  placeholders, and grades the first token that is neither. The captured span was
  also widened, because it stopped at `}` and so truncated
  `Bearer ${VAR} <token>` before the credential.
- **Ordinary operational prose is no longer rejected as a credential.**
  `token: rotation happens quarterly` and `secret: managed elsewhere` were
  refused. Entropy per character cannot separate English from a credential —
  `rotation` scores 2.50 against a 2.50 floor while `hunter2` scores 2.81 — and
  character-class mixing cannot either, since `Rotation` mixes case and `hunter2`
  does not. A digit does: every credential shape this rule is tested against
  carries one and no English word does, so a digit-free value must clear 24
  characters, above the longest word likely to appear in an operator's note.
- The walk stops at the first substantive token rather than searching the whole
  value. That is what keeps `auth: see ticket ABC-1234 for rotation` from being
  graded on its ticket number, which a keep-looking scan would have reached.

Both defects were introduced by the previous repair of this rule and were found
by two independent reviewers on the fifth review cycle of the portability pilot.

## [2.0.2] - 2026-08-22

### Fixed

- **The site-profile loader shipped here now enforces the 1.1 contract the package documents.**
  This loader was published pinned to schema `1.0` while the portable package it mirrors advanced
  its own contract to `1.1`, so one package disagreed with itself: an operator who authored the
  `1.1` document the package documents had it rejected outright by their Claude integration, with
  `UnsupportedSchemaVersionError`. `SUPPORTED_SCHEMA_VERSIONS` is now `("1.0", "1.1")` and
  `SCHEMA_IDENTIFIER` names `1.1`.
- **A credential written into a free-text value is refused here, as the contract already promised.**
  `1.1` adds no field and removes none; what it records is that the secret-free guarantee covers
  *values* and not only property names. This loader enforced the name half alone, so a controller
  password or bearer token pasted into `notes` was accepted on the Claude path while the portable
  loader refused the identical document. Accepting the version and enforcing its rule are one
  change — taking a `1.1` document while ignoring what `1.1` means would restate the same
  disagreement in a quieter form. A `1.0` document is held to the same rule, because a credential
  in a `1.0` profile is exactly as exposed.
- The ported rule grades the token *behind* an auth scheme word. `authorization: Bearer <token>`
  previously graded the word `Bearer`, which carries no entropy, and cleared the credential
  standing behind it; `Basic` and `Token` are shorter than the length floor, so those values were
  never examined at all. Values that name where a secret lives — `vault:` references, `${VAR}`,
  `<redacted>` — are still accepted, and ordinary prose is not graded, since several English words
  clear the entropy floor on their own.

## [2.0.1] - 2026-08-22

Repairs the caller side of the `Retry-After` defect. Fleet Core 0.25.1 taught the shared backoff
primitive to read both RFC 7231 forms of the header, but both UniFi clients still converted the
raw header with `int()` before raising, so the primitive only ever saw a hint the caller had
already failed to parse. Fixing the primitive alone was never sufficient, and the release that
fixed it said so in a characterization test.

**What went wrong.** A controller that answers a 429 with the HTTP-date form —
`Retry-After: Fri, 31 Dec 2100 23:59:59 GMT`, which is a form the specification allows and real
controllers send — made `int()` raise `ValueError` inside the request path. A `ValueError`
carries no `status_code`, so the shared primitive judged it non-retryable and propagated it
immediately. The client's `except _RateLimited` never saw it, the bare `except Exception` did,
and the operator got `Unexpected error: invalid literal for int() with base 10: ...` after
exactly one request, with no backoff and no retry.

**The fix.** Both clients now hand the raw header to the shared `parse_retry_after`, which
reduces either RFC 7231 form to seconds, or to `None` when there is no usable hint. The
`_RateLimited` signalling is unchanged, so a 429 still reaches the backoff primitive carrying its
status.

- A 429 whose `Retry-After` is an HTTP-date now backs off and retries, honoring the parsed delay
  (bounded by the primitive's 60-second maximum) instead of raising.
- A 429 whose `Retry-After` is delta-seconds behaves exactly as before.
- An absent or unparseable `Retry-After` is now treated as no hint at all and answered with the
  primitive's computed jittered backoff. This is a **behavior change**: the clients previously
  substituted a literal 60 for a missing header, which made every hint-less 429 sleep a flat
  60 seconds per attempt. The operator-facing exit surface is unchanged — when retries are
  exhausted with no usable hint, the reported `retry_after` is still 60.

The exit surface keeps its shape in every case: `retry_after` remains a whole number of seconds,
rounded up from a parsed hint.

**Why this is a patch and not a minor.** The one behavior change above is a change in how long the
client waits between its own retries, and the retry loop is internal — no command signature, no
output field, and no exit code moves. An installation that worked before works after, and the
generic `Unexpected error` it used to emit against a date-form `Retry-After` was never a contract
anyone could depend on. Under semantic versioning that is a bug fix.

Files: `skills/unifi-network/scripts/unifi_network_client.py`,
`skills/unifi-protect/scripts/unifi_protect_client.py`.

## [2.0.0] - 2026-08-22

Activates the work Units U6 and U7 authored and deliberately left unreleased. The hold was
lifted by the deployed-profile receipt for the operator site profile: its deployed SHA-256
digest equals the private input digest the pre-activation evidence was taken against, so that
evidence covers exactly the bytes now deployed. Evidence:
`docs/evidence/2026-08-22-unifi-transition-evidence.md`.

**Why this is a major version and not a minor one.** Three of the changes below require an
installation to do something before it works the way it did, and any one of them would carry
the bump on its own.

The removed controller-address default is the clearest case. Both clients previously fell back
to a baked-in address when neither `--host` nor `UNIFI_HOST` was given, so an invocation that
succeeded with only `UNIFI_API_KEY` set now exits 1. That is an incompatible change to
observable behavior, and this release records it as one. The obvious counterargument — that the
default was a defect rather than a promise, so removing it restores the contract rather than
breaking it — is a sound argument about whether the change is *right* and a poor one about
whether it *breaks callers*. Semantic versioning classifies compatibility, not intent. The
default was also a private-range address, so on any network but its author's it resolved to
whatever happened to occupy that address locally: usually nothing, and never anything the
caller had chosen. Replacing that silent misdirection with a named error is an improvement and
a change in observable behavior at the same time. Understating it would save a version number
and cost an operator a surprise.

Second, the `unifi-network-ops` agent no longer carries site topology in its own text. Until an
operator deploys a site profile, it answers `unknown` where it used to state subnets, host
ranges, and a camera count. No fact was lost — the relocation was proved fact by fact against
the deployed profile, fifty fields compared and fifty passed — but reading those facts again
requires a deployed profile, which is a new obligation on the installation.

Third, both skills dropped the non-specification `triggers` frontmatter field, so skill
activation is keyed by the specification's own fields alone. This is the lightest of the three
and would not carry a major bump by itself.

### Fixed - documentation now matches the shipped clients

- Removed every reference to the four UniFi Protect capabilities the client does not
  implement — camera stream URLs, PTZ control, event listing, and NVR info. They were
  deleted from `unifi_protect_client.py` in commit `8a14ad49` on 2026-03-17, when the
  Protect base URL moved to `/proxy/protect/integration/v1`, and no changelog entry ever
  recorded the removal. Surfaces corrected: the Protect skill, the Protect API reference,
  the plugin README, the slash command document, the `unifi-network-ops` agent definition,
  the plugin manifest description, and the 1.0.0 entry below.
- Re-derived `references/protect-api-endpoints.md` from the client source. It documented the
  cookie-authenticated `/proxy/protect/api` base, which this client has never called, and
  gave `PATCH` for a liveview update the client sends as `PUT`.
- Corrected `references/udm-api-endpoints.md` on every path where it disagreed with the
  network client: traffic routes are v2 `trafficroutes` rather than v1 `rest/routing`;
  static DNS is v2 `static-dns` rather than the v1 `rest/setting/dnsmasq` settings object;
  DHCP leases are `stat/dhcp` rather than `stat/dhcp_lease`; alarms are `list/alarm` rather
  than `stat/alarm`; backup is `stat/backup` plus `cmd/backup` rather than `cmd/system` plus
  `dl/backup`; the VPN group is three `vpnconn` paths rather than one `stat/vpn`; and the
  device-locate body is a single `locate` command rather than a `set-locate` and
  `unset-locate` pair.

### Added - previously undocumented network capabilities

- The network skill now documents all twelve resource groups and all fifty-two actions the
  client implements. The `wlans`, `vpn`, and `backup` groups were entirely undocumented, as
  were the `devices adopt`, `devices forget`, and `stats dpi` actions.
- The Protect skill now documents all six resource groups and all twenty-one actions.
- `tests/test_unifi_docs_match_code.py` asserts the agreement mechanically against the real
  argument parsers and the client sources, so this class of drift fails a build instead of
  surviving five months unnoticed.

### Removed - the hard-coded controller address, from both clients

- `UNIFI_HOST` is required and has no default. Both clients previously fell back to one
  operator's controller address, which every installation received as though it were
  universal. With no `--host` and no `UNIFI_HOST`, each client now prints a structured error
  naming the variable and exits 1 before any network call, exactly as it already does for a
  missing `UNIFI_API_KEY`. Substituting a different address would only have moved the problem.
- A present-but-empty `UNIFI_HOST` now fails the same way. It previously built the malformed
  URL `https:///proxy/network/api/s/default` and failed later, one layer away from the mistake.
- Every remaining address in the plugin's documentation is an RFC 5737 documentation address,
  and the agent definition uses named placeholders, so no example can be mistaken for a real
  operator's addressing.

### Changed - the agent reads site context from a profile instead of carrying it

- The `unifi-network-ops` agent no longer states a site topology. Its controller address, four
  subnets, three host ranges, Proxmox master, camera count, and wireless standard were one
  operator's facts shipped to every installation; they moved into an operator site profile.
- `skills/unifi-network/scripts/site_profile_loader.py` is the Claude adapter's reader for the
  portable contract `urn:infiquetra:unifi:site-profile:1.0`, released on branch
  `orch/orch-2026-08-22-unifi-run-a` at commit `097909d7` of `infiquetra-agent-plugins`. It
  imports the standard library only, so a host with no third-party parser can still read a
  profile. The Claude repository carries its own loader because the upstream agent cannot
  depend on a file that lives only in the other repository.
- Resolution order is the `UNIFI_SITE_PROFILE` environment variable, then the path remembered
  in `${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/config.json`, then no profile at all.
  No profile is a supported state, not an error; a path an operator named explicitly must
  exist, and a missing one is reported rather than quietly skipped.
- The no-inference rule is enforced in code. Without a profile, and for any subject a profile
  does not name, trust role, criticality, ownership, and intended policy return an explicit
  unknown. Absent intent is reported as absent, never as a default and never as a guess.
- `tests/test_unifi_site_profile_loader.py` carries the relocated profile and asserts, fact by
  fact, that everything the agent used to say survives in it and that none of it survives in
  the agent.

### Changed - skill frontmatter conforms to the open Agent Skills specification

- Both skills drop the non-specification `triggers` and `script` frontmatter fields. Their
  content moved into each skill's body as a "When to use this skill" list and a "Script"
  line, so nothing is lost and the frontmatter carries only permitted fields.

### Changed - the three release surfaces move together

- Version `1.2.1 → 2.0.0` on the plugin manifest, on the `unifi` entry in
  `.claude-plugin/marketplace.json`, and on this changelog's top dated heading. The
  marketplace entry is regenerated from `plugin.json` via `scripts/sync_marketplace.py`
  rather than hand-edited, because it is a generated mirror and not a source.

## [1.2.1] - 2026-08-08

### Added - house-style presentation contract on the network-ops agent (#704)

- `unifi-network-ops` agent definition gains a "Presentation contract (Infiquetra house style)" section, copied verbatim from `plugins/house-style/references/subagent-presentation-preamble.md`.

## [1.2.0] - 2026-07-05

### Changed
- Both `unifi-network` and `unifi-protect` clients adopt the shared fleet-commons `retry_backoff`
  primitive (#348): a 429 response now retries with bounded exponential backoff (honoring
  `Retry-After`) instead of hard-exiting, preserving the existing typed error surface on
  exhaustion. Vendors the byte-identical `fleet_commons_shim.py` into each client dir (drift-guarded).

## [1.1.0] - 2026-06-21

### Changed
- `unifi-network-ops` agent: add frontmatter and pin `model: sonnet` (R1/R2a tiering;
  network ops are structured/investigative, not judgment-heavy decisions).

## [1.0.0] - 2026-03-17

### Added
- `unifi-network` skill: full UniFi Network API coverage (devices, clients, networks, firewall, traffic routes, port forwards, WLANs, VPN, DNS, DHCP, stats, backup)
- `unifi-protect` skill: UniFi Protect Integration API coverage (cameras, liveviews, lights, sensors, chimes, viewers)
- Dry-run by default for all write operations — `--confirm` required to execute
- API key auth via `UNIFI_API_KEY` (`X-Api-Key` header) — bypasses CSRF tokens on UniFi OS 3.x+
- SSL verification disabled by default with `urllib3.InsecureRequestWarning` suppressed (UDM uses self-signed cert)
- `unifi-network-ops` agent with investigation workflow, common task examples, and safety rules
- Binary snapshot support: save to file or base64-encode into JSON output
