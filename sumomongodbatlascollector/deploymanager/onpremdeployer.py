# -*- coding: future_fstrings -*-

import os
import shutil
import subprocess
import sys

if __name__ == "__main__":
    cur_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, cur_dir)

from common.logger import get_logger
from deploymanager.utils import create_dir, get_config, remove_unwanted_files


class OnPremDeployer(object):

    def __init__(self):
        if len(sys.argv) > 1:
            configpath = sys.argv[1]
        else:
            raise Exception("pass collection config path as param")
        self.base_config, self.deploy_config = get_config(configpath)
        self.log = get_logger(__name__, **self.base_config['Logging'])
        self.project_dir = os.path.dirname(os.path.dirname(os.path.abspath(os.path.expanduser(configpath))))
        self.setup_env()

    def setup_env(self):
        remove_unwanted_files(self.project_dir)
        target_dir = os.path.join(self.project_dir, "target")
        create_dir(target_dir)
        self.onprem_target_dir = os.path.join(target_dir, "onprem")
        self.log.info(f"creating onprem target directory {self.onprem_target_dir}")
        create_dir(self.onprem_target_dir)

    # def generate_setup_files(self):
    #     for filename in ["setup.py", "README.md", "MANIFEST.in"]:
    #         generate_file(os.path.join(RESOURCE_FOLDER, filename), config, os.path.join(TARGET_FOLDER, filename))
    #     for filename in ["LICENSE", "VERSION"]:
    #         shutil.copyfile(os.path.join(RESOURCE_FOLDER, filename), os.path.join(TARGET_FOLDER, filename))

    def build_package(self):
        os.chdir(self.project_dir)
        self.log.debug("changing to root dir: %s" % os.getcwd())
        subprocess.run(["pip", "install", "twine", "wheel", "setuptools", "check-manifest"])
        self.log.info("generating build...")
        subprocess.run(["python", "setup.py", "sdist", "bdist_wheel"])
        subprocess.run(["check-manifest"])
        eggfile = f'''{self.deploy_config['PACKAGENAME'].replace("-", "_")}.egg-info'''
        for filename in [eggfile, "build", "dist"]:
            if os.path.isdir(filename) or os.path.isfile(filename):
                shutil.move(filename, self.onprem_target_dir)

    def deploy_package(self):
        os.chdir(self.onprem_target_dir)
        self.log.info("deploying package to pypi: %s" % self.onprem_target_dir)
        subprocess.run(["python", "-m", "twine", "upload", "dist/*"])

    def deploy_package_test_repo(self):
        os.chdir(self.onprem_target_dir)
        self.log.info("deploying package to testpypi: %s" % self.onprem_target_dir)
        subprocess.run(["python", "-m", "twine", "upload", "dist/*", "--repository", "testpypi"])
        self.log.info("install using command: pip install --extra-index-url https://testpypi.python.org/pypi %s --no-cache-dir" % self.deploy_config['PACKAGENAME'])

    def build_and_deploy(self):
        self.build_package()
        self.deploy_package_test_repo()
        # self.deploy_package()

if __name__ == "__main__":
    OnPremDeployer().build_and_deploy()

