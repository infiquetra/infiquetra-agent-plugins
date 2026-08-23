# Operator site profile

The site profile is how an operator tells this package what a UniFi controller
cannot say about itself. A controller reports that a host exists, that a network
is configured, and that a firewall rule is present. It cannot report that the
host is critical, that the network is meant to be untrusted, who owns either, or
which policy the operator intended. That intent is the profile's entire subject
matter.

The profile is **optional**. The package is fully usable with no profile
present, and nothing in a profile is treated as a universal assumption about how
a site is arranged.

## What a profile carries, and what it never carries

A profile carries five things and nothing else:

| Field | Meaning |
| --- | --- |
| `site` | The operator's name and description for the site. |
| `subjects` | Things at the site the operator has an intent about, each with an optional `trust_role`, `criticality`, `ownership`, and `notes`. |
| `intended_policies` | Policies the operator means to hold, and the subject identifiers each covers. |
| `operational_constraints` | Standing constraints on how the site may be operated. |
| `schema_version` | The contract version of the document. |

A profile **never** carries a credential. This is enforced rather than asked
for, and it is enforced on what a field *holds* as well as on what it is
*called*. Two rules do the work, both of them in the portable loader
[`../scripts/site_profile.py`](../scripts/site_profile.py), which is the code
that actually runs when a profile is read.

**The name rule.** Every object in
[`../schemas/site-profile.schema.json`](../schemas/site-profile.schema.json) is
closed, and every property name is checked against credential-shaped names, so a
field such as `password`, `api_token`, `client_secret`, or `private_key` is
rejected wherever it appears in the document. The loader applies the same rule
and reports the offending field by name.

**The value rule.** A credential written into an ordinary field is rejected too.
This is the half that used to be missing: the field name `notes` is innocent, so
a secret pasted into it satisfied every guard the contract had. Every string in
the document is now inspected, at any depth, by two narrow families:

1. **Literal credential formats.** AWS access key ids, GitHub, Slack and Stripe
   tokens, Google, Anthropic and OpenAI API keys, JSON web tokens, private key
   blocks, and credentials embedded in a URL. These are credentials wherever
   they appear, so they are rejected on sight.
2. **A strict secret-bearing key assigned a literal value.** A string that sets
   `password`, `secret`, `token`, `api_key`, `bearer`, `authorization`,
   `passphrase`, `private_key`, `client_secret`, `access_key`, `auth`, or a near
   neighbour, to a single substantive value is rejected — whatever that value
   looks like. There is no entropy floor, no digit test and no length bar, so
   `password: rainbowtrout` and `password: secret` are both refused.

   Which keys are strict is the same list that grades property names, read once
   and used in both halves of the rule.

The loader names the property and says which family fired, so the report is
actionable rather than a bare refusal.

> **What changed in 2.0.4 and 2.0.5, and why it is written down here.** The rule used to
> grade the *value*: at least six characters clearing 2.5 bits of entropy, later
> narrowed to "carries a digit, or is 24+ characters without one". Grading the
> value cannot work, and it failed in both directions at once. `oauth2` carries a
> digit and 2.585 bits, so ordinary technical prose was refused; `rainbowtrout`
> carries 3.085 bits and no digit, so a real password was accepted. The
> discriminator fired on the lower-entropy inputs and passed the higher-entropy
> ones. The key decides now, and the value is not graded at all. 2.0.5 then
> made an assignment line-scoped in every copy, after a review found the
> loaders reading across a line break where the gate did not.

### What the value rule deliberately does not do

Stating this precisely matters more than stating it generously, because an
operator who is told "credentials are excluded" will act on it.

- **It does not scan for bare high-entropy strings.** A profile legitimately
  carries sha256 digests, long identifiers, and generated names. A rule that
  fires on those is a rule that gets switched off within a day, and a switched
  off rule protects nothing. A digest in a `notes` or `description` value is
  accepted, and there is a test that keeps it accepted.
- **It accepts a value that merely names a secret.** Pointing at where a
  credential lives is one of the things a profile is *for*. A note saying the
  controller password is held in the operator's vault is accepted, as is a
  reference such as `vault:` or `env:`, a redacted marker, and an unexpanded
  variable.
