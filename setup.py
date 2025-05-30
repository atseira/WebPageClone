from setuptools import setup, find_packages

setup(
    name="WebPageClone",
    version="1.0.11",
    packages=find_packages(),
    install_requires=[
        "regex",
        "requests",
        "validators",
    ],
    author="I Kadek Agus Ariesta Putra",
    author_email="ikadekagusariestaputra@gmail.com",
    description="Packages to store web pages down to its assets completely.",
)
