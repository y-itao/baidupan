"""Package configuration for baidupan."""

import re

from setuptools import setup, find_packages

# Read version from baidupan/__init__.py to avoid duplication
with open("baidupan/__init__.py") as f:
    version = re.search(r'__version__\s*=\s*"(.+?)"', f.read()).group(1)

setup(
    name="baidupan",
    version=version,
    description="Baidu Pan CLI tool using official xpan API",
    author="baidupan contributors",
    license="MIT",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "requests",
    ],
    extras_require={
        "progress": ["tqdm"],
    },
    entry_points={
        "console_scripts": [
            "baidupan=baidupan.cli:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS",
    ],
)
