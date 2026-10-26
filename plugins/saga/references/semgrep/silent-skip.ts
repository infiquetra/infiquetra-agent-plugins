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

function checkNames(names: string[], known: Set<string>): string[] {
  const errors: string[] = [];
  for (const name of names) {
    if (!known.has(name)) {
      errors.push(
        `${name} names nothing that is known, ` +
        "so it is reported"
      );
      // ok: saga.silent-skip
      continue;
    }
    store(name);
  }
  return errors;
}

function collectRows(rows: Row[]): void {
  const seen: Row[] = [];
  for (const row of rows) {
    const cleaned = clean(row);
    if (!valid(cleaned)) {
      seen.push(cleaned);
      // ruleid: saga.silent-skip
      continue;
    }
    store(cleaned);
  }
}
