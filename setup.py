#!/usr/bin/env python3

import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="traefikswarm",
    version="0.0.9",
    author="Štefan Šimek",
    author_email="simek@triaxis.sk",
    description="A simple tool to manage traefik in a docker swarm",
    license="MIT",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/ssimek/traefikswarm",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    entry_points={
        'console_scripts': ['traefikswarm=traefikswarm.command_line:main']
    },
    install_requires=[
        'docker>=4',
    ],
    python_requires='>=3.6',
)
