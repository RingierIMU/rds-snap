"""Exit codes for `snapshot tag`, `cluster tag` and `snapshot create` (issue #31).

Tag failures must surface as a non-zero exit naming the ARN, zero-match tagging
is a warning (exit 0), and `snapshot create` must refuse to call
create_db_cluster_snapshot when the cluster is missing or not in a backup-able
state, exiting 1 with a click error instead of a raw traceback.
"""

import pytest
from botocore.exceptions import ClientError
from click.testing import CliRunner

from rds_snap.commands import cluster as cluster_cmd
from rds_snap.commands import snapshot as snapshot_cli
from rds_snap.commands import utils
from tests.conftest import (
    CLUSTER_ID,
    SNAPSHOT_ID,
    cluster,
    cluster_arn,
    instance_arn,
    snapshot,
    snapshot_arn,
)

TAGS_JSON = '{"k": "v"}'
AWS_TAGS = [{"Key": "k", "Value": "v"}]
INSTANCE_ARNS = [instance_arn(f"{CLUSTER_ID}-1"), instance_arn(f"{CLUSTER_ID}-2")]


def _access_denied(stubber, arn):
    stubber.add_client_error(
        "add_tags_to_resource",
        service_error_code="AccessDenied",
        service_message="denied",
        http_status_code=403,
        expected_params={"ResourceName": arn, "Tags": AWS_TAGS},
    )


def _tag_ok(stubber, arn):
    stubber.add_response(
        "add_tags_to_resource", {}, {"ResourceName": arn, "Tags": AWS_TAGS}
    )


@pytest.fixture
def snapshot_rds(stubbed_rds, monkeypatch):
    rds, stubber = stubbed_rds
    monkeypatch.setattr(snapshot_cli, "get_rds_client", lambda profile: rds)
    return rds, stubber


@pytest.fixture
def cluster_rds(stubbed_rds, monkeypatch):
    rds, stubber = stubbed_rds
    monkeypatch.setattr(cluster_cmd, "get_rds_client", lambda profile: rds)
    return rds, stubber


@pytest.fixture
def recorded_sleeps(monkeypatch):
    """Record the backing-up poll delay (utils.sleep) instead of sleeping."""
    recorded = []
    monkeypatch.setattr(utils, "sleep", lambda seconds: recorded.append(seconds))
    return recorded


# --- utils.tag_resource -----------------------------------------------------


def test_tag_resource_propagates_client_error(stubbed_rds):
    """AC: tag_resource no longer swallows AWS errors; the ClientError propagates."""
    rds, stubber = stubbed_rds
    arn = snapshot_arn()
    _access_denied(stubber, arn)

    with pytest.raises(ClientError):
        utils.tag_resource(arn, {"k": "v"}, rds)

    stubber.assert_no_pending_responses()


def test_tag_resource_still_validates_identifier(stubbed_rds):
    """AC: input validation is kept; an empty ARN raises before any API call."""
    rds, stubber = stubbed_rds

    with pytest.raises(Exception):
        utils.tag_resource("", {"k": "v"}, rds)

    stubber.assert_no_pending_responses()


# --- snapshot tag -----------------------------------------------------------


def _describe_snapshot(stubber, payload):
    stubber.add_response(
        "describe_db_cluster_snapshots",
        payload,
        {"DBClusterSnapshotIdentifier": SNAPSHOT_ID},
    )


def test_snapshot_tag_success_tags_each_arn(snapshot_rds):
    """AC: snapshot tag calls add_tags_to_resource per matching ARN and exits 0."""
    _, stubber = snapshot_rds
    _describe_snapshot(stubber, snapshot("available"))
    _tag_ok(stubber, snapshot_arn())

    result = CliRunner().invoke(
        snapshot_cli.tag, ["--snapshot", SNAPSHOT_ID, "--tags", TAGS_JSON]
    )

    assert result.exit_code == 0, result.output
    stubber.assert_no_pending_responses()


