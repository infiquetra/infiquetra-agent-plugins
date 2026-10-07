// Fresh rule-test target for saga.silent-skip. Never executed; only scanned.

function importRows(rows: Row[]): void {
  for (const row of rows) {
    const cleaned = clean(row);
    if (!valid(cleaned)) {
      skipped += 1;
      // ruleid: saga.silent-skip
      continue;
    }
    store(cleaned);
  }
}

function importRowsFilter(rows: Row[]): void {
  for (const row of rows) {
    if (!row) {
      // ok: saga.silent-skip
      continue;
    }
    store(row);
  }
}

function importRowsTraced(rows: Row[]): void {
  for (const row of rows) {
    const cleaned = clean(row);
    if (!valid(cleaned)) {
      skipped += 1;
      log("skipping row", cleaned);
      // ok: saga.silent-skip
      continue;
    }
    store(cleaned);
  }
}

function importRowsGuardLine(rows: Row[]): void {
  for (const row of rows) {
    // ok: saga.silent-skip
    if (!row) continue;
    store(row);
  }
}
