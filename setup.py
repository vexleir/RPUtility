"""
Minimal setup for development install.
Run: pip install -e .
"""

from setuptools import setup, find_packages

setup(
    name="rp-utility",
    version="0.1.0",
    packages=find_packages(),
    python_requires=">=3.11",
    install_requires=[
        "httpx>=0.27.0",
        "pydantic>=2.0.0",
        "pydantic-settings>=2.0.0",
        "click>=8.1.0",
        "rich>=13.0.0",
        "aiosqlite>=0.20.0",
    ],
    extras_require={
        "dev": [
            "pytest>=8.0.0",
            "pytest-asyncio>=0.23.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "rp=app.main:cli",
        ]
    },
)