- **It reads a sentence as a sentence.** In `description` and `notes` — the two
  fields the schema keeps for prose — a strict key followed by *several*
  substantive words is a description rather than a credential, so
  `token: base64 of the site identifier` and `credentials: oauth2 is configured
  at the controller` are accepted. Every other field in the contract holds an
  identifier or an enumerated value, so the allowance does not reach them.
- **A literal padded out with prose is not reported.** The value
  `password: rainbowtrout is the controller value` passes, because the
  several-words reading above cannot distinguish it from a description. This is
  the price of not rejecting ordinary technical writing, and it is the sharpest
  edge of the rule.

  Writing that example down is itself a demonstration: this page has to keep
  each sample assignment on one line, because a line break would leave a bare
  `password: <literal>` behind and the repository gate would refuse the file —
  correctly, since it cannot know a leak from an illustration.
- **It reads one line at a time.** An assignment split across two lines is not
  matched by either the loader or the gate: the whitespace around the delimiter is
  horizontal only, and the value stops at the line break.

  This sentence was false when it was first written. The loaders used `\s*`, which
  spans a newline, so they *did* match a split assignment while the gate did not —
  the documented guarantee described the weaker of the two, in the direction that
  flattered the loader. Worse, the same greedy whitespace let an innocent key at
  the end of a line consume the line break and hide a strict assignment on the
  next one, which the gate caught and the loaders did not. Both are repaired in
  2.0.5, and a shared verdict corpus now pins the two shapes in all three copies.

So the accurate wording of the guarantee is this: **a profile is validated to be
free of credential-shaped field names, and of credentials written as values in
the two families above. That is defense in depth against an accident, not a
proof of absence.** Nothing in this contract can stop an operator who is
determined to write a secret into a free-text field, and no operator should read
this validation as permission to stop being careful.

The same two families are what the repository's own validation gate applies to
every file under `plugins/`. The loader re-states them rather than importing
them, because it is portable package source that has to load on a host where
that gate does not exist; the repository's test suite pins the two copies to
each other so they cannot drift into two different rules.

A profile also carries no observed inventory. Raw discovery output — addresses,
hostnames, hardware addresses, camera names — belongs outside any repository, in
a location the operator names.

## Format

The format is JSON, parsed with the standard library. A host with no
third-party parser installed can still read a profile, which is what keeps the
optional-profile promise true on a minimal runtime. An operator who prefers a
friendlier authoring format may keep the source in that format and render JSON
at deployment time; what the portable core reads is JSON.

## Where the profile comes from

Resolution order, highest precedence first:

1. The `UNIFI_SITE_PROFILE` environment variable.
2. The remembered configured path, read from
   `${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/config.json`.
3. No profile at all.

The third outcome is a valid, fully supported state rather than an error. This
is the same environment-variable-then-default precedence the UniFi clients
already use for `UNIFI_HOST`, so the chain reads the same way to anyone who
knows that code.

The documented default location for a deployed runtime profile is
`${XDG_CONFIG_HOME:-~/.config}/infiquetra/unifi/site-profile.json`. That is a
default *path*, not a default *profile*: nothing at that path still means no
profile.

Two failures are deliberately loud rather than quiet:

- `UNIFI_SITE_PROFILE` naming a file that does not exist fails and does **not**
  fall back to the configured path. Falling back would answer a question about
  the wrong site.
- A configuration file naming a profile that no longer exists reports exactly
  that, and does not silently revert to running without a profile. The operator
  said a profile was there; the honest answer is that it has gone.

## First setup: exactly three paths

[`../scripts/site_profile_setup.py`](../scripts/site_profile_setup.py) presents
the choice and remembers the answer, so it is not asked again on every use.
There are three paths and there is no fourth:

1. **Use an existing site profile.** Supply the path. The file is validated
   against the contract before the choice is remembered, so a malformed profile
   is rejected now rather than on first use.

   ```bash
   python3 site_profile_setup.py --choose existing-profile --profile-path PATH
   ```

