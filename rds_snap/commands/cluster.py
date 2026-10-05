from .utils import (
    destroy_cluster,
    get_rds_clusters,
    get_rds_client,
    restore_cluster,
    tag_resource,
)
import logging, click, click_log, json
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.ERROR)
CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


@click.help_option("--help", "-h")
@click.group()
def cluster():
    """Commands to manage AWS RDS Aurora clusters"""
    pass


@cluster.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option("--cluster", default=None, help="list specific rds cluster")
@click.option(
    "--no-header", "no_head", is_flag=True, help="do not display table header"
)
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def list(profile, cluster, no_head):
    """List the AWS RDS Aurora clusters"""
    xs = get_rds_clusters(cluster, get_rds_client(profile))
    header = ", ".join(
        (
            "DBClusterIdentifier",
            "Status",
            "Engine",
            "ClusterCreateTime",
        )
    )
    if xs and not no_head:
        print(header)
    for i in xs:
        info = ", ".join(
            (
                i["DBClusterIdentifier"],
                i["Status"],
                i["Engine"],
                i["ClusterCreateTime"].strftime("%F-%H:%M:%S"),
            )
        )
        print(info)


@cluster.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option("--cluster", default=None, required=True, help="specific rds cluster")
@click.option("--tags", default=None, required=True, help="tags to add to cluster")
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def tag(profile, cluster, tags):
    """Add Tags to AWS RDS Aurora clusters"""
    tags_json = json.loads(tags)
    rds_client = get_rds_client(profile)
    try:
        xs = get_rds_clusters(cluster_identifier=cluster, rds=rds_client)
        arns = []
        for i in xs:
            arns.append(i["DBClusterArn"])
            response = rds_client.describe_db_instances(
                Filters=[
                    {
                        "Name": "db-cluster-id",
                        "Values": [
                            i["DBClusterIdentifier"],
                        ],
                    },
                ],
            )["DBInstances"]
            for instance in response:
                arns.append(instance["DBInstanceArn"])
    except ClientError as e:
        logger.exception(f"Unable to describe cluster {cluster}")
        raise click.ClickException(f"Unable to describe cluster {cluster}: {e}")
    for arn in arns:
        try:
            tag_resource(arn_identifier=arn, tags=tags_json, rds=rds_client)
        except ClientError as e:
            logger.exception(f"Unable to tag resource {arn}")
            raise click.ClickException(f"Unable to tag resource {arn}: {e}")


@cluster.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option(
    "--snapshot-identifier",
    default=None,
    help="specific rds cluster snapshot to restore",
)
@click.option(
    "--cluster-identifier",
    default=None,
    required=True,
    help="name of the new rds cluster",
)
@click.option(
    "--db-subnet-group-name",
    default=None,
    required=True,
    help="subnet group to use",
)
@click.option(
    "--vpc-security-group-id",
    default=None,
    required=True,
    help="security group to use",
)
@click.option(
    "--db-cluster-parameter-group-name",
    default=None,
    required=True,
    help="cluster parameter group to use",
)
@click.option(
    "--db-cluster-master-password",
    default=None,
    required=True,
    help="new master password to use",
)
@click.option(
    "--db-instance-class",
    default=None,
    required=True,
    help="db instance class to use",
)
@click.option(
    "--max-wait-minutes",
    type=click.IntRange(min=1),
    default=None,
    help="maximum minutes to wait for the restored cluster/instance to become available, as one budget shared by the cluster, password-reset and instance waits; when omitted the built-in ceilings apply: cluster 60m, instance 120m",
)
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def restore(
    profile,
    snapshot_identifier,
    cluster_identifier,
    db_subnet_group_name,
    vpc_security_group_id,
    db_cluster_parameter_group_name,
    db_cluster_master_password,
    db_instance_class,
    max_wait_minutes,
):
    """Restore AWS RDS Aurora cluster from snapshot"""
    if not snapshot_identifier:
        snapshot_identifier = "staging-horizon-2021-07-29-133932"
    if not cluster_identifier:
        cluster_identifier = "staging-horizon-a"
    rds_client = get_rds_client(profile)
    xs = restore_cluster(
        snapshot_identifier,
        cluster_identifier,
        db_subnet_group_name,
        vpc_security_group_id,
        db_cluster_parameter_group_name,
        db_cluster_master_password,
        db_instance_class,
        rds_client,
        max_wait_minutes=max_wait_minutes,
    )


