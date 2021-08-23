from .commands.cluster import cluster
from .commands.snapshot import snapshot
from .version import __version__
from signal import signal, SIGINT
from sys import exit
import click, logging

_tool_name = "rds-snap"
logger = logging.getLogger()
logger.setLevel(logging.ERROR)
logging.basicConfig(
    format="[%(asctime)s] "
    + _tool_name
    + " [%(levelname)s] %(funcName)s %(lineno)d: %(message)s"
)


def version():
    """Return the version of this cli tool"""
    return __version__


def sigint_handler(signal_received, frame):
    """Handle SIGINT or CTRL-C and exit gracefully"""
    logger.warning("SIGINT or CTRL-C detected. Exiting gracefully")
    exit(0)


@click.group(help="CLI tool to manage AWS RDS Aurora clusters/snapshots")
@click.help_option("--help", "-h")
@click.version_option(
    prog_name=_tool_name, version=version(), message="%(prog)s, version %(version)s"
)
def main():
    pass


main.add_command(snapshot)
main.add_command(cluster)

if __name__ == "__main__":
    signal(SIGINT, sigint_handler)
    main()
