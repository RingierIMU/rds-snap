from rds_snap.commands.waiters import get_rds_snapshot, seconds_to_duration
from .utils import (
    copy_rds_snapshot,
    get_kms_arn,
    get_kms_client,
    get_rds_snapshots,
    get_rds_client,
    create_rds_snapshot,
    delete_rds_snapshot,
    share_rds_snapshot,
    tag_resource,
)
from datetime import datetime
from time import perf_counter
from botocore.exceptions import ClientError
import logging, click, click_log, json


logger = logging.getLogger()
logger.setLevel(logging.ERROR)
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.help_option("--help", "-h")
@click.group()
def snapshot():
    """Commands to manage AWS RDS Aurora snapshots"""
    pass


@snapshot.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option("--today", is_flag=True, help="list cluster snapshots created today")
@click.option(
    "--no-header", "no_head", is_flag=True, help="do not display table header"
)
@click.option("--cluster-identifier", default=None, help="RDS cluster identifier")
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def list(profile, today, no_head, cluster_identifier):
    """List AWS RDS aurora snapshots"""
    today_timestamp = None
    if today:
        today_timestamp = (datetime.today()).date()
    xs = get_rds_snapshots(
        cluster_identifier=cluster_identifier,
        cluster_snapshot_identifier="",
        rds=get_rds_client(profile),
    )
    header = ", ".join(
        (
            "DBClusterSnapshotIdentifier",
            "DBClusterIdentifier",
            "Status",
            "SnapshotType",
            "SnapshotCreateTime",
        )
    )
    if xs and not no_head:
        print(header)
    for i in xs:
        info = ", ".join(
            (
                i["DBClusterSnapshotIdentifier"],
                i["DBClusterIdentifier"],
                i["Status"],
                i["SnapshotType"],
                i["SnapshotCreateTime"].strftime("%F-%H:%M:%S"),
            )
        )
        if today and i["SnapshotCreateTime"].date() == today_timestamp:
            print(info)
        elif not today:
            print(info)
    return


