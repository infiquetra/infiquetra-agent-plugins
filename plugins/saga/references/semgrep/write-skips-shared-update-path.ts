// Fresh rule-test target for saga.write-skips-shared-update-path.

function moveCardDirect(): void {
  // ruleid: saga.write-skips-shared-update-path
  const mutation = "mutation { updateProjectV2ItemFieldValue(input: $i) }";
}

function moveCardCli(): void {
  // ruleid: saga.write-skips-shared-update-path
  run("gh project item-edit --id " + cardId);
}

function moveCardPayload(): void {
  // ruleid: saga.write-skips-shared-update-path
  const payload = { optionId: "abc123" };
}

function moveCardQuery(): void {
  // ruleid: saga.write-skips-shared-update-path
  run("gh api graphql --field query={ projectV2ItemFieldTextValue }");
}

function moveCardShared(): void {
  // ok: saga.write-skips-shared-update-path
  illustrative_update_path("updateProjectV2ItemFieldValue", cardId);
}

function moveCardSharedOther(): void {
  // ok: saga.write-skips-shared-update-path
  example_shared_write("gh project item-edit", cardId);
}
