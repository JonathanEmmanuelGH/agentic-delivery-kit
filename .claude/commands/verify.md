---
description: Run the single verification gate and report its verdict honestly.
---

Run the gate and report only what it printed.

1. Short changes: `VERIFY_SCOPE=auto bash kit/gate/verify.sh` in the foreground.
2. Anything that may take longer than a tool call's timeout: launch it detached with a unique log name and wait for it:
   ```
   start=$(date +%s); log="gate-$(git rev-parse --short HEAD)-$start.log"
   setsid nohup bash kit/gate/verify.sh > "$log" 2>&1 &
   bash kit/gate/gate-wait.sh "$log" --pid <the gate's pid> --after "$start"
   ```
3. Report the `VERIFY:` line, the `exit=` line, each failed phase with the first lines of its output, and the log's sha256 from the gate-wait block.

Rules: a PASS line without `exit=0` is not a pass. Do not summarize a red phase as "mostly green". Do not re-run a failing gate hoping for green; diagnose the first failure.
