# -*- coding: future_fstrings -*-

import os
import shutil
import subprocess
from utils import ROOT_DIR, TARGET_FOLDER, RESOURCE_FOLDER, generate_file, create_target_dir, config, remove_unwanted_files


def generate_setup_files():
    create_target_dir()
    for filename in ["setup.py", "README.md", "MANIFEST.in"]:
        generate_file(os.path.join(RESOURCE_FOLDER, filename), config, os.path.join(TARGET_FOLDER, filename))
    for filename in ["LICENSE", "VERSION"]:
        shutil.copyfile(os.path.join(RESOURCE_FOLDER, filename), os.path.join(TARGET_FOLDER, filename))


def build_package():
    subprocess.run(["pip", "install", "twine", "wheel", "setuptools"])
    subprocess.run(["python", "setup.py", "sdist", "bdist_wheel"])


def deploy_package():
    subprocess.run(["python", "-m", "twine", "upload", "dist/*"])


def build_and_deploy():
    remove_unwanted_files()
    # create_target_dir()
    # generate_setup_files()
    print("current python env:", subprocess.run(["pyenv", "version"]))
    os.chdir(ROOT_DIR)
    print("changing to root dir: ", os.getcwd())
    build_package()
    deploy_package()


if __name__ == "__main__":
    build_and_deploy()

