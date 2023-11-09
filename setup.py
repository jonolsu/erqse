from setuptools import setup, find_packages
import os

"""
Borrowed heavily from https://github.com/bast/somepackage/blob/master/setup.py
"""

_here = os.path.abspath(os.path.dirname(__file__))

with open(os.path.join(_here, "README.rst")) as f:
    long_description = f.read()

version = {}
with open(os.path.join(_here, "erqse", "version.py")) as f:
    exec(f.read(), version)

install_requires = [
    "lxml==4.6.5",
    "black==23.3.0",
    "environs==9.5.0",
    "requests==2.31.0",
    "xmlsec==1.3.13",
    "zeep==4.2.1",
]


setup(
    name="erqse",
    url="https://github.com/jonolsu/erqse",
    author="Jonathan Bennett",
    author_email="jonathan@konoanalytics.com",
    packages=find_packages(),
    package_dir={"erqse": "erqse"},
    package_data={"erqse": ["wsdl/*"]},
    include_package_data=True,
    install_requires=install_requires,
    version=version["__version__"],
    license="Proprietary",
    description="Enchanted Rock ERCOT QSE Python Utilities",
    long_description=long_description,
    python_requires=">=3.10, <3.11",
)
