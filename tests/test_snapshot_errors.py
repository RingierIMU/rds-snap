"""Exit-code contract for `snapshot delete` and `snapshot share` (#28).

AWS errors are injected through a botocore Stubber on a real rds client, so the
command matches modelled faults via ``client.exceptions.<Fault>`` exactly as in
production. Click >= 8.2's CliRunner mixes stderr into ``result.output``.
"""

import logging

import pytest
from click.testing import CliRunner

from rds_snap.commands import snapshot as snapshot_cli
from tests.conftest import SNAPSHOT_ID

ACCOUNT = "444455556666"


@pytest.fixture
def rds(stubbed_rds, monkeypatch):
    client, stubber = stubbed_rds
    monkeypatch.setattr(snapshot_cli, "get_rds_client", lambda profile: client)
    return stubber


def _delete():
    return CliRunner().invoke(
        snapshot_cli.delete, ["--snapshot-identifier", SNAPSHOT_ID]
    )


def _share():
    return CliRunner().invoke(
        snapshot_cli.share,
        ["--snapshot-identifier", SNAPSHOT_ID, "--account-number", ACCOUNT],
    )


def _assert_clean_failure(result, caplog):
    """exit 1 via ClickException: `Error: ...` line, no traceback, but
    logger.exception recorded the cause with exc_info."""
    assert result.exit_code == 1, result.output
    # ClickException is turned into SystemExit(1) by standalone mode; an
    # unhandled exception would surface here as itself instead.
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "Error:" in result.output
    assert "Traceback" not in result.output
    assert any(
        r.levelno == logging.ERROR and r.exc_info for r in caplog.records
    ), "expected logger.exception(...) to be called"


def test_delete_success(rds):
    rds.add_response(
        "delete_db_cluster_snapshot",
        {"DBClusterSnapshot": {"DBClusterSnapshotIdentifier": SNAPSHOT_ID}},
        {"DBClusterSnapshotIdentifier": SNAPSHOT_ID},
    )
    result = _delete()
    assert result.exit_code == 0, result.output
    assert f"Successfully deleted snapshot {SNAPSHOT_ID}" in result.output


def test_delete_not_found_exits_zero_with_warning(rds):
    rds.add_client_error(
        "delete_db_cluster_snapshot",
        service_error_code="DBClusterSnapshotNotFoundFault",
        service_message=f"DBClusterSnapshot {SNAPSHOT_ID} not found.",
        http_status_code=404,
    )
    result = _delete()
    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert f"snapshot {SNAPSHOT_ID} not found, nothing to delete" in result.output


def test_delete_invalid_state_exits_one(rds, caplog):
    caplog.set_level(logging.ERROR)
    rds.add_client_error(
        "delete_db_cluster_snapshot",
        service_error_code="InvalidDBClusterSnapshotStateFault",
        service_message="Snapshot is in state copying",
        http_status_code=400,
    )
    result = _delete()
    _assert_clean_failure(result, caplog)
    assert SNAPSHOT_ID in result.output
    assert "Snapshot is in state copying" in result.output


def test_delete_generic_client_error_exits_one(rds, caplog):
    caplog.set_level(logging.ERROR)
    rds.add_client_error(
        "delete_db_cluster_snapshot",
        service_error_code="AccessDenied",
        service_message="User is not authorized to delete",
        http_status_code=403,
    )
    result = _delete()
    _assert_clean_failure(result, caplog)
    assert SNAPSHOT_ID in result.output
    assert "User is not authorized to delete" in result.output


def test_share_client_error_exits_one(rds, caplog):
    caplog.set_level(logging.ERROR)
    rds.add_client_error(
        "modify_db_cluster_snapshot_attribute",
        service_error_code="AccessDenied",
        service_message="User is not authorized to share",
        http_status_code=403,
    )
    result = _share()
    _assert_clean_failure(result, caplog)
    assert SNAPSHOT_ID in result.output
    assert ACCOUNT in result.output
    assert "User is not authorized to share" in result.output


def test_share_success_exits_zero(rds):
    rds.add_response(
        "modify_db_cluster_snapshot_attribute",
        {
            "DBClusterSnapshotAttributesResult": {
                "DBClusterSnapshotIdentifier": SNAPSHOT_ID,
                "DBClusterSnapshotAttributes": [
                    {"AttributeName": "restore", "AttributeValues": [ACCOUNT]}
                ],
            }
        },
        {
            "DBClusterSnapshotIdentifier": SNAPSHOT_ID,
            "AttributeName": "restore",
            "ValuesToAdd": [ACCOUNT],
        },
    )
    result = _share()
    assert result.exit_code == 0, result.output
    assert (
        f"Successfully shared snapshot {SNAPSHOT_ID} with aws account {ACCOUNT}"
        in result.output
    )
