import importlib.util, sys, pathlib
root = pathlib.Path("/Users/jefcox/workspace/infiquetra/infiquetra-agent-plugins")
copies = {
 "target site_profile.py": root/"plugins/unifi/scripts/site_profile.py",
 "gate check_repo.py":     root/"scripts/check_repo.py",
 "upstream loader":        root/"plugins/unifi/com.infiquetra.claude/skills/unifi-network/scripts/site_profile_loader.py",
}
FP = [  # Ox F-01: technical words with digits, first substantive position
 "credentials: oauth2 is configured at the controller",
 "token: base64 of the site identifier",
 "secret: sha256 checksum recorded in the manifest",
 "auth: vlan40 handles the guest network",
]
RECALL = [  # Ox A-01: digit-free secrets 6..23 chars
 "password: rainbowtrout",
 "password: sunshine",
 "api_key: correcthorsebattery",
]
for label, path in copies.items():
    spec = importlib.util.spec_from_file_location("m_"+label.replace(" ","_").replace(".","_"), path)
    m = importlib.util.module_from_spec(spec); sys.modules[spec.name] = m; spec.loader.exec_module(m)
    cand = getattr(m, "_credential_candidate", None)
    shaped = getattr(m, "_is_credential_shaped", None)
    rx = getattr(m, "CREDENTIAL_VALUE_ASSIGNMENT", None) or getattr(m, "CREDENTIAL_ASSIGNMENT", None)
    print(f"\n=== {label} ===")
    for line in FP + RECALL:
        mt = rx.search(line)
        if not mt:
            print(f"  no-regex-match      | {line}"); continue
        c = cand(mt.group(2))
        fires = bool(c) and shaped(c)
        tag = "FIRES (finding)" if fires else "passes (no find)"
        print(f"  {tag:<16} | candidate={c!r:<26} | {line}")
