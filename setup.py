from setuptools import setup, find_packages
from os.path import join, dirname, abspath
import io

here = abspath(dirname(__file__))

with open(join(here, 'VERSION')) as VERSION_FILE:
    __versionstr__ = VERSION_FILE.read().strip()


with open(join(here, 'requirements.txt')) as REQUIREMENTS:
    INSTALL_REQUIRES = REQUIREMENTS.read().split('\n')


with io.open(join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()


CONSOLE_SCRIPTS = [
    'sumomongodbatlascollector=sumomongodbatlascollector.main:main'
]

setup(
    name="sumologic-mongodb-atlas",
    version=__versionstr__,
    packages=find_packages(),
    install_requires=INSTALL_REQUIRES,
    extras_require={
        ':python_version < "3.2"': ['futures'],
        ':python_version < "3.6"': ['future-fstrings'],
        'aws': ["boto3>=1.9.66", "botocore>=1.12.66"],
        "gcp": ["google-api-python-client>=1.7.8", "oauth2client>=4.1.3", "google-cloud-datastore>=1.7.3"],
        "azure": ["azure-cosmosdb-table>=1.0.5", "bson>=0.5.8"]
    },
    # PyPI metadata
    author="SumoLogic",
    author_email="it@sumologic.com",
    description="Sumo Logic collection solution for mongodb atlas",
    license="PSF",
    long_description=long_description,
    long_description_content_type='text/markdown',
    keywords="sumologic python rest api log management analytics logreduce mongodb atlas agent security siem collector forwarder",
    url="https://github.com/SumoLogic/sumologic-mongodb-atlas",
    zip_safe=True,
    include_package_data=True,
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.7',
        'Operating System :: OS Independent'
    ],
    entry_points={
        'console_scripts': CONSOLE_SCRIPTS,
    }

)
