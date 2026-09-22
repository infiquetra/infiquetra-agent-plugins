<!-- matrix-status: notice -->

# UniFi compatibility evidence for 2.0.7: the matrix landed, the readback did not

The ten-client records dated 2026-08-22 describe the derived UniFi package at
2.0.6 and earlier. Package 2.0.7 is the authored cut, imported from
infiquetra-claude-plugins at commit acc99fe7. When this note was written,
no ten-client run and no post-activation readback had been made against 2.0.7.
The ten-client run was made on 2026-09-22 and is recorded in
[2026-09-22-unifi-compatibility-matrix.md](2026-09-22-unifi-compatibility-matrix.md),
which is the current matrix for the package that ships. No post-activation
readback has been made.

A compatibility matrix binds to the package version. A version bump without a
fresh run fails that check, and copying the 2.0.6 client rows forward under
the new version would claim a run that did not happen. This note is the
current successor those superseded records name. It is not a matrix: it has no
client rows, and it is not evidence that any client can load 2.0.7.

The ten-client assessment this note said was outstanding has been made. The
post-activation readback has not, and the two are separate records, so this
note stays in place for the one that is still missing.
