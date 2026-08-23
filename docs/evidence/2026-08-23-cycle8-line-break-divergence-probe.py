"""Cycle-8 blocker evidence: the three copies disagree on where a line ends.

Run from the repository root. Prints one row per line-break character for two
shapes, and a JSON reachability check showing the divergent characters survive
``json.load`` and reach the loader an operator runs.
"""
import importlib.util
import json
import sys


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


target = load("plugins/unifi/scripts/site_profile.py", "sp")
gate = load("scripts/check_repo.py", "cr")
loader = load(
    "plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py",
    "ld",
)

BREAKS = [
    ("\\n", "\n"), ("\\r", "\r"), ("\\r\\n", "\r\n"), ("\\v", "\v"), ("\\f", "\f"),
    ("\\x1c", "\x1c"), ("\\x1d", "\x1d"), ("\\x1e", "\x1e"), ("NEL", "\x85"),
    ("U+2028", " "), ("U+2029", " "),
]

divergent = 0
for title, shape, expected in (
    ("A. swallow: 'see notes:<BREAK>password=hunter2' must FIRE", "see notes:{}password=hunter2", True),
    ("B. split:   'password:<BREAK>  hunter2' must NOT fire", "password:{}  hunter2", False),
):
    print(title)
    for label, character in BREAKS:
        text = shape.format(character)
        verdicts = (
            loader._credential_in_text(text, descriptive=True) is not None,
            target._credential_in_text(text, descriptive=True) is not None,
            bool(gate.credential_findings(text, include_assignments=True)),
        )
        agrees = verdicts == (expected,) * 3
        divergent += not agrees
        print(f"   {label:<8} loader={verdicts[0]!s:<5} target={verdicts[1]!s:<5} "
              f"gate={verdicts[2]!s:<5} {'ok' if agrees else 'DIVERGES'}")
    print()

print(f"divergent rows: {divergent} of {2 * len(BREAKS)}\n")

print("Reachability through ordinary valid JSON:")
for label, document in (
    ("escaped \\r", r'{"schema_version":"1.1","site":{"identifier":"s","description":"d"},'
                    r'"subjects":[{"kind":"network","identifier":"n",'
                    r'"notes":"see notes:\rpassword=hunter2"}]}'),
    ("literal U+2028", '{"schema_version":"1.1","site":{"identifier":"s","description":"d"},'
                       '"subjects":[{"kind":"network","identifier":"n",'
                       '"notes":"see notes: password=hunter2"}]}'),
):
    parsed = json.loads(document)
    try:
        loader.validate_profile(parsed)
        verdict = "ACCEPTED — the credential loads unseen"
    except loader.ProfileInvalidError:
        verdict = "refused"
    print(f"   {label:<16} survives json.load, loader verdict: {verdict}")
