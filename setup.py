from setuptools import setup, find_packages
from rds_snap.__main__ import version
from io import open
from os import path

import pathlib

# The directory containing this file
HERE = pathlib.Path(__file__).parent
# README.md content
README = (HERE / "README.md").read_text()

# automatically captured required modules for install_requires in requirements.txt
with open(path.join(HERE, "requirements.txt"), encoding="utf-8") as f:
    all_reqs = f.read().split("\n")
    install_requires = [
        x.strip()
        for x in all_reqs
        if ("git+" not in x) and (not x.startswith("#")) and (not x.startswith("-"))
    ]
    dependency_links = [
        x.strip().replace("git+", "") for x in all_reqs if "git+" not in x
    ]

setup(
    name="rds-snap",
    version=version(),
    keywords="aws, rds, aurora, snapshot, cluster",
    author="Ringier Tech",
    author_email="tools@ringier.co.za",
    description="Tool to allow for the management of aws rds aurora snapshots and clusters.",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://github.com/RingierIMU/rds-snap",
    packages=find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3",
    install_requires=install_requires,
    dependency_links=dependency_links,
    entry_points={
        "console_scripts": [
            "rds-snap=rds_snap.__main__:main",
        ],
    },
)
