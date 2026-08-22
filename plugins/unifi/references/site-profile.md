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
for. Every object in [`../schemas/site-profile.schema.json`](../schemas/site-profile.schema.json)
is closed, and every property name is additionally checked against
credential-shaped names, so a field such as `password`, `api_token`,
`client_secret`, or `private_key` is rejected wherever it appears in the
document. The portable loader in
[`../scripts/site_profile.py`](../scripts/site_profile.py) applies the same rule
and reports the offending field by name.

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

The current contract version is `1.0`, published under the schema identifier
`urn:infiquetra:unifi:site-profile:1.0`. The identifier is a URN rather than a
URL because nothing here ever resolves a schema over the network, and a
fetchable identifier would imply otherwise.

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
