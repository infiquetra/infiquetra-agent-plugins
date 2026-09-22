<!-- matrix-status: current -->

# UniFi compatibility evidence is not current for 2.0.7

The ten-client records dated 2026-08-22 describe the derived UniFi package at
2.0.6 and earlier. Package 2.0.7 is the authored cut, imported from
infiquetra-claude-plugins at commit acc99fe7. No ten-client run and no
post-activation readback have been made against 2.0.7.

A compatibility matrix binds to the package version. A version bump without a
fresh run fails that check, and copying the 2.0.6 client rows forward under
the new version would claim a run that did not happen. This note is the
current successor those superseded records name. It is not a matrix: it has no
client rows, and it is not evidence that any client can load 2.0.7.

The next run is the ten-client assessment planned after the catalog imports
land. It needs the clients installed on this machine. It is not part of the
import.
