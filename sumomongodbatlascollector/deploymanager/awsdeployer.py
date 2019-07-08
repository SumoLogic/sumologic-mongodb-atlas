import os
import sys
import subprocess
import shutil

import yaml


if __name__ == "__main__":
    cur_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, cur_dir)

from common.config import Config
from common.logger import get_logger

from deploymanager.utils import RESOURCE_FOLDER, generate_file, create_dir, get_config, remove_unwanted_files, \
    upload_code_in_S3, copytree


class AWSDeployer(object):
    def __init__(self):
        if os.getenv("AWS_PROFILE") == "prod":
            self.SAM_S3_BUCKET="appdevstore"
            self.AWS_REGION="us-east-1"
        else:
            self.SAM_S3_BUCKET="appdevstore-us-east-1"
            self.AWS_REGION="us-east-1"
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
        self.aws_target_dir = os.path.join(target_dir, "aws")
        self.log.info(f"creating aws target directory {self.aws_target_dir}")
        create_dir(self.aws_target_dir)

    def get_param_name(self, s):
        return s.title().replace("_", "")

    def create_parameters(self, sam_template_path):
        self.log.debug(f"adding parameters {sam_template_path}")
        cfg = Config()
        sam_config = cfg.read_config(sam_template_path)
        function_name = "%sFunction" % self.deploy_config["APPNAME_SINGLE"]
        vars = sam_config["Resources"][function_name]["Properties"]['Environment']["Variables"]
        sam_config["Parameters"] = params = sam_config["Parameters"] or {}
        self.template_params = set()
        for section, section_cfg in self.base_config.items():
            for k, v in section_cfg.items():
                if v is None:
                    param_name = self.get_param_name(k)
                    params[param_name] = {"Type": "String"}
                    vars[k] = {"Ref": param_name}
                    self.template_params.add(param_name)
        with open(sam_template_path, "w") as f:
            f.write(yaml.dump(sam_config, default_flow_style=False))
            # yaml.dump(sam_config, f)

    def generate_template(self):
        base_same_template_path = os.path.join(RESOURCE_FOLDER, "aws", "basesamtemplate.yaml")
        target_filepath = os.path.join(self.aws_target_dir, "samtemplate.yaml")
        self.log.info(f"generating_template {target_filepath}")
        generate_file(base_same_template_path, self.deploy_config, target_filepath)
        self.create_parameters(target_filepath)
        return target_filepath

    def deploy_package(self, template_file_path):
        # Todo create layer, create and publish SAM
        # sam package --template-file MongoDBAtlas.yaml --s3-bucket $SAM_S3_BUCKET  --output-template-file packaged_MongoDBAtlas.yaml

        self.log.info(f"deploying template in {os.getenv('AWS_PROFILE')} Region: {self.AWS_REGION}")
        env_vars = []
        user_cfg = Config().read_config(os.path.expanduser(f"~/{self.deploy_config['COLLECTION_CONFIG']}"))
        for section, section_cfg in user_cfg.items():
            for k, v in section_cfg.items():
                param_name = self.get_param_name(k)
                if param_name in self.template_params:
                    env_vars.append(f"{param_name}=\"{v}\"")
        cmd = ["sam", "deploy", "--template-file", template_file_path, "--stack-name", f"testing{self.deploy_config['APPNAME_SINGLE']}", "--capabilities", "CAPABILITY_IAM", "--region", self.AWS_REGION, "--parameter-overrides", *env_vars]
        self.log.debug(f"Running cmd: {' '.join(cmd)}")
        subprocess.run(cmd)

        # aws cloudformation get-template --stack-name testingMongoDBAtlas  --region $AWS_REGION > MongoDBAtlasCFTemplate.json
        # aws cloudformation describe-stack-events --stack-name testingsecurityhublambda --region $AWS_REGION
        # aws serverlessrepo create-application-version --region us-east-1 --application-id arn:aws:serverlessrepo:us-east-1:$AWS_ACCOUNT_ID:applications/sumologic-securityhub-connector --semantic-version 1.0.1 --template-body file://packaged.yaml

    def build_zip(self):
        # Todo convert pip/zip to non command based
        aws_build_folder = os.path.join(self.aws_target_dir, "build")
        create_dir(aws_build_folder)
        os.chdir(aws_build_folder)
        self.log.debug(f"changing to build dir: {os.getcwd()}")
        zip_file_path = os.path.join(self.aws_target_dir, self.deploy_config["APPNAME_SINGLE"]+".zip")
        requirement_filepath = os.path.join(self.project_dir, "requirements.txt")
        shutil.copy(requirement_filepath, aws_build_folder)
        subprocess.run(["pip", "install", "-r", "requirements.txt", "-t", "."])
        self.log.debug(f"installing dependencies {requirement_filepath}")
        src_dir = os.path.join(self.project_dir, self.deploy_config['SRC_FOLDER_NAME'])
        self.log.debug(f"copying src {src_dir}")
        copytree(src_dir, aws_build_folder)
        shutil.rmtree(os.path.join(aws_build_folder,"concurrent"))
        shutil.rmtree(os.path.join(aws_build_folder,"futures-3.1.1.dist-info"))
        self.log.info(f"creating zip file {zip_file_path}")
        subprocess.run(["zip", "-r", zip_file_path, "."])
        return zip_file_path

    def build_and_deploy(self):
        template_file_path = self.generate_template()
        zip_file_path = self.build_zip()
        upload_code_in_S3(zip_file_path, self.SAM_S3_BUCKET, self.AWS_REGION)
        self.deploy_package(template_file_path)



if __name__ == "__main__":
    AWSDeployer().build_and_deploy()