@snapshot.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option(
    "--snapshot", default=None, required=True, help="specific rds cluster snapshot"
)
@click.option(
    "--tags", default=None, required=True, help="tags to add to cluster snapshot"
)
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def tag(profile, snapshot, tags):
    """Add Tags to AWS RDS Aurora cluster snapshots"""
    tags_json = json.loads(tags)
    rds_client = get_rds_client(profile)
    try:
        xs = get_rds_snapshots(
            cluster_identifier="",
            cluster_snapshot_identifier=snapshot,
            rds=rds_client,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "DBClusterSnapshotNotFoundFault":
            xs = []
        else:
            logger.exception(f"Unable to describe snapshot {snapshot}")
            raise click.ClickException(f"Unable to describe snapshot {snapshot}: {e}")
    if not xs:
        click.echo(f"Warning: no snapshots matched {snapshot}, nothing to tag", err=True)
        return
    for arn in (i["DBClusterSnapshotArn"] for i in xs):
        try:
            tag_resource(arn_identifier=arn, tags=tags_json, rds=rds_client)
        except ClientError as e:
            logger.exception(f"Unable to tag snapshot {arn}")
            raise click.ClickException(f"Unable to tag snapshot {arn}: {e}")


@snapshot.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option(
    "--cluster",
    default=None,
    required=True,
    help="cluster for which snapshot should be made",
)
@click.option(
    "--snapshot-identifier", default=None, required=True, help="identifier for snapshot"
)
@click.option("--wait", is_flag=True, help="wait for snapshot creation to complete")
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def create(profile, cluster, snapshot_identifier, wait):
    """Create AWS RDS Aurora snapshots"""
    tic = perf_counter()
    xs = create_rds_snapshot(
        cluster_identifier=cluster,
        snapshot_identifier=snapshot_identifier,
        wait=wait,
        rds=get_rds_client(profile),
    )
    if wait:
        toc = perf_counter()
        print(
            "Created snapshot {} in {}".format(
                xs["DBClusterSnapshotIdentifier"], seconds_to_duration(toc - tic)
            )
        )
    else:
        print("Creating snapshot {}".format(xs["DBClusterSnapshotIdentifier"]))


@snapshot.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option(
    "--snapshot-identifier", default=None, required=True, help="identifier for snapshot"
)
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def delete(profile, snapshot_identifier):
    """Delete AWS RDS Aurora snapshots"""
    tic = perf_counter()
    client = get_rds_client(profile)
    try:
        xs = delete_rds_snapshot(snapshot_identifier, client)
    except client.exceptions.DBClusterSnapshotNotFoundFault:
        click.echo(
            "snapshot {} not found, nothing to delete".format(snapshot_identifier),
            err=True,
        )
    except client.exceptions.InvalidDBClusterSnapshotStateFault as e:
        logger.exception("Invalid state for snapshot {}".format(snapshot_identifier))
        raise click.ClickException(
            "Could not delete snapshot {}, invalid snapshot state: {}".format(
                snapshot_identifier, e
            )
        )
    except Exception as e:
        logger.exception("Could not delete snapshot {}".format(snapshot_identifier))
        raise click.ClickException(
            "Could not delete snapshot {}: {}".format(snapshot_identifier, e)
        )
    else:
        toc = perf_counter()
        print(
            "Successfully deleted snapshot {} in {}".format(
                xs["DBClusterSnapshotIdentifier"], seconds_to_duration(toc - tic)
            )
        )


@snapshot.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option(
    "--snapshot-identifier", default=None, required=True, help="identifier for snapshot"
)
@click.option(
    "--account-number",
    default=None,
    required=True,
    help="aws account number with which to share the snapshot",
)
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def share(profile, snapshot_identifier, account_number):
    """Share AWS RDS Aurora snapshots with another account"""
    tic = perf_counter()
    try:
        xs = share_rds_snapshot(
            snapshot_identifier, account_number, get_rds_client(profile)
        )
    except Exception as e:
        logger.exception(
            "Could not share snapshot {} with aws account {}".format(
                snapshot_identifier, account_number
            )
        )
        raise click.ClickException(
            "Could not share snapshot {} with aws account {}: {}".format(
                snapshot_identifier, account_number, e
            )
        )
    else:
        toc = perf_counter()
        print(
            "Successfully shared snapshot {} with aws account {} in {}".format(
                xs["DBClusterSnapshotIdentifier"],
                account_number,
                seconds_to_duration(toc - tic),
            )
        )


@snapshot.command(context_settings=CONTEXT_SETTINGS)
@click.option(
    "--source-profile",
    default=None,
    required=True,
    help="aws profile for account from which the snapshot should be copied",
)
@click.option(
    "--target-profile",
    default=None,
    required=True,
    help="aws profile for the account into which the snapshot should be copied",
)
@click.option(
    "--snapshot-identifier", default=None, required=True, help="identifier for snapshot"
)
@click.option(
    "--target-kms-alias",
    default=None,
    required=True,
    help="aws account number with which to share the snapshot",
)
@click.option("--wait", is_flag=True, help="wait for snapshot creation to complete")
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def copy(source_profile, target_profile, snapshot_identifier, target_kms_alias, wait):
    """Copy AWS RDS Aurora snapshots that have been shared"""
    tic = perf_counter()
    kms_arn = get_kms_arn(target_kms_alias, get_kms_client(target_profile))
    source_snapshot_arn = get_rds_snapshot(
        snapshot_identifier, get_rds_client(source_profile)
    )[0]["DBClusterSnapshotArn"]
    x = copy_rds_snapshot(
        snapshot_identifier,
        source_snapshot_arn,
        kms_arn,
        wait,
        get_rds_client(target_profile),
    )
    if wait:
        toc = perf_counter()
        print(
            "Created snapshot {} in {}".format(
                x["DBClusterSnapshotIdentifier"], seconds_to_duration(toc - tic)
            )
        )
    else:
        print("Creating snapshot {}".format(x["DBClusterSnapshotIdentifier"]))
