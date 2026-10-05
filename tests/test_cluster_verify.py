"""Tests for `rds-snap cluster verify` (#30).

`verify` is a read-only health gate: it checks a cluster exists, is 'available',
has exactly the expected members with exactly one writer, and that every expected
instance is 'available'. Each failed check is a click.ClickException (exit 1, no
traceback). AWS is stubbed at the network boundary via botocore's Stubber.
"""

from click.testing import CliRunner

from rds_snap.commands import cluster as cluster_cmd
from tests.conftest import CLUSTER_ID, cluster_with_members, instances

WRITER = f"{CLUSTER_ID}-0"
READER = f"{CLUSTER_ID}-1"
CLUSTER_PARAMS = {"DBClusterIdentifier": CLUSTER_ID}
INSTANCE_PARAMS = {"Filters": [{"Name": "db-cluster-id", "Values": [CLUSTER_ID]}]}


def _invoke(monkeypatch, rds, *instance_ids, cluster_id=CLUSTER_ID):
    monkeypatch.setattr(cluster_cmd, "get_rds_client", lambda profile: rds)
    argv = ["verify", "--cluster-identifier", cluster_id]
    for instance_id in instance_ids:
        argv += ["--instance-identifier", instance_id]
    return CliRunner().invoke(cluster_cmd.cluster, argv)


def _assert_click_error(result, message):
    assert result.exit_code == 1, result.output
    assert "Error:" in result.output
    assert message in result.output
    # a ClickException exits via SystemExit; any other type is an unhandled traceback
    assert result.exception is None or isinstance(result.exception, SystemExit)


def _queue_cluster(stubber, payload):
    stubber.add_response("describe_db_clusters", payload, CLUSTER_PARAMS)


# --- CLI surface -------------------------------------------------------------


def test_cluster_help_lists_verify():
    result = CliRunner().invoke(cluster_cmd.cluster, ["--help"])
    assert result.exit_code == 0
    assert "verify" in result.output


def test_verify_help_lists_options():
    result = CliRunner().invoke(cluster_cmd.cluster, ["verify", "--help"])
    assert result.exit_code == 0, result.output
    for option in ("--profile", "--cluster-identifier", "--instance-identifier"):
        assert option in result.output


