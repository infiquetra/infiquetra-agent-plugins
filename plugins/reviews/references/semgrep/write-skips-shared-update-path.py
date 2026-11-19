"""Fresh rule-test target for saga.write-skips-shared-update-path."""


def move_card_direct():
    # ruleid: saga.write-skips-shared-update-path
    mutation = "mutation { updateProjectV2ItemFieldValue(input: $i) }"


def move_card_cli():
    # ruleid: saga.write-skips-shared-update-path
    run(["gh", "project", "item-edit", "--id", card_id])


def move_card_payload():
    # ruleid: saga.write-skips-shared-update-path
    payload = {"singleSelectOptionId": option_id}


def move_card_query():
    # ruleid: saga.write-skips-shared-update-path
    run(["gh", "api", "graphql", "--field", "query={ projectV2ItemFieldTextValue }"])


def move_card_shared():
    # ok: saga.write-skips-shared-update-path
    example_shared_write("updateProjectV2ItemFieldValue", card_id)


def move_card_shared_other():
    # ok: saga.write-skips-shared-update-path
    illustrative_update_path("updateProjectV2ItemFieldValue", card_id)


def read_card():
    # ok: saga.write-skips-shared-update-path
    return example_shared_write.describe(card_id)
