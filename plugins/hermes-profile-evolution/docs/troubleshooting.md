# Troubleshoot the Claude Code adapter

The adapter checks Hermes automatically before dialogue. For a direct local
diagnostic, run:

```bash
hermes profile-request doctor --target brokkr
```

| Symptom | Meaning | Action |
|---|---|---|
| Exit `2` and the target is invalid | The target is reserved or does not match a named profile. | Use the classified target name. |
| Exit `2` and health is unavailable or incompatible | The route, credentials, service, or doctor response is not ready. | Repair the external Hermes setup and rerun the producer doctor. |
| Exit `2` and JSON is invalid | A reply or resume did not receive one canonical proposal envelope. | Copy the returned envelope unchanged to standard input. |
| Direct edit blocked | The supported file tool reached governed or unclassifiable Team Mimir custody. | Use `/hermes-profile-evolution`; do not bypass the classifier. |
| Bash edit was not intercepted | Bash is outside the supported hook matcher. | Treat the boundary honestly and invoke the command before governed work. |
| Status fails while dialogue works | `status` is a direct read and does not run the adapter's dialogue health preflight. | Verify identifiers, then run the producer doctor explicitly. |
| Remote route differs from local doctor | `HERMES_PROFILE_REQUEST_SSH_ALIAS` makes the adapter use its governed Secure Shell route. | Run diagnosis on the same configured route; do not place credentials in the request. |

The plugin does not store failed work in a retry queue. Retry only after
correcting the input or restoring the producer boundary.

For custody and activation failures, use the
[Team Mimir operator hub](https://github.com/infiquetra/team-mimir/tree/main/docs/team/profile-evolution).
For dialogue failures, use the
[Hermes producer troubleshooting guide](https://github.com/infiquetra/infiquetra-hermes-plugins/blob/main/docs/profile-evolution/troubleshooting.md).
