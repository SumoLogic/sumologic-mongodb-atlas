# -*- coding: future_fstrings -*-
import os
from string import Template
import shutil

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
TARGET_FOLDER = os.path.join(ROOT_DIR, "deploymanager", "target")
RESOURCE_FOLDER = os.path.join(ROOT_DIR, "deploymanager", "resources")

def get_config():
    config = {
        "APPNAME": "MongoDB Atlas",
        "PACKAGENAME": "sumologic-mongodb-atlas"
    }
    config["APPNAME_SINGLE"] = config['APPNAME'].replace(" ", '')
    config["APPNAME_SMALL"] = config['APPNAME_SINGLE'].lower()
    config["SRC_FOLDER_NAME"] = f'''sumo{config['APPNAME_SMALL']}collector'''
    return config

def generate_file(filepath, params, target_dir):
    with open(filepath) as filein:
        src = Template(filein.read())
        result = src.substitute(params)
        with open(target_dir) as fileout:
            fileout.write(result)


def create_target_dir():
    if not os.path.isdir(TARGET_FOLDER):
        os.mkdir(TARGET_FOLDER)


def remove_unwanted_files(config):
    print("removing build directories")

    eggfile = f'''{config['PACKAGENAME'].replace("-", "_")}.egg-info'''
    for dirname in ["dist", "build", eggfile]:
        dirpath = os.path.join(ROOT_DIR, dirname)
        if os.path.isdir(dirpath):
            shutil.rmtree(dirpath)

    print("removing pyc/pycache files")
    for dirpath, dirnames, filenames in os.walk(ROOT_DIR):

        for file in filenames:
            if file.endswith("pyc") or file.endswith(".db"):
                os.remove(os.path.join(dirpath, file))
        for dirname in dirnames:
            if dirname.startswith("__pycache__"):
                shutil.rmtree(os.path.join(dirpath, dirname))

    print("removing zip/db files")
    dbfile = os.path.join(ROOT_DIR, config['SRC_FOLDER_NAME'], "omnistorage", config['APPNAME_SMALL'])
    if os.path.isdir(TARGET_FOLDER):
        shutil.rmtree(TARGET_FOLDER)
    zipfile = os.path.join(ROOT_DIR,f"{config['APPNAME_SINGLE']}.zip")

    for filepath in [dbfile, zipfile]:
        if os.path.isfile(filepath):
            os.remove(filepath)