def test_verify_requires_cluster_identifier(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    monkeypatch.setattr(cluster_cmd, "get_rds_client", lambda profile: rds)
    result = CliRunner().invoke(
        cluster_cmd.cluster, ["verify", "--instance-identifier", WRITER]
    )
    assert result.exit_code == 2
    assert "--cluster-identifier" in result.output
    stubber.assert_no_pending_responses()


def test_verify_requires_instance_identifier(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    monkeypatch.setattr(cluster_cmd, "get_rds_client", lambda profile: rds)
    result = CliRunner().invoke(
        cluster_cmd.cluster, ["verify", "--cluster-identifier", CLUSTER_ID]
    )
    assert result.exit_code == 2
    assert "--instance-identifier" in result.output
    stubber.assert_no_pending_responses()


# --- success -----------------------------------------------------------------


def test_verify_succeeds_for_healthy_cluster(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    _queue_cluster(
        stubber, cluster_with_members("available", [(WRITER, True), (READER, False)])
    )
    stubber.add_response(
        "describe_db_instances",
        instances({WRITER: "available", READER: "available"}),
        INSTANCE_PARAMS,
    )

    result = _invoke(monkeypatch, rds, WRITER, READER)

    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert f"{CLUSTER_ID}: available" in lines
    assert f"  {WRITER}: writer=True status=available" in lines
    assert f"  {READER}: writer=False status=available" in lines
    stubber.assert_no_pending_responses()


# --- check 1: cluster lookup -------------------------------------------------


def test_verify_fails_when_cluster_not_found(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    stubber.add_client_error(
        "describe_db_clusters",
        service_error_code="DBClusterNotFoundFault",
        service_message=f"DBCluster {CLUSTER_ID} not found.",
        expected_params=CLUSTER_PARAMS,
    )

    result = _invoke(monkeypatch, rds, WRITER)

    _assert_click_error(result, f"Cluster {CLUSTER_ID} not found")
    stubber.assert_no_pending_responses()


def test_verify_fails_on_other_describe_clusters_error(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    stubber.add_client_error(
        "describe_db_clusters",
        service_error_code="AccessDenied",
        service_message="not authorised",
        expected_params=CLUSTER_PARAMS,
    )

    result = _invoke(monkeypatch, rds, WRITER)

    _assert_click_error(
        result, f"describe_db_clusters failed for cluster {CLUSTER_ID}:"
    )
    assert "AccessDenied" in result.output
    stubber.assert_no_pending_responses()


# --- check 2: cluster status -------------------------------------------------


def test_verify_fails_when_cluster_not_available(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    _queue_cluster(stubber, cluster_with_members("modifying", [(WRITER, True)]))

    result = _invoke(monkeypatch, rds, WRITER)

    _assert_click_error(
        result, f"Cluster {CLUSTER_ID} status is 'modifying', expected 'available'"
    )
    stubber.assert_no_pending_responses()


# --- check 3: membership -----------------------------------------------------


def test_verify_fails_on_member_mismatch(monkeypatch, stubbed_rds):
    """One expected member missing and one unexpected member present."""
    rds, stubber = stubbed_rds
    extra = f"{CLUSTER_ID}-9"
    _queue_cluster(
        stubber, cluster_with_members("available", [(WRITER, True), (extra, False)])
    )

    result = _invoke(monkeypatch, rds, WRITER, READER)

    _assert_click_error(result, f"Cluster {CLUSTER_ID} member mismatch:")
    assert f"expected {sorted([WRITER, READER])!r}" in result.output
    assert f"actual {sorted([WRITER, extra])!r}" in result.output
    stubber.assert_no_pending_responses()


# --- check 4: exactly one writer ---------------------------------------------


def test_verify_fails_with_no_writer(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    _queue_cluster(
        stubber, cluster_with_members("available", [(WRITER, False), (READER, False)])
    )

    result = _invoke(monkeypatch, rds, WRITER, READER)

    _assert_click_error(
        result, f"Cluster {CLUSTER_ID} has 0 writer(s), expected exactly 1: []"
    )
    stubber.assert_no_pending_responses()


def test_verify_fails_with_two_writers(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    _queue_cluster(
        stubber, cluster_with_members("available", [(READER, True), (WRITER, True)])
    )

    result = _invoke(monkeypatch, rds, WRITER, READER)

    _assert_click_error(
        result,
        f"Cluster {CLUSTER_ID} has 2 writer(s), expected exactly 1: "
        f"{sorted([WRITER, READER])!r}",
    )
    stubber.assert_no_pending_responses()


# --- check 5: instance status ------------------------------------------------


def test_verify_fails_when_instance_not_available(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    _queue_cluster(
        stubber, cluster_with_members("available", [(WRITER, True), (READER, False)])
    )
    stubber.add_response(
        "describe_db_instances",
        instances({WRITER: "available", READER: "creating"}),
        INSTANCE_PARAMS,
    )

    result = _invoke(monkeypatch, rds, WRITER, READER)

    _assert_click_error(result, f"Instances not available: {READER} (creating)")
    stubber.assert_no_pending_responses()


def test_verify_fails_on_describe_instances_error(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    _queue_cluster(stubber, cluster_with_members("available", [(WRITER, True)]))
    stubber.add_client_error(
        "describe_db_instances",
        service_error_code="AccessDenied",
        service_message="not authorised",
        expected_params=INSTANCE_PARAMS,
    )

    result = _invoke(monkeypatch, rds, WRITER)

    _assert_click_error(
        result, f"describe_db_instances failed for cluster {CLUSTER_ID}:"
    )
    assert "AccessDenied" in result.output
    stubber.assert_no_pending_responses()


def test_verify_reports_instance_missing_from_describe(monkeypatch, stubbed_rds):
    rds, stubber = stubbed_rds
    _queue_cluster(
        stubber, cluster_with_members("available", [(WRITER, True), (READER, False)])
    )
    stubber.add_response(
        "describe_db_instances", instances({WRITER: "available"}), INSTANCE_PARAMS
    )

    result = _invoke(monkeypatch, rds, WRITER, READER)

    _assert_click_error(result, f"Instances not available: {READER} (missing)")
    stubber.assert_no_pending_responses()
