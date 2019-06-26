import os
import subprocess
import boto3
import shutil
from utils import ROOT_DIR, TARGET_FOLDER, RESOURCE_FOLDER, generate_file, create_target_dir, get_config, remove_unwanted_files

if os.getenv("AWS_PROFILE") == "prod":
    SAM_S3_BUCKET="appdevstore"
    AWS_REGION="us-east-1"
else:
    SAM_S3_BUCKET="cf-templates-5d0x5unchag-us-east-2"
    AWS_REGION="us-east-2"


def upload_code_in_S3(filepath, bucket_name, region):
    print("Uploading zip file in S3", region)
    s3 = boto3.client('s3', region)
    filename = os.path.basename(filepath)
    s3.upload_file(filepath, bucket_name, filename,
                   ExtraArgs={'ACL': 'public-read'})


def create_parameters():
    pass

def generate_template():
    pass

def deploy_package():
    # Todo create layer, create and publish SAM
    # sam package --template-file MongoDBAtlas.yaml --s3-bucket $SAM_S3_BUCKET  --output-template-file packaged_MongoDBAtlas.yaml
    #
    # sam deploy --template-file packaged_MongoDBAtlas.yaml --stack-name testingMongoDBAtlas --capabilities CAPABILITY_IAM --region $AWS_REGION
    #
    # aws cloudformation get-template --stack-name testingMongoDBAtlas  --region $AWS_REGION > MongoDBAtlasCFTemplate.json

    # aws cloudformation describe-stack-events --stack-name testingsecurityhublambda --region $AWS_REGION
    # aws serverlessrepo create-application-version --region us-east-1 --application-id arn:aws:serverlessrepo:us-east-1:$AWS_ACCOUNT_ID:applications/sumologic-securityhub-connector --semantic-version 1.0.1 --template-body file://packaged.yaml
    pass

def copytree(src, dst, symlinks=False, ignore=None):
    for item in os.listdir(src):
        s = os.path.join(src, item)
        d = os.path.join(dst, item)
        if os.path.isdir(s):
            shutil.copytree(s, d, symlinks, ignore)
        else:
            shutil.copy2(s, d)

def build_zip(config):
    os.chdir(TARGET_FOLDER)
    print("changing to root dir: ", os.getcwd())
    print("creating zip file")
    shutil.copy(os.path.join(ROOT_DIR, "requirements.txt"), TARGET_FOLDER)
    subprocess.run(["pip", "install", "-r", "requirements.txt", "-t", "."])
    copytree(os.path.join(ROOT_DIR,config['SRC_FOLDER_NAME']), TARGET_FOLDER)
    shutil.rmtree(os.path.join(TARGET_FOLDER,"concurrent"))
    shutil.rmtree(os.path.join(TARGET_FOLDER,"futures-3.1.1.dist-info"))
    subprocess.run(["zip", "-r", os.path.join(ROOT_DIR,config["APPNAME_SINGLE"]+".zip"), "."])

def build_and_deploy(config):
    remove_unwanted_files(config)
    create_target_dir()
    # generate_template()
    print("current python env:", subprocess.run(["pyenv", "version"]))
    build_zip(config)
    upload_code_in_S3(os.path.join(ROOT_DIR,config["APPNAME_SINGLE"]+".zip"), SAM_S3_BUCKET, AWS_REGION)
    # deploy_package()



if __name__ == "__main__":
    config = get_config()
    build_and_deploy(config)