def test_snapshot_tag_client_error_exits_1_naming_arn(snapshot_rds):
    """AC: an add_tags_to_resource ClientError exits 1 with `Error:` and the ARN."""
    _, stubber = snapshot_rds
    _describe_snapshot(stubber, snapshot("available"))
    _access_denied(stubber, snapshot_arn())

    result = CliRunner().invoke(
        snapshot_cli.tag, ["--snapshot", SNAPSHOT_ID, "--tags", TAGS_JSON]
    )

    assert result.exit_code == 1, result.output
    assert "Error:" in result.output
    assert snapshot_arn() in result.output
    stubber.assert_no_pending_responses()


def test_snapshot_tag_no_matches_warns_and_exits_0(snapshot_rds):
    """AC: zero matching snapshots is a warning (exit 0), not a silent no-op."""
    _, stubber = snapshot_rds
    _describe_snapshot(stubber, {"DBClusterSnapshots": []})

    result = CliRunner().invoke(
        snapshot_cli.tag, ["--snapshot", SNAPSHOT_ID, "--tags", TAGS_JSON]
    )

    assert result.exit_code == 0, result.output
    assert "warning" in result.output.lower()
    assert SNAPSHOT_ID in result.output
    stubber.assert_no_pending_responses()


def test_snapshot_tag_not_found_fault_warns_and_exits_0(snapshot_rds):
    """AC: DBClusterSnapshotNotFoundFault is treated as zero matches (warn, exit 0)."""
    _, stubber = snapshot_rds
    stubber.add_client_error(
        "describe_db_cluster_snapshots",
        service_error_code="DBClusterSnapshotNotFoundFault",
        service_message=f"{SNAPSHOT_ID} not found",
        http_status_code=404,
        expected_params={"DBClusterSnapshotIdentifier": SNAPSHOT_ID},
    )

    result = CliRunner().invoke(
        snapshot_cli.tag, ["--snapshot", SNAPSHOT_ID, "--tags", TAGS_JSON]
    )

    assert result.exit_code == 0, result.output
    assert "warning" in result.output.lower()
    assert SNAPSHOT_ID in result.output
    stubber.assert_no_pending_responses()


# --- cluster tag ------------------------------------------------------------


def _describe_cluster_and_instances(stubber):
    stubber.add_response(
        "describe_db_clusters",
        cluster("available"),
        {"DBClusterIdentifier": CLUSTER_ID},
    )
    stubber.add_response(
        "describe_db_instances",
        {"DBInstances": [{"DBInstanceArn": a} for a in INSTANCE_ARNS]},
        {"Filters": [{"Name": "db-cluster-id", "Values": [CLUSTER_ID]}]},
    )


def _invoke_cluster_tag():
    return CliRunner().invoke(
        cluster_cmd.tag, ["--cluster", CLUSTER_ID, "--tags", TAGS_JSON]
    )


def test_cluster_tag_success_tags_cluster_then_instances(cluster_rds):
    """AC: cluster tag tags the cluster ARN then each instance ARN and exits 0."""
    _, stubber = cluster_rds
    _describe_cluster_and_instances(stubber)
    _tag_ok(stubber, cluster_arn())
    for arn in INSTANCE_ARNS:
        _tag_ok(stubber, arn)

    result = _invoke_cluster_tag()

    assert result.exit_code == 0, result.output
    stubber.assert_no_pending_responses()


def test_cluster_tag_error_on_cluster_arn_exits_1(cluster_rds):
    """AC: a ClientError tagging the cluster ARN exits 1 naming that ARN."""
    _, stubber = cluster_rds
    _describe_cluster_and_instances(stubber)
    _access_denied(stubber, cluster_arn())

    result = _invoke_cluster_tag()

    assert result.exit_code == 1, result.output
    assert "Error:" in result.output
    assert cluster_arn() in result.output
    stubber.assert_no_pending_responses()


def test_cluster_tag_error_on_instance_arn_exits_1(cluster_rds):
    """AC: a ClientError tagging an instance ARN (after the cluster) exits 1 naming it."""
    _, stubber = cluster_rds
    _describe_cluster_and_instances(stubber)
    _tag_ok(stubber, cluster_arn())
    _access_denied(stubber, INSTANCE_ARNS[0])

    result = _invoke_cluster_tag()

    assert result.exit_code == 1, result.output
    assert "Error:" in result.output
    assert INSTANCE_ARNS[0] in result.output
    stubber.assert_no_pending_responses()


