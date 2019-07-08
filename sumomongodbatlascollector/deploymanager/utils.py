# -*- coding: future_fstrings -*-
import os
from string import Template
import shutil
import boto3

from common.config import Config

RESOURCE_FOLDER = os.path.join(os.path.dirname(os.path.realpath(__file__)), "resources")

def get_config(configpath):
    cfg = Config()
    collection_config = cfg.read_config(configpath)
    deploy_metadata = collection_config["DeployMetaData"]
    deploy_config = {
        "APPNAME": deploy_metadata["APPNAME"],
        "PACKAGENAME": deploy_metadata["PACKAGENAME"],
        "SRC_FOLDER_NAME":deploy_metadata["SRC_FOLDER_NAME"],
        "COLLECTION_CONFIG": os.path.basename(configpath),
        "APPNAME_SINGLE": deploy_metadata["APPNAME"].replace(" ", '').replace("_", "")
    }

    return collection_config, deploy_config

def generate_file(basefilepath, params, target_filepath):
    with open(basefilepath) as fin:
        body = fin.read()
    sam_template = Template(body)
    sam_body = sam_template.substitute(**params)
    with open(target_filepath, "w") as fout:
        fout.write(sam_body)

def create_dir(dirpath):
    if not os.path.isdir(dirpath):
        os.mkdir(dirpath)

def remove_unwanted_files(PROJECT_DIR):
    print("removing build directories")

    # eggfile = f'''{config['PACKAGENAME'].replace("-", "_")}.egg-info'''
    # for dirname in ["dist", "build", "target", eggfile]:
    for dirname in ["target"]:
        dirpath = os.path.join(PROJECT_DIR, dirname)
        if os.path.isdir(dirpath):
            shutil.rmtree(dirpath)

    print("removing pyc/pycache files")
    for dirpath, dirnames, filenames in os.walk(PROJECT_DIR):

        for file in filenames:
            if file.endswith("pyc") or file.endswith(".db"):
                os.remove(os.path.join(dirpath, file))
        for dirname in dirnames:
            if dirname.startswith("__pycache__"):
                shutil.rmtree(os.path.join(dirpath, dirname))

    print("removing zip/db files")
    # dbfile = os.path.join(ROOT_DIR, config['SRC_FOLDER_NAME'], "omnistorage", config['APPNAME_SMALL'])
    # if os.path.isdir(TARGET_FOLDER):
    #     shutil.rmtree(TARGET_FOLDER)
    # zipfile = os.path.join(ROOT_DIR,f"{config['APPNAME_SINGLE']}.zip")
    #
    # for filepath in [dbfile, zipfile]:
    #     if os.path.isfile(filepath):
    #         os.remove(filepath)

def upload_code_in_S3(filepath, bucket_name, region):
    print("Uploading zip file in S3", region)
    s3 = boto3.client('s3', region)
    filename = os.path.basename(filepath)
    s3.upload_file(filepath, bucket_name, filename,
                   ExtraArgs={'ACL': 'public-read'})

def copytree(src, dst, symlinks=False, ignore=None):
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)
