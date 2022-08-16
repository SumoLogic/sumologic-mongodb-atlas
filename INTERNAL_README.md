We use sumoappclient for testing the lambda paackage. We can install it by: 
```
pip install sumologic-sdk
```
Description:
```
sumoappclient [-h] [-e {onprem,aws,gcp,azure}] [-d {prod,test,local}] [-c CONFIGPATH] [-pc PYTHON_CMD] [-g TARGET_FOLDER]
```

Deployment testing for PyPi:
1.  For onprem pypi testing of this package, we perform these steps:
        * Upgrade the version in the Version file, eg 1.0.10 -> 1.0.11
        * Run the following command 
        ```
        sumoappclient -d sumotest -c mongodbatlas.yaml -e onprem
        ```
        * This deploys the package in the testing org of pypi via the credentials stored in the .pypirc file for the sumotestpypi section. You can find the file in the shared vault.
2.  For onprem pypi production deployment, we perform these steps:
        * Upgrade the version in the Version file, eg 1.0.10 -> 1.0.11
        * Run the following command 
        ```
        sumoappclient -d sumopypi -c mongodbatlas.yaml -e onprem
        ```
        * This deploys the package in the production org of pypi via the credentials stored in the .pypirc file for the sumopypi section. You can find the file in the shared vault.

Deployment testing for AWS:
1.  For testing of this package, we perform these steps:
        * Update .aws file to use a personal aws account credentials
        * Create a S3 bucket named 'appdevstore' in the personal aws account
        * Upgrade the SemanticVersion in the template.yaml file, eg 1.0.16 -> 1.0.17
        * Run the following command 
        ```
        sumoappclient -d test -c mongodbatlas.yaml -e aws
        ```
        * This deploys the package via a personal aws account onto AWS Serverless Application Repository
2.  For onprem pypi production deployment, we perform these steps:
        * Update .aws file to use sumocontent aws account credentials
        * Upgrade the SemanticVersion in the template.yaml file, eg 1.0.16 -> 1.0.17
        * Run the following command 
        ```
        sumoappclient -d prod -c mongodbatlas.yaml -e aws
        ```
        * This deploys the package via the sumocontent aws account onto AWS Serverless Application Repository
