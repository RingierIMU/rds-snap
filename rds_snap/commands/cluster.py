from rds_snap.commands.waiters import get_rds_cluster
import click
from pprint import pprint
from .utils import destroy_cluster, get_rds_clusters, get_rds_client, restore_cluster

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
def restore(
    profile,
    snapshot_identifier,
    cluster_identifier,
    db_subnet_group_name,
    vpc_security_group_id,
    db_cluster_parameter_group_name,
    db_cluster_master_password,
    db_instance_class,
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
    )


@cluster.command(context_settings=CONTEXT_SETTINGS)
@click.option("--profile", default=None, help="aws profile")
@click.option(
    "--snapshot-identifier",
    default=None,
    required=True,
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
def delete(profile, snapshot_identifier, cluster_identifier, wait):
    """Delete AWS RDS Aurora cluster"""
    if not snapshot_identifier:
        snapshot_identifier = "staging-horizon-2021-07-29-133932"
    if not cluster_identifier:
        cluster_identifier = "staging-horizon-a"
    rds_client = get_rds_client(profile)
    destroy_cluster(
        cluster_identifier,
        snapshot_identifier,
        wait,
        rds_client,
    )
