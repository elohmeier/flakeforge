from setuptools import find_packages, setup

setup(
    name="flakeforge",
    version="0.0.1",
    description="Serve docker images from Nix flakes",
    author="Enno Richter <enno@nerdworks.de>",
    packages=find_packages(),
    install_requires=[
        "starlette",
        "uvicorn",
    ],
    entry_points={
        "console_scripts": [
            "flakeforge = flakeforge:cli",
        ]
    },
)
