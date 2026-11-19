// Fresh rule-test target for saga.release-shares-cleanup-block. Never executed.

function renewShared(): void {
  const lease = acquireLease();
  try {
    rotate(lease);
  // ruleid: saga.release-shares-cleanup-block
  } finally {
    auditRotation();
    lease.release();
  }
}

function renewReleaseFirst(): void {
  const lease = acquireLease();
  try {
    rotate(lease);
  // ruleid: saga.release-shares-cleanup-block
  } finally {
    lease.release();
    auditRotation();
  }
}

function renewInline(): void {
  const lease = acquireLease();
  try {
    rotate(lease);
  // ruleid: saga.release-shares-cleanup-block
  } finally { auditRotation(); lease.release(); }
}

function renewSoleRelease(): void {
  const lease = acquireLease();
  try {
    rotate(lease);
  // ok: saga.release-shares-cleanup-block
  } finally {
    lease.release();
  }
}

function renewUsing(): void {
  // ok: saga.release-shares-cleanup-block
  using lease = acquireLease();
  rotate(lease);
}

function renewNoRelease(): void {
  const lease = acquireLease();
  try {
    rotate(lease);
  // ok: saga.release-shares-cleanup-block
  } finally {
    auditRotation();
  }
}
