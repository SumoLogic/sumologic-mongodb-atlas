# -*- coding: future_fstrings -*-

import os
import shutil
import subprocess
from utils import ROOT_DIR, TARGET_FOLDER, RESOURCE_FOLDER, generate_file, create_target_dir, get_config, remove_unwanted_files


def generate_setup_files(config):
    create_target_dir()
    for filename in ["setup.py", "README.md", "MANIFEST.in"]:
        generate_file(os.path.join(RESOURCE_FOLDER, filename), config, os.path.join(TARGET_FOLDER, filename))
    for filename in ["LICENSE", "VERSION"]:
        shutil.copyfile(os.path.join(RESOURCE_FOLDER, filename), os.path.join(TARGET_FOLDER, filename))


def build_package():
    os.chdir(ROOT_DIR)
    print("changing to root dir: ", os.getcwd())
    subprocess.run(["pip", "install", "twine", "wheel", "setuptools"])
    subprocess.run(["python", "setup.py", "sdist", "bdist_wheel"])


def deploy_package():
    os.chdir(ROOT_DIR)
    print("changing to root dir: ", os.getcwd())
    subprocess.run(["python", "-m", "twine", "upload", "dist/*"])


def deploy_package_test_repo():
    os.chdir(ROOT_DIR)
    print("changing to root dir: ", os.getcwd())
    subprocess.run(["python", "-m", "twine", "upload", "dist/*", "--repository", "testpypi"])
    print("install using command: pip install --extra-index-url https://testpypi.python.org/pypi %s --no-cache-dir" % config['PACKAGENAME'])

def build_and_deploy(config):
    remove_unwanted_files(config)
    # create_target_dir()
    # generate_setup_files(config)
    print("current python env:", subprocess.run(["pyenv", "version"]))
    build_package()
    # deploy_package_test_repo()
    deploy_package()

if __name__ == "__main__":
    config = get_config()
    build_and_deploy(config)

