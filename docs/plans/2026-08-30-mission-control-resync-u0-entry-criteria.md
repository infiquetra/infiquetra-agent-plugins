# U0 entry-criteria note — mission-control resync 2.12.2 to 2.15.2, pin proof

**Date.** 2026-08-30 · **Unit.** U0 of the [issue-50 resync plan](2026-08-30-issue-50-mission-control-resync-plan.md) ·
**Child issue.** [infiquetra/infiquetra-agent-plugins#51](https://github.com/infiquetra/infiquetra-agent-plugins/issues/51) ·
**Parent issue.** [infiquetra/infiquetra-agent-plugins#50](https://github.com/infiquetra/infiquetra-agent-plugins/issues/50) ·
**Runbook.** [portable-plugin-port.md v1.1.0](../runbooks/portable-plugin-port.md) ·
**Branch.** `orch-agent-plugins-50` · **Base SHA.** `ab939ffcb20272fb12d8c6616ec81b067847e1d4`

This note closes the runbook's entry criteria for the 2.15.2 resynchronization
and records the pin proof, so every later unit builds on a proven pin rather
than an assumed one. Every command below is a captured transcript — the exact
command and its exact output, pasted verbatim, never reconstructed after the
fact (runbook v1.1.0 Phase 2 capture rule).

The headline result: the upstream suite is **green at the exact pin**
`3b2b7083fdda8e39e213b5f4acf9f8301d60dd52`, proven by running it in a
**disposable scratch clone** created for this run — not from the local
read-only upstream checkout, and not by quoting continuous-integration
reporting, which is corroborating evidence and not the same act.

## Provenance of this record

This note supersedes the first U0 attempt, commit
`ab939ffcb20272fb12d8c6616ec81b067847e1d4`. That attempt ran partly on a
DeepSeek-direct API-key fallback route and is **not accepted as evidence**.
The record in this revision was produced entirely on
**opencode-go/deepseek-v4-pro at max effort**: every command was re-executed
fresh on that route — a new scratch clone, a new suite run, new gate runs —
and the transcripts below are those fresh captures, not figures copied
forward from the superseded attempt. The superseded attempt's note content is
replaced in this commit.

---

## 1. The upstream suite, green at the pin, from a disposable scratch clone

Operator ruling 1 fixes the pin at `3b2b7083` and requires the upstream suite
proven green at that exact commit from a disposable scratch clone. The
commands are the ones the pinned upstream README documents (Development /
Setup): `uv sync --locked --extra dev`, then `uv run pytest`.

The scratch clone was created fresh with `mktemp` under the system temporary
directory (`/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz`)
and removed after capture (§9). The clone and checkout were quiet (no
output); the readback proves the checked-out revision:

```
$ SCRATCH=$(mktemp -d /var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-XXXXXX)
$ git clone --quiet https://github.com/infiquetra/infiquetra-claude-plugins "$SCRATCH/upstream"
$ git -C "$SCRATCH/upstream" checkout --quiet 3b2b7083
$ git -C "$SCRATCH/upstream" rev-parse HEAD
3b2b7083fdda8e39e213b5f4acf9f8301d60dd52
```

### 1.1 Suite transcript (verbatim)

`````
$ uv sync --locked --extra dev
Using CPython 3.12.11
Creating virtual environment at: .venv
Resolved 84 packages in 6ms
   Building infiquetra-claude-plugins @ file:///private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream
      Built infiquetra-claude-plugins @ file:///private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream
Prepared 1 package in 437ms
Installed 81 packages in 196ms
 + annotated-doc==0.0.4
 + annotated-types==0.7.0
 + anyio==4.13.0
 + attrs==26.1.0
 + authlib==1.7.0
 + bandit==1.9.4
 + boto3==1.43.2
 + botocore==1.43.2
 + certifi==2026.4.22
 + cffi==2.0.0
 + charset-normalizer==3.4.7
 + click==8.3.3
 + coverage==7.13.5
 + cryptography==47.0.0
 + dparse==0.6.4
 + fakeredis==2.35.1
 + filelock==3.29.0
 + h11==0.16.0
 + httpcore==1.0.9
 + httpx==0.28.1
 + httpx-sse==0.4.3
 + idna==3.13
 + infiquetra-claude-plugins==1.0.0 (from file:///private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream)
 + iniconfig==2.3.0
 + jinja2==3.1.6
 + jmespath==1.1.0
 + joblib==1.5.3
 + joserfc==1.6.4
 + jsonschema==4.26.0
 + jsonschema-specifications==2025.9.1
 + librt==0.9.0
 + markdown-it-py==4.0.0
 + markupsafe==3.0.3
 + marshmallow==4.3.0
 + mcp==1.27.1
 + mdurl==0.1.2
 + mypy==1.20.2
 + mypy-extensions==1.1.0
 + nltk==3.9.4
 + packaging==26.2
 + pathspec==1.1.1
 + pluggy==1.6.0
 + pycparser==3.0
 + pydantic==2.13.3
 + pydantic-core==2.46.3
 + pydantic-settings==2.14.1
 + pygments==2.20.0
 + pyjwt==2.13.0
 + pytest==9.0.3
 + pytest-cov==7.1.0
 + python-dateutil==2.9.0.post0
 + python-dotenv==1.2.2
 + python-multipart==0.0.29
 + pyyaml==6.0.3
 + redis==7.4.0
 + referencing==0.37.0
 + regex==2026.4.4
 + requests==2.33.1
 + rich==15.0.0
 + rpds-py==0.30.0
 + ruamel-yaml==0.19.1
 + ruff==0.15.12
 + s3transfer==0.17.0
 + safety==3.7.0
 + safety-schemas==0.0.16
 + shellingham==1.5.4
 + six==1.17.0
 + sortedcontainers==2.4.0
 + sse-starlette==3.4.4
 + starlette==1.1.0
 + stevedore==5.7.0
 + tenacity==9.1.4
 + tomlkit==0.14.0
 + tqdm==4.67.3
 + typer==0.25.1
 + types-pyyaml==6.0.12.20260508
 + types-requests==2.33.0.20260508
 + typing-extensions==4.15.0
 + typing-inspection==0.4.2
 + urllib3==2.6.3
 + uvicorn==0.48.0
$ uv sync exit=0
$ uv run pytest
============================= test session starts ==============================
platform darwin -- Python 3.12.11, pytest-9.0.3, pluggy-1.6.0 -- /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/bin/python
cachedir: .pytest_cache
rootdir: /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream
configfile: pyproject.toml
testpaths: tests, plugins/*/tests
plugins: cov-7.1.0, anyio-4.13.0
collecting ... collected 6935 items
[... 6,937 lines elided from the middle of the captured transcript: 6,927 per-test PASSED lines, 7 SKIPPED lines, 1 XFAIL line, and 2 blank separator lines. Full verbose output was captured at run time in the disposable scratch clone; the head, tail, warnings summary, coverage table, final summary, and exit status are retained verbatim above and below. Nothing here is reconstructed. ...]
=============================== warnings summary ===============================
tests/test_saga_engine_dispatch.py::test_team_execution_two_process_claim_race_both_proceed_and_one_state_persists
tests/test_saga_engine_dispatch.py::test_team_execution_two_process_claim_race_both_proceed_and_one_state_persists
  /Users/jefcox/.local/share/uv/python/cpython-3.12-macos-aarch64-none/lib/python3.12/multiprocessing/popen_fork.py:66: DeprecationWarning: This process (pid=54688) is multi-threaded, use of fork() may lead to deadlocks in the child.
    self.pid = os.fork()

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================================ tests coverage ================================
______________ coverage: platform darwin, python 3.12.11-final-0 _______________

Name                                                                                  Stmts   Miss  Cover   Missing
-------------------------------------------------------------------------------------------------------------------
plugins/agent-launcher/skills/agent-launcher/scripts/launcher.py                        624     77    88%   45, 47, 50-51, 73, 76-77, 79, 133, 287, 291, 311, 339, 377-378, 400, 423, 585, 723-724, 739-740, 773, 814, 817, 914, 925, 977, 1027, 1109, 1187-1193, 1200, 1218, 1234, 1244, 1246, 1254, 1262-1263, 1323-1328, 1334-1336, 1338-1351, 1354-1355, 1357-1361, 1364, 1369-1373, 1381-1382, 1386
plugins/agy/scripts/agy_delegate.py                                                     891    271    70%   76, 82, 86, 119, 129, 226, 297, 310-313, 323-331, 335-361, 380-388, 517-518, 553-604, 622, 709-711, 713-715, 722, 724, 732, 755-762, 825-826, 922-924, 951-953, 958, 969, 974-977, 996-997, 1004, 1006, 1031, 1055, 1072, 1085, 1104, 1141, 1158-1227, 1242, 1245-1247, 1249, 1341-1379, 1383-1426, 1440, 1449, 1462, 1467, 1503, 1522-1528, 1534, 1542-1558, 1562, 1568-1572, 1576-1583, 1593-1594, 1614, 1657-1658, 1666-1670, 1829, 1859-1861, 1868-1870, 1879-1880, 1886, 1891, 1925-1931, 1982, 1984, 1986, 1988, 1990, 1992, 2001, 2006, 2015-2024, 2031, 2041-2050
plugins/codex/scripts/codex_delegate.py                                                 695     97    86%   102, 111, 117, 121, 144, 156, 160, 209, 214-222, 228-231, 327-328, 381, 390, 395, 414-415, 417-419, 422-424, 426-427, 540-541, 549-560, 571-574, 589-590, 620, 708-710, 737-739, 745, 756, 761-764, 784-785, 795, 849, 856-857, 869, 896-897, 971-973, 1039, 1059-1061, 1090, 1096, 1125, 1138, 1307-1308, 1475-1481, 1564-1565, 1568, 1588-1597
plugins/deploy/scripts/mint_tag.py                                                      134     92    31%   24-34, 41-44, 48, 71-72, 76, 87-98, 104-114, 120-127, 133-139, 145-163, 176-184, 192-196, 200-212, 216-254
plugins/deploy/scripts/query_deployments.py                                              89     34    62%   26-35, 45, 49-60, 64-72, 130-132, 149-151, 155-159
plugins/fleet-core/scripts/fleet_commons/audit_store.py                                 156      5    97%   71, 128-129, 213, 357
plugins/fleet-core/scripts/fleet_commons/bridge_receipt.py                               92      7    92%   38-39, 41, 48, 140, 144, 162
plugins/fleet-core/scripts/fleet_commons/concurrency_policy.py                           45      0   100%
plugins/fleet-core/scripts/fleet_commons/cost_weights.py                                 62      5    92%   33, 54, 58, 93, 112
plugins/fleet-core/scripts/fleet_commons/delegation_audit.py                            250     51    80%   49-50, 52, 59, 177, 187-196, 204, 214-223, 260, 263-265, 267, 320-321, 332, 336-338, 340, 349-350, 361, 420, 443-444, 446-451, 461
plugins/fleet-core/scripts/fleet_commons/delegation_state.py                            213     47    78%   80, 82, 84, 147, 150, 160, 218, 247-248, 275, 277, 279, 296, 323-324, 383-385, 389-391, 395-402, 406-424, 428-430
plugins/fleet-core/scripts/fleet_commons/effort_rider.py                                 37      1    97%   35
plugins/fleet-core/scripts/fleet_commons/intent_envelope.py                             340     12    96%   198, 354, 373, 381, 384, 574, 593, 735, 775, 945-946, 959
plugins/fleet-core/scripts/fleet_commons/liveness_engine.py                             173      7    96%   160, 162, 164, 166, 251, 253-254
plugins/fleet-core/scripts/fleet_commons/output_attestation.py                           45      2    96%   43, 47
plugins/fleet-core/scripts/fleet_commons/plugin_resolution.py                            86      4    95%   98-99, 118, 127
plugins/fleet-core/scripts/fleet_commons/render_tier_table.py                            33      3    91%   23, 107-108
plugins/fleet-core/scripts/fleet_commons/retry_backoff.py                                91      0   100%
plugins/fleet-core/scripts/fleet_commons/tier_palette.py                                108      4    96%   48, 51, 71, 209
plugins/fleet-core/scripts/fleet_commons/tier_resolver.py                               197     21    89%   47, 194, 231, 286, 294, 301, 306-307, 320, 328, 342, 368, 371, 374, 377, 383, 433-437
plugins/fleet-core/scripts/fleet_commons_shim.py                                         99     46    54%   49-52, 56-76, 80-94, 104, 117, 119, 121, 123-124, 137-138, 166-168
plugins/hermes-profile-evolution/hooks/profile_edit_guard.py                             85     17    80%   48, 61, 75, 82, 85, 88, 95, 100, 115, 123, 128, 131-134, 137-138
plugins/hermes-profile-evolution/scripts/profile_request.py                             160     27    83%   64, 89, 99, 101, 106, 108, 111, 123, 127, 132, 160, 162, 165-166, 223-224, 232-233, 250, 265, 271, 274, 301-302, 319-321
plugins/mission-control/config/generated/check_issue_contract_parity.py                  90     25    72%   76-77, 79-80, 119-135, 145, 149, 191-194, 201
plugins/mission-control/config/generated/issue_contract_data.py                          11      0   100%
plugins/mission-control/config/generated/issue_contract_shim.py                          12      0   100%
plugins/mission-control/scripts/board_census.py                                          75     10    87%   133-134, 154-155, 175-180
plugins/mission-control/scripts/check_pagination.py                                      92     14    85%   70, 72-73, 172-173, 190-200
plugins/mission-control/scripts/executor_profile_lint.py                                 67      1    99%   79
plugins/mission-control/scripts/sdlc_manager.py                                        3300   1011    69%   102, 107, 121, 124-125, 127, 130, 138, 217-220, 225-280, 373, 403-404, 411, 425, 469, 494, 498-509, 516, 519, 527, 534-538, 720, 722-723, 730, 738, 837-838, 846-847, 1195, 1200-1204, 1209-1213, 1227, 1229, 1239-1277, 1307, 1325-1331, 1356-1357, 1360, 1432-1433, 1449-1451, 1458, 1463, 1468, 1471-1472, 1479-1522, 1527-1546, 1566-1608, 1613-1642, 1647-1685, 1694-1725, 1739, 1747-1748, 1750, 1757, 1777-1806, 1833, 1872, 1893, 1896, 1899, 1908, 2005, 2011, 2039-2065, 2092-2093, 2095-2098, 2123, 2134-2163, 2182, 2188, 2193, 2197-2198, 2228-2229, 2238, 2243-2290, 2295-2317, 2322-2358, 2368-2380, 2385-2406, 2411-2452, 2457-2461, 2477, 2480-2481, 2496-2497, 2500-2518, 2523-2570, 2575, 2580-2624, 2629-2635, 2705, 2722-2726, 2730-2732, 2817, 2824-2842, 2975, 2980, 3090, 3272, 3274, 3313, 3342-3352, 3356-3366, 3415-3430, 3437-3438, 3456, 3459, 3463, 3468, 3485, 3501, 3506, 3510, 3531, 3542-3543, 3548, 3581, 3676-3677, 3688-3689, 3703, 3731-3732, 3742-3743, 3745, 3980, 4034-4036, 4048-4071, 4113-4115, 4122-4134, 4166-4167, 4188, 4197-4235, 4451, 4454, 4472, 4478, 4484, 4486, 4493, 4499, 4501, 4503, 4505, 4515, 4519-4520, 4538, 4558-4559, 4578, 4584-4585, 4613, 4638-4639, 4651, 4664, 4687, 4690, 4704-4705, 4712-4715, 4720, 4723, 4727, 4752, 4760, 4763, 4765, 4838, 4840, 4847-4851, 5004-5023, 5054-5055, 5065, 5068-5069, 5071, 5113, 5115, 5117, 5137, 5176, 5180, 5188-5189, 5260, 5288, 5296-5297, 5299, 5320, 5324-5325, 5340, 5342, 5344, 5403, 5405, 5407, 5409, 5423-5424, 5476, 5490, 5495, 5499-5501, 5505-5511, 5521-5530, 5534-5542, 5546-5549, 5555, 5592-5593, 5617, 5626, 5643, 5650-5652, 5666, 5669, 5696, 5757, 5805, 5821, 5876, 5961, 5983, 5990, 5994, 6020-6021, 6024-6026, 6040-6042, 6058, 6073-6074, 6131, 6150-6154, 6180-6185, 6193, 6216-6234, 6243-6256, 6380-6381, 6396-6397, 6404-6405, 6425, 6490, 6495-6499, 6511-6525, 6533-6554, 6559-6568, 6573, 6575-6576, 6582-6584, 6597-6598, 6643-6650, 7158, 7162, 7172-7179, 7182-7238, 7242, 7245-7248, 7251-7256, 7259-7266, 7269-7276, 7279-7288, 7318, 7320, 7331-7342, 7345-7346
plugins/mission-control/scripts/sync_template_docs.py                                   123     30    76%   80, 108, 118, 134, 147, 221, 279, 284-296, 301-309, 314-327
plugins/orchestrate/skills/orchestrate/scripts/orchestrate.py                          2414    427    82%   499, 556, 759-761, 781-782, 854-855, 858-861, 925, 929, 932-933, 936, 943, 1046, 1088, 1109, 1114, 1117, 1141-1142, 1144, 1152, 1158, 1162, 1165, 1168, 1173, 1244-1245, 1357, 1365, 1411, 1456, 1495-1501, 1508-1527, 1540-1547, 1549-1550, 1561, 1567, 1580, 1591-1611, 1666, 1675, 1700, 1704, 1729, 1801, 1817, 1906, 1990-1991, 1993, 2023-2024, 2035-2042, 2203-2205, 2253-2259, 2264-2276, 2284-2285, 2316, 2319-2333, 2340-2362, 2402-2403, 2405, 2469, 2481, 2483, 2496-2497, 2503, 2507-2511, 2542-2547, 2558, 2560, 2580-2581, 2639-2640, 2643-2644, 2742, 2750, 2856-2862, 2890-2894, 2898, 2905-2908, 2928, 2956-3025, 3029-3030, 3068-3105, 3118-3119, 3158-3159, 3184-3185, 3205-3206, 3208, 3211, 3214-3215, 3222, 3229, 3233-3234, 3236, 3361-3367, 3386-3391, 3440-3442, 3461-3471, 3486-3487, 3501-3502, 3507-3508, 3614, 3729-3747, 3784, 3788, 3790, 3806, 3838-3843, 3847, 3850, 3858, 3861, 3872, 3877, 3883, 3885, 3932-3933, 3963-3965, 3971, 4045-4058, 4074-4079, 4081-4082, 4086-4087, 4094-4095, 4102, 4140, 4176, 4183, 4218, 4222, 4243, 4254, 4267, 4272, 4288, 4300-4302, 4327-4328, 4331-4332, 4351-4352, 4364-4365, 4389-4390, 4439-4441, 4444, 4487, 4494-4495, 4560, 4565, 4575-4576, 4619-4621, 4645-4646
plugins/redis-channel/server/__init__.py                                                  1      0   100%
plugins/redis-channel/server/channel.py                                                 459    107    77%   130-134, 155-159, 187-188, 243, 248, 267-269, 300-302, 351-353, 377-378, 402-403, 408-409, 416-417, 446, 453, 468, 476-477, 535-536, 548, 558, 574, 585-586, 637-638, 667-674, 694-695, 723, 732-739, 821-822, 838, 851-852, 867-868, 886, 909, 942-967, 977-986, 1002-1010, 1093, 1108-1109, 1137, 1140-1141, 1149-1151, 1176-1177, 1198-1211
plugins/redis-channel/server/notifier.py                                                 53      3    94%   110-114
plugins/redis-channel/server/presence.py                                                160      8    95%   33, 334-335, 350-351, 376, 378-379
plugins/redis-channel/server/protocol.py                                                 73      0   100%
plugins/redis-channel/server/redis_client.py                                             27      4    85%   59-67
plugins/redis-channel/server/redis_consumer.py                                          105     12    89%   63, 100, 135-143, 199-200
plugins/redis-channel/server/redis_producer.py                                           15      0   100%
plugins/redis-channel/server/registry.py                                                 69      2    97%   142, 147
plugins/redis-channel/server/session_id.py                                               29      0   100%
plugins/saga/hooks/delegation_stop_audit_hook.py                                         82     11    87%   55-57, 75-76, 103, 107, 123-124, 153-155
plugins/saga/hooks/delegation_tripwire_hook.py                                           73     16    78%   48-50, 61, 64, 67-70, 103-105, 116-117, 121, 127-128
plugins/saga/hooks/journal_nudge_hook.py                                                 73     20    73%   99-112, 117-132, 149-151, 157, 162, 185
plugins/saga/hooks/pre_push_gate_hook.py                                                179     16    91%   92, 193, 199-200, 261-263, 275, 294, 297-298, 335, 344-349, 353
plugins/saga/hooks/team_spawn_residency_hook.py                                         143     17    88%   122-123, 137, 161-162, 164, 204, 275-296
plugins/saga/hooks/validate_json_hook.py                                                 64     46    28%   37, 41-108
plugins/saga/scripts/adjustment_envelope.py                                             257     34    87%   128, 130, 193, 203, 206, 311-313, 336-340, 348, 398, 430, 453, 513-519, 521-523, 525-527, 529-531, 536
plugins/saga/scripts/board_progression.py                                               202     12    94%   110, 127-128, 156, 413, 419-420, 424, 430, 466, 522, 594
plugins/saga/scripts/bridge_signatures.py                                                68      8    88%   28, 31, 35, 37, 66, 76, 78, 85
plugins/saga/scripts/capability_elo.py                                                  146     31    79%   129, 133, 152, 211, 233-270
plugins/saga/scripts/ceremony_hazards.py                                                 84      6    93%   127-128, 143, 216, 284, 286
plugins/saga/scripts/chaperone_economics.py                                             258     17    93%   64, 66, 69, 132, 165, 201, 217, 388, 391, 414, 420, 448, 451, 478, 484, 498, 554
plugins/saga/scripts/check_engine_registry.py                                            48     15    69%   29, 32, 65-68, 72-81
plugins/saga/scripts/closure_gate.py                                                    120      2    98%   305-306
plugins/saga/scripts/completeness_gate.py                                               159     63    60%   81, 87-101, 124-130, 154-155, 169, 179-180, 225-260, 265-275
plugins/saga/scripts/concurrency_governor.py                                            168     18    89%   28-54, 98, 149, 216, 251, 317, 319, 327
plugins/saga/scripts/deploy_handoff.py                                                  244     10    96%   181, 184, 237-238, 417, 420-421, 423, 459, 484
plugins/saga/scripts/detect_deploy_strategy.py                                           74     42    43%   26, 41, 51-59, 63, 67-73, 77-78, 82-90, 94-98, 102-120
plugins/saga/scripts/discover_subissues.py                                               53     14    74%   51-54, 82-83, 158-161, 165-168
plugins/saga/scripts/dispatch_settlement.py                                             951    126    87%   171, 182, 195, 202, 234, 244, 251, 254, 260, 274, 281, 298, 348, 361, 402, 411, 445, 451, 455, 484, 501, 524, 528, 555, 565, 619, 638, 644-647, 649, 655, 667, 670-671, 673, 686, 688, 691, 704, 709, 719, 723, 725-744, 750, 752, 757-764, 767, 778-779, 781, 790, 795, 803, 807, 809, 812, 835, 848-862, 895, 932, 940, 1104, 1184, 1408, 1430, 1482-1495, 1498, 1502, 1571, 1607-1614, 1627, 1684, 1711, 1742, 1759, 1787-1793, 1800-1802, 1845, 1856, 1860, 1944, 1975, 1989-1992, 2005, 2041, 2043-2047
plugins/saga/scripts/effort_ledger.py                                                   127     15    88%   75, 77, 114, 124, 148, 240-252, 256-259
plugins/saga/scripts/engine_benchmark.py                                                210     61    71%   89, 94, 96, 98, 108, 112, 115-116, 129, 131, 145, 151, 155, 160, 162, 165, 179, 188, 199, 236, 311-326, 330-332, 336-399
plugins/saga/scripts/engine_bridge_http.py                                               90      6    93%   104, 140, 181, 190-191, 193
plugins/saga/scripts/engine_calibration.py                                              160     35    78%   101-102, 117, 123-126, 277, 311, 316-347
plugins/saga/scripts/engine_dispatch.py                                                 886     99    89%   145, 147, 149, 153, 155, 167, 173, 213-214, 219-220, 226, 235, 256, 259, 348-349, 353-355, 527-528, 533-534, 582, 806-807, 819, 980, 1021, 1040-1041, 1059, 1140-1142, 1159, 1175-1176, 1185, 1188, 1205, 1230, 1282, 1309, 1318, 1341, 1379-1380, 1401, 1403, 1410-1411, 1434, 1442, 1523, 1623-1624, 1632, 1664, 1697, 1708-1709, 1713, 1724-1725, 1745, 1751-1752, 1763, 1844-1845, 1852, 1894, 1939, 1973-1978, 1983-1984, 1986, 1992, 2013, 2084, 2098, 2125, 2135, 2164, 2169, 2188-2189, 2207, 2240, 2242, 2311, 2313, 2325, 2328
plugins/saga/scripts/engine_onboarding.py                                               277     39    86%   90-91, 99, 131, 184, 202, 204, 224, 241, 245, 247, 250-251, 260, 263, 265, 294, 301, 304, 316, 323, 331, 337, 343, 349, 355, 358, 365-366, 368, 375-376, 388-389, 391, 397, 432-433, 468
plugins/saga/scripts/engine_overlay.py                                                  121     10    92%   63-64, 71, 77, 81, 83, 90, 95, 124, 178
plugins/saga/scripts/engine_promotion.py                                                112      2    98%   142-143
plugins/saga/scripts/engine_recommend.py                                                134     14    90%   85, 88-89, 110-115, 138, 149, 173, 189, 216, 221, 253
plugins/saga/scripts/engine_registry.py                                                 481     41    91%   56, 62, 69, 76, 90, 98, 104-106, 115, 117, 119, 125, 137, 142, 152, 183, 216, 257, 288, 334, 339, 415, 499, 504, 507, 530, 540, 555, 570, 577, 589, 647, 696, 706, 719, 726-730, 754, 831
plugins/saga/scripts/engine_registry_cli.py                                             168     24    86%   127-141, 154, 165-166, 227-228, 230, 310, 313, 316
plugins/saga/scripts/engine_registry_conformance.py                                      89      8    91%   70-72, 74, 89-91, 140
plugins/saga/scripts/engine_resolver.py                                                 400     46    88%   265, 298, 336, 362, 385, 419, 433, 437, 443, 450, 452, 460, 469, 522, 552, 574, 584-589, 705-710, 792, 795, 798, 856, 860, 867, 869, 909, 925-930, 934-944, 953, 966, 973
plugins/saga/scripts/engine_stale_report.py                                             107      8    93%   64, 67-68, 84, 186, 213-215
plugins/saga/scripts/envelope_token.py                                                  320     16    95%   129, 132-133, 185, 230, 234, 269, 523-524, 661, 693-696, 740, 761-762
plugins/saga/scripts/evidence_ledger.py                                                 277     14    95%   79, 154, 163, 166-167, 332, 385, 447, 468, 473, 482, 557, 699-700
plugins/saga/scripts/execution_spec.py                                                 1511    101    93%   923-930, 956, 959-960, 996, 1034, 1054, 1143-1144, 1204, 1207, 1242, 1267, 1279, 1425, 1555, 1632, 1788, 1816, 1851, 1855, 1904-1905, 1921, 1926, 1929, 1936-1937, 1999, 2003, 2133-2134, 2146-2147, 2173, 2201, 2208-2210, 2213-2226, 2238-2239, 2252-2253, 2284-2285, 2369-2370, 2382-2383, 2476-2477, 3155, 3179-3185, 3220, 3377, 3582, 3643, 3715, 3958, 4127, 4232, 4261, 4395, 4484-4514, 4524, 4526, 4535
plugins/saga/scripts/find_inflight_work.py                                               27      0   100%
plugins/saga/scripts/fleet_commons_shim.py                                               99     44    56%   49-52, 56-76, 80-94, 104, 117, 119, 121, 123-124, 166-168
plugins/saga/scripts/fleet_doctor.py                                                    854     54    94%   263-266, 285, 287, 310, 334, 371, 400, 407, 646-657, 700-711, 756, 758, 771, 834, 839, 844, 850, 936, 1149-1150, 1157, 1168-1173, 1224, 1227, 1237, 1279-1282, 1378-1383, 1419-1426, 1482, 1496, 1502, 1505, 1781-1782
plugins/saga/scripts/gate_divergence_reader.py                                          102     26    75%   79, 89-90, 119, 122, 137-138, 141-145, 148, 206-218, 222-234
plugins/saga/scripts/handoff_envelope.py                                                103     37    64%   27, 29, 36-38, 44, 46, 50, 52, 60, 63-64, 77-85, 93, 114, 163, 177-185, 189-200
plugins/saga/scripts/intent_envelope.py                                                 131     53    60%   150-152, 156-163, 167-174, 178-181, 185-187, 191-197, 201-247, 251-256
plugins/saga/scripts/issue_progress.py                                                   64      0   100%
plugins/saga/scripts/lifecycle_state.py                                                 131      5    96%   36, 108, 114-115, 549
plugins/saga/scripts/lint_gate_absence_contract.py                                      243     61    75%   79, 122, 125, 131, 195, 202-204, 267, 275, 280-281, 347-348, 362-363, 372-397, 401-423, 427-453
plugins/saga/scripts/liveness_events.py                                                 502     74    85%   150, 156, 168, 174, 177, 183, 186, 214, 281, 296, 298, 300, 320, 326, 328, 348, 350, 367, 371, 373, 385, 390, 416, 466, 468, 470, 476, 528, 534, 538, 567, 571, 730, 747, 760, 766, 783, 789, 805, 826, 847, 854, 867, 909, 936, 963-969, 973-977, 981-983, 987-997, 1001-1013, 1017-1024, 1083-1085
plugins/saga/scripts/load_saga_context.py                                                18      0   100%
plugins/saga/scripts/manifest_reader.py                                                 124      3    98%   73, 87, 109
plugins/saga/scripts/manifest_store.py                                                  215     32    85%   164, 181, 191-192, 195-196, 210-213, 262-263, 266-267, 269, 389-390, 396-401, 404-406, 413-414, 423, 431-434
plugins/saga/scripts/merge_watcher.py                                                   192      5    97%   113, 199, 244-245, 401
plugins/saga/scripts/outcome.py                                                         985    126    87%   185-186, 189, 254-255, 301, 354, 574-577, 882, 929-932, 978, 1017, 1050-1051, 1073, 1316, 1547-1568, 1606, 1637-1639, 1782-1787, 1812, 1818-1819, 1871, 1914-1925, 1946-1948, 2020, 2023-2024, 2059, 2075, 2079, 2140, 2143, 2146, 2506-2518, 2521, 2537, 2559-2560, 2601, 2652-2668, 2670-2675, 2683, 2687, 2693-2696, 2701-2711, 2715, 2730-2743, 2748-2756, 2758-2761, 2763-2770, 2772-2783, 2799, 2810-2828
plugins/saga/scripts/outcome_board_sync.py                                               97      8    92%   130-134, 148-150, 291
plugins/saga/scripts/outcome_compat.py                                                  521     43    92%   51, 216, 242, 249, 255, 262, 274, 282, 364, 379, 403, 421, 508-509, 570, 579, 608, 642-643, 697, 717, 745, 753, 794, 812, 820, 835, 878, 886, 902, 929, 933, 945, 1046, 1054, 1167-1168, 1265, 1290, 1321, 1357, 1461, 1524
plugins/saga/scripts/outcome_costs.py                                                   118      1    99%   108
plugins/saga/scripts/outcome_decompose.py                                               174     18    90%   85, 98, 112, 117-119, 131, 163, 174-176, 213, 240-244, 338
plugins/saga/scripts/outcome_dispatcher.py                                              227     10    96%   505-507, 540, 543, 560, 645, 765-767
plugins/saga/scripts/outcome_edges.py                                                    85      5    94%   57-58, 112, 130-131
plugins/saga/scripts/outcome_gate_transport.py                                           63      1    98%   80
plugins/saga/scripts/outcome_github.py                                                  193     38    80%   105-106, 108, 113, 118, 130-131, 133, 159, 162, 166, 198, 201-202, 204, 268-269, 277, 281-282, 294-295, 297, 321-322, 346-360
plugins/saga/scripts/outcome_intent.py                                                  229     16    93%   162, 200, 212, 226-232, 294, 362, 400, 436, 566-567
plugins/saga/scripts/outcome_liveness.py                                                 97      1    99%   154
plugins/saga/scripts/outcome_merge.py                                                   176      9    95%   173, 226, 318-319, 342-343, 468-469, 488
plugins/saga/scripts/outcome_orchestrator.py                                            126     13    90%   89, 262-263, 340-362
plugins/saga/scripts/outcome_projection.py                                               41     15    63%   108-128
plugins/saga/scripts/outcome_reconcile.py                                               158     14    91%   106-107, 109, 113, 117-120, 164, 226, 230, 233, 279, 444
plugins/saga/scripts/outcome_report.py                                                  145      5    97%   204, 301-304
plugins/saga/scripts/outcome_spec.py                                                    322      9    97%   135, 160, 165, 170, 243, 457, 459, 695, 835
plugins/saga/scripts/outcome_store.py                                                   408     27    93%   116-117, 124, 244, 371, 398, 464, 577, 650-651, 678-679, 745, 778, 783, 790, 797-798, 810-811, 864-870
plugins/saga/scripts/outcome_worktrees.py                                               281     22    92%   153, 155, 158, 161, 274, 342-348, 355, 392, 447, 464-465, 537-538, 645-646, 649, 652, 655
plugins/saga/scripts/override_rate_reader.py                                            133      5    96%   159, 180, 183, 206-207
plugins/saga/scripts/parse_issue.py                                                      76     10    87%   62, 121-123, 127-133
plugins/saga/scripts/promote_scan.py                                                    297      1    99%   175
plugins/saga/scripts/provenance_manifest.py                                             292     14    95%   191, 335, 375, 380, 397, 402-404, 495, 603, 605, 607, 625, 633
plugins/saga/scripts/provider_control_chart.py                                          106     11    90%   69, 123, 190-192, 199-205
plugins/saga/scripts/pulse.py                                                           249     28    89%   78, 140-141, 148-149, 163, 248, 286-287, 295-302, 424, 443-445, 461-471, 478-479, 647, 655
plugins/saga/scripts/qa_health_score.py                                                  36     14    61%   93-98, 102-119
plugins/saga/scripts/reconcile.py                                                       485     20    96%   90, 92, 107, 109, 113, 291, 305, 368, 418, 486, 555, 576, 642, 717, 744-745, 841, 870, 875, 877
plugins/saga/scripts/reconcile_controller.py                                            167     20    88%   155, 167, 236, 268, 359, 453-465, 540-543, 559, 562, 579
plugins/saga/scripts/render_docs_visuals.py                                             194     35    82%   37-40, 393, 398-401, 407-426, 430-434, 438-440
plugins/saga/scripts/reversibility_certificate.py                                       117      7    94%   123, 165, 323, 369, 377, 443, 455
plugins/saga/scripts/review_consensus.py                                               1223    192    84%   254, 260, 265, 271, 277, 344, 347, 357, 483, 485, 487, 489, 491, 495, 497, 500, 505, 528-529, 558, 560, 562, 564, 573-574, 595, 597, 599, 602, 608-609, 643, 645, 647, 651, 656, 663, 667, 671, 706-707, 729, 732, 740-743, 751-754, 779, 781, 786, 842, 859, 861, 868-871, 888, 897, 980, 1003, 1007, 1011, 1019, 1023, 1027, 1031, 1076, 1091, 1093, 1095, 1097, 1101, 1104, 1110, 1114, 1125, 1135, 1137, 1139, 1141, 1145, 1149, 1152, 1154, 1157, 1159, 1233, 1243, 1289, 1296-1297, 1340-1346, 1410, 1427, 1441, 1445, 1449, 1454, 1468, 1470, 1475, 1477, 1556, 1561, 1569, 1595, 1602, 1604, 1612, 1629, 1649, 1686, 1714, 1730, 1816, 1863, 1878, 1883, 1887, 1907-1908, 1920, 1930, 1933, 1953-1954, 1957, 1967, 1974-1975, 2023, 2026, 2030, 2047, 2049, 2149, 2151, 2155, 2159, 2161, 2180, 2218-2222, 2286, 2291, 2316, 2328-2329, 2333, 2339, 2343, 2345, 2347, 2349, 2357, 2365, 2373, 2383, 2385, 2393, 2403, 2405, 2409, 2449, 2558, 2560, 2563, 2569, 2574, 2576, 2600, 2619, 2650, 2656, 2659, 2663, 2668, 2682, 2688
plugins/saga/scripts/run_ledger.py                                                      209      8    96%   202, 210-212, 304, 330-331, 360
plugins/saga/scripts/saga.py                                                            680     51    92%   52-53, 139, 368, 435, 440, 444-445, 453, 459, 473, 481, 502, 523, 567-568, 670, 693-694, 736, 963, 1204, 1207-1208, 1293, 1296, 1364, 1370, 1388, 1395, 1653-1665, 1674-1676, 1681-1692, 1710-1715
plugins/saga/scripts/saga_spore.py                                                      235     23    90%   99, 102, 105-106, 108, 142-143, 148-151, 177, 194, 218-219, 230-231, 294-295, 309, 360, 362, 466
plugins/saga/scripts/scaffold_checkpoint.py                                              37      0   100%
plugins/saga/scripts/second_opinion.py                                                 1024    249    76%   117, 147, 151, 153, 155, 159, 161, 201, 227, 230, 232, 258, 273, 285, 288, 294, 325, 327, 334, 338, 355, 358, 392, 396, 428, 431, 458, 464, 468, 472, 476, 478, 482, 486, 488, 502, 506, 508, 526, 564, 570, 593-595, 601-624, 631-635, 639-673, 678-703, 706-731, 734-757, 761-784, 793, 796, 798, 804, 820, 843, 846, 848, 883-885, 898-899, 903, 906, 910, 913, 937, 944, 955, 962, 968, 996, 1024, 1063, 1066, 1068, 1098-1100, 1112, 1114, 1118, 1120, 1147, 1187-1188, 1207, 1220, 1278, 1296-1297, 1303-1309, 1335, 1340, 1343, 1349, 1352, 1354, 1370-1371, 1383, 1387, 1389, 1391, 1405, 1427, 1435, 1438, 1458, 1462, 1464, 1507, 1539, 1551-1552, 1580, 1583, 1588, 1632-1641, 1643, 1645, 1668-1669, 1689, 1694, 1700-1704, 1711, 1721, 1723, 1731, 1742-1743, 1776-1777, 1783, 1789, 1806, 1818-1820, 1841, 1859, 1872, 1936, 1960, 1993, 1995, 1998, 2001, 2010, 2016, 2023, 2029, 2031, 2038, 2041, 2047
plugins/saga/scripts/ship_ceremony.py                                                   468     16    97%   583-584, 590, 668-669, 693-694, 698-700, 1067-1068, 1131, 1208, 1572, 1692
plugins/saga/scripts/ship_receipt.py                                                    123     12    90%   115, 163-166, 187, 228-232, 280-286
plugins/saga/scripts/ship_teardown.py                                                   468     53    89%   316, 336, 339, 342-343, 369, 507, 521, 535, 546, 561-562, 578-579, 589-593, 626-627, 632, 658, 664-668, 691, 703, 724, 733-738, 741, 787, 806-815, 817-826, 956-964, 966-967, 983-999
plugins/saga/scripts/ship_undo.py                                                       201      9    96%   338, 355, 443, 455, 605-606, 653-655
plugins/saga/scripts/spec_table.py                                                      172     12    93%   49, 57, 65, 67, 70, 72-77, 79, 86, 110, 162
plugins/saga/scripts/spend_authority.py                                                  46      2    96%   56, 63
plugins/saga/scripts/spend_estimate.py                                                  146     16    89%   189, 321, 346-361, 371-372
plugins/saga/scripts/spend_receipt.py                                                    78      2    97%   169-170
plugins/saga/scripts/spend_retro.py                                                     152     18    88%   81-85, 91, 237-240, 291, 329-333, 338-339
plugins/saga/scripts/status_card.py                                                     427     82    81%   279-280, 284-285, 312-313, 329-330, 439, 441, 446, 449, 481, 513-514, 594-595, 615-616, 693-694, 762, 797-798, 806, 810, 840, 855, 869-943, 948-960
plugins/saga/scripts/team_emitter.py                                                    149      6    96%   210-215
plugins/saga/scripts/team_teardown.py                                                   508     26    95%   95, 101, 136, 180, 205, 209, 236, 266, 268, 292, 298, 379, 429, 456, 472, 558, 762, 779, 815, 1040, 1172-1173, 1225, 1240, 1292, 1362
plugins/saga/scripts/tier_defaults.py                                                   102      5    95%   56, 59, 61, 85, 170
plugins/saga/scripts/tier_efficacy.py                                                    87     10    89%   101-102, 128, 156-164, 185-187
plugins/saga/scripts/tier_session.py                                                     89     27    70%   42, 114-125, 129-142
plugins/saga/scripts/workflow_emitter.py                                                103     13    87%   49, 55, 70, 75, 82, 89, 91, 97, 172, 201-204
plugins/team-execution/skills/team-execution/scripts/artifact_pointer.py                513    133    74%   181-182, 184, 221, 227-236, 257, 260, 266, 271, 289, 346, 348, 351, 353, 373, 375, 377, 380, 382, 384, 386, 388, 391, 393, 395, 397, 404, 407, 409, 426, 442, 456, 589-590, 602-605, 615-616, 641-644, 690-691, 695, 753-754, 757, 760-761, 803, 808, 842, 872-873, 919-922, 926-929, 933-936, 940-943, 947-953, 957-964, 968-986, 990-1048
plugins/team-execution/skills/team-execution/scripts/consensus_advisory.py              142     13    91%   104, 108, 110, 113, 188, 194, 196, 199, 208, 210, 219, 228, 241
plugins/team-execution/skills/team-execution/scripts/dispatch_settlement_adapter.py     250     52    79%   72, 74, 77, 81, 87-88, 96, 105, 149-152, 158, 178, 191, 198, 202, 207-211, 213, 215, 218, 224-225, 269, 296-307, 393-394, 396-397, 420-425, 437, 443-445
plugins/team-execution/skills/team-execution/scripts/liveness_protocol.py               340    168    51%   84, 88-106, 112-113, 117-130, 148, 152-159, 169-170, 172, 187-188, 205, 209, 216, 250-251, 273, 278, 280, 283, 289-291, 407, 442, 446, 529, 552, 569, 590, 592, 594, 596, 619-622, 627-628, 632-638, 642-661, 665-674, 678-689, 693-707, 711-717, 721-729, 733-743, 747-819
plugins/team-execution/skills/team-execution/scripts/posture_check.py                    34      0   100%
plugins/unifi/skills/unifi-network/scripts/site_profile_loader.py                       389     35    91%   302, 356-357, 359, 375, 402, 449, 502, 544, 560, 569, 580, 612, 628, 650, 658, 665, 669, 672-679, 689-692, 776, 784-786, 799
plugins/unifi/skills/unifi-network/scripts/unifi_network_client.py                      697    256    63%   35-45, 229-239, 257-258, 313-316, 395-398, 454-457, 512-515, 576-578, 635-638, 685-686, 762-764, 852, 1157-1386
plugins/unifi/skills/unifi-protect/scripts/unifi_protect_client.py                      357    127    64%   38-48, 235-239, 260-261, 311, 354-356, 399, 431, 461-463, 481-483, 493-495, 657-808
-------------------------------------------------------------------------------------------------------------------
TOTAL                                                                                 39648   6103    85%
====== 6927 passed, 7 skipped, 1 xfailed, 2 warnings in 736.15s (0:12:16) ======
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:103: PytestWarning: (rm_rf) unknown function <built-in function scandir> when removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0/repo/.orchestrate/land-r1:
<class 'PermissionError'>: [Errno 1] Operation not permitted: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0/repo/.orchestrate/land-r1'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0/repo/.orchestrate/land-r1
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0/repo/.orchestrate/land-r1'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0/repo/.orchestrate
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0/repo/.orchestrate'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0/repo
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0/repo'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve0'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:103: PytestWarning: (rm_rf) unknown function <built-in function scandir> when removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1/repo/.orchestrate/land-r1:
<class 'PermissionError'>: [Errno 1] Operation not permitted: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1/repo/.orchestrate/land-r1'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1/repo/.orchestrate/land-r1
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1/repo/.orchestrate/land-r1'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1/repo/.orchestrate
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1/repo/.orchestrate'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1/repo
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1/repo'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75/test_real_removal_failure_neve1'
  warnings.warn(
/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/upstream/.venv/lib/python3.12/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-b586e034-4611-4269-b76b-c90f68807b75'
  warnings.warn(
$ uv run pytest exit=0
`````

The suite passed: **6927 passed, 7 skipped, 1 xfailed in 736.15s (0:12:16)**,
exit 0. The `PytestWarning` lines near the end are temporary-directory
cleanup notices from the test's own scratch tree under the macOS sandbox
(`Errno 66` on pytest's `garbage-*` fixtures); pytest reports them as warnings
and the run's exit status is 0. They did not affect any test verdict.

---

## 2. Pin manifest readback — version 2.15.2 at the pin

```
$ git -C "$SCRATCH/upstream" show 3b2b7083:plugins/mission-control/.claude-plugin/plugin.json
{
  "name": "mission-control",
  "version": "2.15.2",
  "description": "SDLC management for Operations, Asgard, and CAMPPS: prepared issue drafts, live schema sync, board schemas, labels, project fields, metrics, and card validation.",
  "author": {
    "name": "Infiquetra",
    "email": "hello@infiquetra.com"
  },
  "repository": "https://github.com/infiquetra/infiquetra-claude-plugins",
  "keywords": [
    "sdlc",
    "github-projects",
    "kanban",
    "issues",
    "labels",
    "metrics",
    "sub-issues",
    "campps",
    "asgard",
    "operations"
  ]
}
```

The pinned revision's client manifest
`plugins/mission-control/.claude-plugin/plugin.json` reads version **2.15.2**.

---

## 3. Three-revision package-tree comparison — why the pin is the accepted merge

```
$ for r in 379d2350 1111de33 3b2b7083; do printf "%s %s\n" "$r" "$(git rev-parse $r:plugins/mission-control)"; done
379d2350 0fdcea0de13b7d48746f81c632f3da1666acc3a2
1111de33 a851eabb24bac6f539e9356f95e554d84bc4ea0b
3b2b7083 a851eabb24bac6f539e9356f95e554d84bc4ea0b
```

| Revision | Package tree | What it is |
|---|---|---|
| `379d2350` | `0fdcea0de13b7d48746f81c632f3da1666acc3a2` | where the version landed |
| `1111de33` | `a851eabb24bac6f539e9356f95e554d84bc4ea0b` | its document review |
| `3b2b7083` | `a851eabb24bac6f539e9356f95e554d84bc4ea0b` | the accepted merge — **this is the pin** |

Three commits carry version 2.15.2 and their package trees are not identical.
The document review (`1111de33`) repaired `CHANGELOG.md` and
`skills/board/references/kanban-workflow.md` inside the package without moving
the version. Pinning the version-landing commit (`379d2350`, tree `0fdcea0d`)
would import content its own review had already corrected. The pin is the
accepted merge, which shares the reviewed tree `a851eabb…` (plan KTD1,
operator ruling 1).

---

## 4. Python floor unchanged at the pin

```
$ git -C "$SCRATCH/upstream" show 3b2b7083:pyproject.toml | grep requires-python
requires-python = ">=3.12"
```

`requires-python = ">=3.12"` at the pin — the floor has not moved, and the
catalog's declared floor matches. Interpreter presence, by explicit path,
never `python3` (runbook Phase 0):

```
$ python3 --version; command -v python3; command -v python3.12
Python 3.14.7
/opt/homebrew/bin/python3
/opt/homebrew/bin/python3.12
```

The default `python3` on this machine is 3.14.7; the floor interpreter
`python3.12` resolves to `/opt/homebrew/bin/python3.12` (3.12.13).

---

## 5. Allowed merge methods — read before any run text states a merge form

```
$ gh repo view infiquetra/infiquetra-agent-plugins --json squashMergeAllowed,mergeCommitAllowed,rebaseMergeAllowed
{"mergeCommitAllowed":false,"rebaseMergeAllowed":true,"squashMergeAllowed":true}
$ merge-read exit=0
```

Read from `gh repo view` before any text in this note or the run states a
merge form (runbook entry criterion; lesson R1 from the #9 retrospective).
Result: merge commits **not allowed** (`mergeCommitAllowed: false`); squash
and rebase allowed. No statement in this note asserts a merge form beyond this
readback.

---

## 6. The assessment plan prints and runs nothing

```
$ python3 scripts/assess_clients.py --package mission-control
Assessment plan for mission-control (plugins/mission-control)
Clients: 10   Stages per client: 4

Nothing below has run. Pass --execute to run it.

## Claude Code  [home: isolated]
   quirk: User-scope installation needs a marketplace file the portable root does not carry. Placement is session-scoped through the local-plugin flag, which is re-supplied on every later stage.
   placement   claude --plugin-dir <package> plugin list   (deadline 120s)
   discovery   claude --plugin-dir <package> plugin list   (deadline 120s)
   load        claude --plugin-dir <package> plugin details mission-control   (deadline 120s)
   invocation  <python> <package>/scripts/sdlc_manager.py --help   (5 commands, deadline 120s)
               <python> <package>/scripts/board_census.py --help
               <python> <package>/scripts/check_pagination.py --help
               <python> <package>/scripts/executor_profile_lint.py --help
               <python> <package>/scripts/sync_template_docs.py --help

## OpenAI Codex  [home: isolated]
   quirk: Refuses the package root with an actionable message naming the manifest it wants. The marketplace is its only placement path, so load and invocation stay blocked on the absent adapter rather than on any package defect.
   placement   codex plugin marketplace add <package>   (deadline 120s)
   discovery   codex plugin list   (deadline 120s)
   load        blocked in advance: Nothing was placed, so there is nothing to load. Blocked on the absent adapter rather than on any package defect.
   invocation  blocked in advance: No client-resolved path exists, because placement produced none. A stage that did not run through the client is recorded blocked rather than borrowed from another client's result.

## Cursor Agent  [home: real]
   quirk: Must run against the real authenticated home. An isolated home strips authentication and measures an unauthenticated first-run client, which a superseded matrix published as a package failure. Placement is session-scoped through the local-plugin flag, so no stage writes client state.
   placement   cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text Report the locally loaded plugin and component names available from session context. Do not use filesystem, shell, network, or UniFi tools.   (deadline 120s)
   discovery   cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text Report the locally loaded plugin and component names available from session context. Do not use filesystem, shell, network, or UniFi tools.   (deadline 120s)
   load        cursor-agent --plugin-dir <package> --mode ask --trust -p --output-format text From session context only, for the plugin loaded from the session-scoped local plugin directory (not any marketplace-installed plugin of the same name): report its plugin name, its version if session context carries one, and the exact component names it contributes. Do not use filesystem, shell, network, or UniFi tools.   (deadline 120s)
   invocation  <python> <package>/scripts/sdlc_manager.py --help   (5 commands, deadline 120s)
               <python> <package>/scripts/board_census.py --help
               <python> <package>/scripts/check_pagination.py --help
               <python> <package>/scripts/executor_profile_lint.py --help
               <python> <package>/scripts/sync_template_docs.py --help

## Qwen  [home: isolated]
   quirk: The installer asks for confirmation on standard input; with no answer it lists the skills and exits without installing. It copies rather than links, and adds one bookkeeping file of its own to the extension directory.
   placement   qwen extensions install <package>   (confirmation on stdin, deadline 120s)
   discovery   qwen extensions list   (deadline 120s)
   load        qwen extensions list   (deadline 120s)
   invocation  <python> <client-home>/.qwen/extensions/mission-control/scripts/sdlc_manager.py --help   (5 commands, deadline 120s)
               <python> <client-home>/.qwen/extensions/mission-control/scripts/board_census.py --help
               <python> <client-home>/.qwen/extensions/mission-control/scripts/check_pagination.py --help
               <python> <client-home>/.qwen/extensions/mission-control/scripts/executor_profile_lint.py --help
               <python> <client-home>/.qwen/extensions/mission-control/scripts/sync_template_docs.py --help

## Grok  [home: isolated]
   quirk: The launcher on PATH is an auto-trust wrapper that resolves its real binary through the client home, which an isolated home does not contain; without GROK_AUTO_TRUST_REAL_BIN, the wrapper's own documented override, it exits before reaching the client. 'plugin details' takes the plugin name, not the generated install id.
   placement   grok plugin install <package> --trust   (deadline 120s)
   discovery   grok plugin list   (deadline 120s)
   load        grok plugin details mission-control   (deadline 120s)
   invocation  <python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/sdlc_manager.py --help   (5 commands, deadline 120s)
               <python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/board_census.py --help
               <python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/check_pagination.py --help
               <python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/executor_profile_lint.py --help
               <python> <client-home>/.grok/installed-plugins/<plugin-id>/scripts/sync_template_docs.py --help

## OpenCode  [home: isolated]
   quirk: Its own configuration documents an auto-loaded external skill directory and offers no install command for it, so placement is a copy into that directory. 'debug skill' returns each skill's full parsed body, which is load proven rather than inferred.
   placement   cp -R <package>/skills/board <client-home>/.agents/skills/   (7 commands, deadline 120s)
               cp -R <package>/skills/flow <client-home>/.agents/skills/
               cp -R <package>/skills/issues <client-home>/.agents/skills/
               cp -R <package>/skills/labels <client-home>/.agents/skills/
               cp -R <package>/skills/metrics <client-home>/.agents/skills/
               cp -R <package>/skills/milestones <client-home>/.agents/skills/
               cp -R <package>/skills/rollout <client-home>/.agents/skills/
   discovery   opencode debug skill   (deadline 120s)
   load        opencode debug skill   (deadline 120s)
   invocation  blocked in advance: OpenCode installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance.

## Gemini CLI  [home: isolated]
   quirk: 'skills link' prompts on standard input and hangs rather than declining when stdin is closed, so the confirmation is supplied explicitly and the stage carries a deadline. Session injection is not observable without credentials, so what load confirms is definition load.
   placement   gemini skills link <package>/skills/board   (7 commands, confirmation on stdin, deadline 120s)
               gemini skills link <package>/skills/flow
               gemini skills link <package>/skills/issues
               gemini skills link <package>/skills/labels
               gemini skills link <package>/skills/metrics
               gemini skills link <package>/skills/milestones
               gemini skills link <package>/skills/rollout
   discovery   gemini skills list --all   (deadline 120s)
   load        gemini skills list --all   (deadline 120s)
   invocation  blocked in advance: Gemini CLI installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance.

## Muse  [home: isolated]
   quirk: Refuses the package root as an installable unit, so the skill units install individually. '--force' is required on the JSON install for it to report a content digest once placement has already installed the unit.
   placement   muse skills install <package>/skills/board --scope user   (7 commands, deadline 120s)
               muse skills install <package>/skills/flow --scope user
               muse skills install <package>/skills/issues --scope user
               muse skills install <package>/skills/labels --scope user
               muse skills install <package>/skills/metrics --scope user
               muse skills install <package>/skills/milestones --scope user
               muse skills install <package>/skills/rollout --scope user
   discovery   muse skills list --source user   (deadline 120s)
   load        muse skills install <package>/skills/board --scope user --force --json   (7 commands, deadline 120s)
               muse skills install <package>/skills/flow --scope user --force --json
               muse skills install <package>/skills/issues --scope user --force --json
               muse skills install <package>/skills/labels --scope user --force --json
               muse skills install <package>/skills/metrics --scope user --force --json
               muse skills install <package>/skills/milestones --scope user --force --json
               muse skills install <package>/skills/rollout --scope user --force --json
   invocation  blocked in advance: Muse installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance.

## Agy  [home: isolated]
   quirk: Same auto-trust wrapper arrangement as Grok, and the same override, AGY_AUTO_TRUST_REAL_BIN, for the same reason. It re-validates its own installed copy, which is what makes its load stage independent of its placement stage.
   placement   agy plugin install <package>   (deadline 120s)
   discovery   agy plugin list   (deadline 120s)
   load        agy plugin validate <client-home>/.gemini/config/plugins/mission-control   (deadline 120s)
   invocation  <python> <client-home>/.gemini/config/plugins/mission-control/scripts/sdlc_manager.py --help   (5 commands, deadline 120s)
               <python> <client-home>/.gemini/config/plugins/mission-control/scripts/board_census.py --help
               <python> <client-home>/.gemini/config/plugins/mission-control/scripts/check_pagination.py --help
               <python> <client-home>/.gemini/config/plugins/mission-control/scripts/executor_profile_lint.py --help
               <python> <client-home>/.gemini/config/plugins/mission-control/scripts/sync_template_docs.py --help

## Hermes  [home: isolated]
   quirk: Isolated home only, and the live skills directory is counted before and after to prove it was not written to. Its install subcommand takes a remote identifier or an HTTP URL rather than a local path, so placement is a copy into the profile skills directory. 'prompt-size --json' resolves the skills into a composed prompt offline, which proves load without credentials.
   placement   cp -R <package>/skills/board <client-home>/.hermes/skills/   (7 commands, deadline 120s)
               cp -R <package>/skills/flow <client-home>/.hermes/skills/
               cp -R <package>/skills/issues <client-home>/.hermes/skills/
               cp -R <package>/skills/labels <client-home>/.hermes/skills/
               cp -R <package>/skills/metrics <client-home>/.hermes/skills/
               cp -R <package>/skills/milestones <client-home>/.hermes/skills/
               cp -R <package>/skills/rollout <client-home>/.hermes/skills/
   discovery   hermes skills list   (deadline 120s)
   load        hermes prompt-size --json   (deadline 120s)
   invocation  blocked in advance: Hermes installs skill units rather than the package, so declared entrypoint(s) sitting outside every declared skill unit have no client-resolved path: 'scripts/sdlc_manager.py', 'scripts/board_census.py', 'scripts/check_pagination.py', 'scripts/executor_profile_lint.py', 'scripts/sync_template_docs.py'. A stage that half ran did not run, so invocation is blocked in advance.

$ assess exit=0
```

Exit 0. The plan header states "Nothing below has run. Pass --execute to run
it." — the entry-criterion line "print the plan with
`python3 scripts/assess_clients.py --package <package>` before running it" is
satisfied; the ten-client assessment itself is U5's deliverable and was not
run here.

---

## 7. Runbook version followed, and the steps a resync skips

Runbook followed: **`docs/runbooks/portable-plugin-port.md` v1.1.0**. It is
written for an initial port; a resynchronization has no counterpart for
several of its steps. Every entry-criteria line and phase step is accounted
for below — kept, skipped, replaced, or narrowed — each with its reason, so
the deviation from the runbook is documented rather than silent.

| Runbook step (v1.1.0) | Disposition for this run | Reason |
|---|---|---|
| Entry: "Upstream plugin sits at a pinned commit; its own suite is green there." | **kept** | performed by this unit — scratch-clone proof in §1 |
| Entry: "the port descriptor exists at `ports/<package>.json` and `check_repo.py` passes on the empty port" | **skipped** | the descriptor has existed since the #9 port; the gate passes on the *populated* port today (§8 transcript) |
| Entry: "every validation rule the plugin carries is inventoried, each with a named predicate and a named authority" | **skipped** | done once in #9 and recorded in `docs/plans/2026-08-24-mission-control-port-u7-phase2-rule-audit.md`; a resync re-runs rules, it does not re-inventory them |
| Entry: "the client roster and assessment method are scripted in `scripts/assess_clients.py` … print the plan" | **kept** | performed by this unit — §6 transcript |
| Entry: "the Python floor is decided and a matching interpreter exists" | **kept** | re-verified at the pin (§4) and by explicit path on this machine |
| Entry: "non-goals are written down" | **kept** | issue #50's *Out-of-scope / non-goals* section stands for this run |
| Entry: "the repository's allowed merge methods are read before any plan, review contract, or PR text states a merge form" | **kept** | performed by this unit — §5 transcript |
| Phase 0: "write `ports/<package>.json`" | **replaced** | U1 amends an existing descriptor rather than writing a new one |
| Phase 0: "classify every path" | **narrowed** | only the eight new upstream paths need classification (U1) |
| Phase 0: "confirm the floor interpreter by explicit path, never as `python3`" | **kept** | `command -v python3.12` → `/opt/homebrew/bin/python3.12` (§4) |
| Phase 1: three parallel lanes A/B/C | **replaced** | Lane C (bundling) is empty — fleet-core is unchanged upstream; Lanes A and B become serialized units U2 and U3 because U3 edits inside the package root and must precede the freeze |
| Phase 2: full rule audit | **narrowed** | the four transform premises are re-proven at the new pin (U2, R19) and the verb table is re-audited (U3); the rule inventory itself is unchanged |
| Phase 3: freeze and evidence | **kept, except mutation-proof re-run** | the matrix, readback, freeze, and content bindings are U5; a new mutation proof is out of scope because the five graded files are untouched (plan §2.8, KTD11) |
| Phase 3: "mutation proof per rule copy, bound by test" | **skipped** | the cycle-16 proof still stands; re-running it would edit a graded file or the proof document, both forbidden |
| Phase 4: review (two reviewers, max three rounds) | **kept in full** | plan §2.4 |

---

## 8. The gates — four mandated, plus the floor-interpreter package run

Run on this repository's `orch-agent-plugins-50` tree (base
`ab939ffcb20272fb12d8c6616ec81b067847e1d4`), transcripts verbatim (R36):

```
$ python3 scripts/check_repo.py
Repository validation passed.
$ check_repo exit=0
$ python3 -m unittest discover -s tests
.......................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................................--- /Users/jefcox/workspace/infiquetra/orch-agent-plugins-50/plugins/mission-control/skills/issues/references/templates-reference.md
+++ generated templates-reference.md
@@ -217,5 +217,3 @@
 - Non-actionable cards carry only their type and context labels.
 - Do not document or treat this template as an actionable task card.
 - Use these cards for coordination, research, or documentation context rather than agent dispatch.
-
-## Drift Injected Section
..............................................................................................................................................................................................................................................
----------------------------------------------------------------------
Ran 773 tests in 49.301s

OK
$ unittest exit=0
$ python3 -m pytest plugins/mission-control/tests -q
........................................................................ [ 27%]
........................................................................ [ 54%]
........................................................................ [ 81%]
..................................................                       [100%]
266 passed in 1.45s
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:103: PytestWarning: (rm_rf) unknown function <built-in function scandir> when removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0/repo/.orchestrate/land-r1:
<class 'PermissionError'>: [Errno 1] Operation not permitted: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0/repo/.orchestrate/land-r1'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0/repo/.orchestrate/land-r1
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0/repo/.orchestrate/land-r1'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0/repo/.orchestrate
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0/repo/.orchestrate'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0/repo
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0/repo'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve0'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:103: PytestWarning: (rm_rf) unknown function <built-in function scandir> when removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1/repo/.orchestrate/land-r1:
<class 'PermissionError'>: [Errno 1] Operation not permitted: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1/repo/.orchestrate/land-r1'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1/repo/.orchestrate/land-r1
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1/repo/.orchestrate/land-r1'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1/repo/.orchestrate
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1/repo/.orchestrate'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1/repo
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1/repo'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944/test_real_removal_failure_neve1'
  warnings.warn(
/opt/homebrew/lib/python3.14/site-packages/_pytest/pathlib.py:96: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944
<class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-92e8257d-ed6e-4bfa-bdcb-fff9ee78c944'
  warnings.warn(
$ pytest exit=0
$ <scratch>/floor-venv/bin/python -m pytest plugins/mission-control/tests -q
........................................................................ [ 27%]
........................................................................ [ 54%]
........................................................................ [ 81%]
..................................................                       [100%]
=============================== warnings summary ===============================
../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:102
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:102: PytestWarning: (rm_rf) unknown function <built-in function scandir> when removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0/repo/.orchestrate/land-r1:
  <class 'PermissionError'>: [Errno 1] Operation not permitted: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0/repo/.orchestrate/land-r1'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0/repo/.orchestrate/land-r1
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0/repo/.orchestrate/land-r1'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0/repo/.orchestrate
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0/repo/.orchestrate'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0/repo
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0/repo'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve0'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:102
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:102: PytestWarning: (rm_rf) unknown function <built-in function scandir> when removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1/repo/.orchestrate/land-r1:
  <class 'PermissionError'>: [Errno 1] Operation not permitted: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1/repo/.orchestrate/land-r1'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1/repo/.orchestrate/land-r1
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1/repo/.orchestrate/land-r1'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1/repo/.orchestrate
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1/repo/.orchestrate'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1/repo
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1/repo'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2/test_real_removal_failure_neve1'
    warnings.warn(

../../../../../private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95
  /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/opencode/u0-r2-scratch-6p2gdz/floor-venv/lib/python3.12/site-packages/_pytest/pathlib.py:95: PytestWarning: (rm_rf) error removing /private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2
  <class 'OSError'>: [Errno 66] Directory not empty: '/private/var/folders/ky/n5fq5mgd5rl4321kxfy3jtvw0000gn/T/pytest-of-jefcox/garbage-4c917ea8-5597-44b3-8657-0a2c0316dde2'
    warnings.warn(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
266 passed, 11 warnings in 1.59s
$ floor pytest exit=0
$ git diff --check
$ diff-check exit=0
```

Results: `check_repo.py` printed `Repository validation passed.` (exit 0);
`unittest discover` reported `Ran 773 tests in 49.301s … OK` (exit 0); the
package suite on the default interpreter reported `266 passed in 1.45s` (exit
0); the same suite on the floor interpreter reported `266 passed, 11 warnings
in 1.59s` (exit 0); `git diff --check` produced no output (exit 0).

Floor-run mechanics: `/opt/homebrew/bin/python3.12` does not carry `pytest`,
so per plan §2.6 a **throwaway virtual environment** was created outside the
repository (`<scratch>/floor-venv`, from `python3.12 -m venv`, with `pytest
pyyaml requests urllib3` installed — the set `.github/workflows/ci.yml`
installs). No dependency file was added to the repository.

---

## 9. Disposal and integrity

- The scratch clone and its transcripts lived under the system temporary
  directory and were removed after this note was assembled. Nothing from the
  scratch tree was copied into the repository except the transcripts pasted
  above.
- The local read-only upstream checkout `../infiquetra-claude-plugins` was
  not opened, referenced, or modified by this unit. The proof above comes
  from the scratch clone alone.
- `git status --porcelain` before and after the unit's verification work was
  identical (both empty) — no unrelated dirty file was disturbed (R38).
- The only file this unit changes is this note. `ports/mission-control.json`,
  `plugins/mission-control/`, the runbook, and all five graded files
  (`scripts/port_config.py`, `scripts/check_repo.py`,
  `scripts/check_compatibility_matrix.py`, `scripts/assess_clients.py`,
  `plugins/unifi/scripts/site_profile.py`) are untouched.
