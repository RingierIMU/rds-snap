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
)
from datetime import datetime
from time import perf_counter
import logging, click, click_log


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
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def list(profile, today, no_head):
    """List AWS RDS aurora snapshots"""
    today_timestamp = None
    if today:
        today_timestamp = (datetime.today()).date()
    xs = get_rds_snapshots(get_rds_client(profile))
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
    if xs:
        if wait:
            toc = perf_counter()
            print(
                "Created snapshot {} in {}".format(
                    xs["DBClusterSnapshotIdentifier"], seconds_to_duration(toc - tic)
                )
            )
        else:
            print("Creating snapshot {}".format(xs["DBClusterSnapshotIdentifier"]))
    else:
        print("Something went wrong creating snapshot {}".format(snapshot_identifier))


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
    except client.exceptions.DBClusterSnapshotNotFoundFault as e:
        print(f"Snapshot not found error: {e}")
    except client.exceptions.InvalidDBClusterSnapshotStateFault as e:
        print(f"Encountered invalid snapshot state: {e}")
    except Exception as e:
        print("Could not delete snapshot {}: {}".format(snapshot_identifier, e))
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
    except:
        print(
            "Could not share snapshot {} with aws account {}".format(
                snapshot_identifier, account_number
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
    if x:
        if wait:
            toc = perf_counter()
            print(
                "Created snapshot {} in {}".format(
                    x["DBClusterSnapshotIdentifier"], seconds_to_duration(toc - tic)
                )
            )
        else:
            print("Creating snapshot {}".format(x["DBClusterSnapshotIdentifier"]))
    else:
        print("Something went wrong creating snapshot {}".format(snapshot_identifier))