@cluster.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option(
    "--snapshot-identifier",
    default=None,
    required=False,
    help="name of new rds cluster snapshot",
)
@click.option(
    "--cluster-identifier",
    default=None,
    required=True,
    help="name of the rds cluster to destroy",
)
@click.option(
    "--wait",
    default=False,
    is_flag=True,
    help="wait for cluster destruction",
)
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def delete(profile, snapshot_identifier, cluster_identifier, wait):
    """Delete AWS RDS Aurora cluster skipping the final snapshot. If a snapshot identifier is provided, a snapshot will be created before deletion"""
    rds_client = get_rds_client(profile)
    destroy_cluster(
        cluster_identifier,
        snapshot_identifier,
        wait,
        rds_client,
    )


def _describe_failed(
    operation: str, cluster_identifier: str, error: ClientError
) -> str:
    """Message for a describe call that failed with a botocore ClientError."""
    code = error.response["Error"]["Code"]
    message = error.response["Error"]["Message"]
    return f"{operation} failed for cluster {cluster_identifier}: {code}: {message}"


@cluster.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option("--cluster-identifier", required=True, help="rds cluster to verify")
@click.option(
    "--instance-identifier",
    required=True,
    multiple=True,
    help="expected member instance",
)
@click_log.simple_verbosity_option(
    logger,
    default="ERROR",
    help="Either CRITICAL, ERROR, WARNING, INFO or DEBUG, default is ERROR",
)
def verify(profile, cluster_identifier, instance_identifier):
    """Verify an AWS RDS Aurora cluster's status and member instances"""
    rds_client = get_rds_client(profile)
    try:
        clusters = get_rds_clusters(cluster_identifier, rds_client)
    except ClientError as error:
        code = error.response["Error"]["Code"]
        if code == "DBClusterNotFoundFault":
            raise click.ClickException(f"Cluster {cluster_identifier} not found")
        raise click.ClickException(
            _describe_failed("describe_db_clusters", cluster_identifier, error)
        )
    if not clusters:
        raise click.ClickException(f"Cluster {cluster_identifier} not found")

    cluster_info = clusters[0]
    status = cluster_info["Status"]
    if status != "available":
        raise click.ClickException(
            f"Cluster {cluster_identifier} status is '{status}', expected 'available'"
        )

    members = cluster_info.get("DBClusterMembers", [])
    expected = set(instance_identifier)
    actual = {member["DBInstanceIdentifier"] for member in members}
    if actual != expected:
        raise click.ClickException(
            f"Cluster {cluster_identifier} member mismatch: expected {sorted(expected)}, actual {sorted(actual)}"
        )

    writer_ids = sorted(
        member["DBInstanceIdentifier"]
        for member in members
        if member["IsClusterWriter"]
    )
    if len(writer_ids) != 1:
        raise click.ClickException(
            f"Cluster {cluster_identifier} has {len(writer_ids)} writer(s), expected exactly 1: {writer_ids}"
        )

    try:
        response = rds_client.describe_db_instances(
            Filters=[{"Name": "db-cluster-id", "Values": [cluster_identifier]}]
        )
    except ClientError as error:
        raise click.ClickException(
            _describe_failed("describe_db_instances", cluster_identifier, error)
        )
    statuses = {
        instance["DBInstanceIdentifier"]: instance["DBInstanceStatus"]
        for instance in response["DBInstances"]
    }
    unavailable = [
        f"{instance_id} ({statuses.get(instance_id, 'missing')})"
        for instance_id in sorted(expected)
        if statuses.get(instance_id, "missing") != "available"
    ]
    if unavailable:
        raise click.ClickException(f"Instances not available: {', '.join(unavailable)}")

    click.echo(f"{cluster_identifier}: {status}")
    for member in sorted(members, key=lambda member: member["DBInstanceIdentifier"]):
        member_id = member["DBInstanceIdentifier"]
        click.echo(
            f"  {member_id}: writer={member['IsClusterWriter']} status={statuses[member_id]}"
        )