# --- snapshot create --------------------------------------------------------


def _describe_cluster(stubber, payload):
    stubber.add_response(
        "describe_db_clusters", payload, {"DBClusterIdentifier": CLUSTER_ID}
    )


def _invoke_create():
    return CliRunner().invoke(
        snapshot_cli.create,
        ["--cluster", CLUSTER_ID, "--snapshot-identifier", SNAPSHOT_ID],
    )


def test_create_on_stopped_cluster_exits_1_without_creating(snapshot_rds):
    """AC: a cluster in a non-backup-able state exits 1 and never calls create."""
    _, stubber = snapshot_rds
    _describe_cluster(stubber, cluster("stopped"))

    result = _invoke_create()

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "stopped" in result.output
    stubber.assert_no_pending_responses()


def test_create_on_empty_cluster_list_exits_1_not_found(snapshot_rds):
    """AC: an empty DBClusters list is `not found` (exit 1), not an IndexError."""
    _, stubber = snapshot_rds
    _describe_cluster(stubber, {"DBClusters": []})

    result = _invoke_create()

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "not found" in result.output.lower()
    assert CLUSTER_ID in result.output
    stubber.assert_no_pending_responses()


def test_create_on_cluster_not_found_fault_exits_1_not_found(snapshot_rds):
    """AC: DBClusterNotFoundFault is `not found` (exit 1), not a raw ClientError."""
    _, stubber = snapshot_rds
    stubber.add_client_error(
        "describe_db_clusters",
        service_error_code="DBClusterNotFoundFault",
        service_message=f"DBCluster {CLUSTER_ID} not found.",
        http_status_code=404,
        expected_params={"DBClusterIdentifier": CLUSTER_ID},
    )

    result = _invoke_create()

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "not found" in result.output.lower()
    assert CLUSTER_ID in result.output
    stubber.assert_no_pending_responses()


def test_create_backing_up_then_stopped_exits_1_after_one_sleep(
    snapshot_rds, recorded_sleeps
):
    """AC: leaving backing-up for a bad state exits 1 at once, without creating."""
    _, stubber = snapshot_rds
    _describe_cluster(stubber, cluster("backing-up"))  # precheck
    _describe_cluster(stubber, cluster("stopped"))  # sleep, then poll 1 -> fail

    result = _invoke_create()

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert "stopped" in result.output
    assert recorded_sleeps == [10]
    stubber.assert_no_pending_responses()


def test_create_backing_up_timeout_exits_1_without_creating(
    snapshot_rds, recorded_sleeps
):
    """AC: staying backing-up past the poll limit exits 1 naming the cluster and state."""
    _, stubber = snapshot_rds
    for _ in range(101):  # precheck + 100 polls
        _describe_cluster(stubber, cluster("backing-up"))

    result = _invoke_create()

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert CLUSTER_ID in result.output
    assert "backing-up" in result.output
    assert recorded_sleeps == [10] * 100
    stubber.assert_no_pending_responses()


def test_create_backing_up_then_available_creates_snapshot(
    snapshot_rds, recorded_sleeps
):
    """AC: backing-up -> available still proceeds to create the snapshot (exit 0)."""
    _, stubber = snapshot_rds
    _describe_cluster(stubber, cluster("backing-up"))  # precheck
    _describe_cluster(stubber, cluster("backing-up"))  # poll 1
    _describe_cluster(stubber, cluster("available"))  # poll 2
    stubber.add_response(
        "create_db_cluster_snapshot",
        {
            "DBClusterSnapshot": {
                "DBClusterSnapshotIdentifier": SNAPSHOT_ID,
                "DBClusterIdentifier": CLUSTER_ID,
                "Status": "creating",
            }
        },
        {
            "DBClusterSnapshotIdentifier": SNAPSHOT_ID,
            "DBClusterIdentifier": CLUSTER_ID,
        },
    )

    result = _invoke_create()

    assert result.exit_code == 0, result.output
    assert "Creating snapshot" in result.output
    assert recorded_sleeps == [10, 10]  # one sleep before each of the two polls
    stubber.assert_no_pending_responses()
