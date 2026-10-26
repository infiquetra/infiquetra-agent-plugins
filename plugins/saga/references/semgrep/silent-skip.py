"""Fresh rule-test target for saga.silent-skip. Never executed; only scanned."""


def import_rows(rows):
    for row in rows:
        cleaned = clean(row)
        if not valid(cleaned):
            log_result(cleaned)
            skipped = count_skipped()
            # ruleid: saga.silent-skip
            continue
        store(cleaned)


def import_rows_bare(rows):
    for row in rows:
        cleaned = clean(row)
        # ruleid: saga.silent-skip
        continue


def import_rows_filter(rows):
    for row in rows:
        if not row:
            # ok: saga.silent-skip
            continue
        store(row)


def import_rows_traced(rows):
    for row in rows:
        cleaned = clean(row)
        if not valid(cleaned):
            log("skipping row", cleaned)
            # ok: saga.silent-skip
            continue
        store(cleaned)


def import_rows_default_branch(rows):
    for row in rows:
        if row.ready:
            store(row)
        else:
            # ok: saga.silent-skip
            continue


def check_names(names, known):
    errors = []
    for name in names:
        if name not in known:
            errors.append(
                f"{name} names nothing that is known, "
                "so it is reported"
            )
            # ok: saga.silent-skip
            continue
        if not name:
            errors.append(f"{name} is empty")
            # ok: saga.silent-skip
            continue
        store(name)
    return errors


def collect_rows(rows):
    seen = []
    for row in rows:
        cleaned = clean(row)
        if not valid(cleaned):
            seen.append(cleaned)
            # ruleid: saga.silent-skip
            continue
        store(cleaned)


def long_record_then_work(rows, errors):
    """A long recorded call that is not followed by a continue must not end the exclusion for the
    rest of the file (the pattern once backtracked until it dropped out)."""
    for row in rows:
        errors.append(
            dict(
                row=row,
                one=1,
                two=2,
                three=3,
                four=4,
                five=5,
                six=6,
                seven=7,
                eight=8,
                nine=9,
                ten=10,
            )
        )
        process(row)


def recorded_after_the_long_call(rows, errors):
    for row in rows:
        if bad(row):
            errors.append(
                f"{row} is bad, "
                "so it is reported"
            )
            # ok: saga.silent-skip
            continue
        store(row)


def names_that_are_not_reports(rows, seen_issues, tissues):
    for row in rows:
        if bad(row):
            seen_issues.add(row)
            # ruleid: saga.silent-skip
            continue
        if worse(row):
            tissues.append(row)
            # ruleid: saga.silent-skip
            continue
        store(row)
