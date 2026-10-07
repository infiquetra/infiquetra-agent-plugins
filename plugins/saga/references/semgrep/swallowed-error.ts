// Fresh rule-test target for saga.swallowed-error. Never executed; only scanned.

function fetchEmpty(): string {
  try {
    return readConfig();
  // ruleid: saga.swallowed-error
  } catch (e) {}
  return "";
}

function fetchCommented(): string {
  try {
    return readConfig();
  // ruleid: saga.swallowed-error
  } catch (e) {
    // nothing to do
  }
  return "";
}

function fetchUnbound(): string {
  try {
    return readConfig();
  // ruleid: saga.swallowed-error
  } catch {
  }
  return "";
}

function fetchLogged(): string {
  try {
    return readConfig();
  // ok: saga.swallowed-error
  } catch (e) {
    log("config unreadable", e);
    throw e;
  }
}

function fetchDefault(): string {
  try {
    return readConfig();
  // ok: saga.swallowed-error
  } catch (e) {
    return "default";
  }
}