2. **Generate a proposed profile from read-only discovery.** Credential-safe,
   read-only discovery writes a proposal for operator review. The proposal
   records what the controller reports and marks every intent field unknown,
   because observing a host cannot establish who owns it or how much it matters.
   Nothing is applied: review the proposal, fill in the intent yourself, then
   return and choose `existing-profile`.

   ```bash
   python3 site_profile_setup.py --choose discovery-proposal
   ```

3. **Continue without a profile.** Fully supported, with the limits below.

   ```bash
   python3 site_profile_setup.py --choose discovery-only
   ```

Running the entrypoint with no arguments presents the three paths on first
setup, and reports the remembered choice afterwards. `--list` always prints the
three paths. Output is JSON on standard output, matching the output discipline
the UniFi clients already use.

## The no-inference rule

Without a profile, the package reports actual controller state and infers
nothing about intent. This is enforced in code, not described in prose: a query
for a trust role, criticality, ownership, or intended policy returns an explicit
unknown that callers render as unknown.

The same answer is given for a subject a profile does not mention. Absent intent
is reported as absent — never as a default, and never as a guess.

In discovery-only mode the following remain unknown:

- No trust role is known for any subject.
- No criticality is known for any subject.
- No ownership is known for any subject.
- No intended policy or operational constraint is known.
- Controller state may be reported; operator intent may not be inferred from it.

## Schema versions

A profile declares `schema_version`. A version this package does not recognize
is rejected outright rather than partially applied, because a half-understood
statement of intent is worse than none.

The current contract version is `1.1`, published under the schema identifier
`urn:infiquetra:unifi:site-profile:1.1`. The identifier is a URN rather than a
URL because nothing here ever resolves a schema over the network, and a
fetchable identifier would imply otherwise.

Version `1.1` adds no field and removes none. What changed is the value rule
above: the set of documents this contract calls valid is now smaller, and that
is a change to the contract even though the document shape is identical. The
identifier moved with it, because leaving the same identifier on a document that
now means something different is the kind of silent drift this package refuses
everywhere else.

A `1.0` document still loads, and the value rule is applied to it. A credential
in a `1.0` profile is exactly as exposed as one in a `1.1` profile, and refusing
to read `1.0` would strand every profile already deployed without protecting
anything. An operator with a valid `1.0` profile has nothing to do; changing
`schema_version` to `1.1` is an accurate relabelling, not a migration.

## Custody is the operator's, and is not part of this contract

This contract defines a *path* and a *document shape*. It says nothing about
where an operator keeps the authoritative copy, and it requires no particular
arrangement for producing one.

Infiquetra's own instance keeps its profile in a private repository and deploys
it to the documented runtime path with its existing configuration-management
harness. That is one operator's arrangement, described here only as an example.
It is not required, not assumed, and not part of the portable contract. Any
equivalent method of getting a valid JSON document to the resolved path
satisfies this contract completely.

## Example

Inert example values only. No real site is described.

```json
{
  "schema_version": "1.0",
  "site": {
    "identifier": "example-site",
    "description": "Example site used for documentation and tests."
  },
  "subjects": [
    {
      "kind": "network",
      "identifier": "example-guest-network",
      "trust_role": "untrusted",
      "criticality": "routine",
      "ownership": "example-team",
      "notes": "Operator-supplied intent, not observed state."
    },
    {
      "kind": "host",
      "identifier": "example-host",
      "trust_role": "trusted",
      "criticality": "critical",
      "ownership": "example-team"
    }
  ],
  "intended_policies": [
    {
      "identifier": "example-isolation-policy",
      "description": "Example hosts stay off the guest network.",
      "applies_to": ["example-host"]
    }
  ],
  "operational_constraints": [
    {
      "identifier": "example-change-window",
      "description": "Changes are applied during the example maintenance window."
    }
  ]
}
```

## Vocabularies

| Field | Permitted values |
| --- | --- |
| `subjects[].kind` | `site`, `network`, `host`, `device`, `client` |
| `subjects[].trust_role` | `trusted`, `restricted`, `untrusted`, `unknown` |
| `subjects[].criticality` | `critical`, `important`, `routine`, `unknown` |
| `subjects[].ownership` | Free text, or omitted |

The literal `unknown` is permitted anywhere a vocabulary allows it, and means
the same as omitting the field: the operator has stated that the intent is not
known, rather than leaving a reader to assume one.
