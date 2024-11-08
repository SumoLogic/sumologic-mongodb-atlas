### OnPrem

1. For generating the build and running locally, we perform these steps:

    * Upgrade the version in the `VERSION` file, eg 1.0.10 -> 1.0.11
    * Run the `build.sh`.
    * Create a `mongodbatlas.yaml` in home folder (for ex ~/sumo/mongodbatlas.yaml), refer the `sumomongodbatlascollector/mongodbatlas.yaml` file for instructions on each of the parameter. You can override any parameter in this file
        ```
        SumoLogic:
          HTTP_LOGS_ENDPOINT: <Paste the HTTP Logs source URL from step 2.>
          HTTP_METRICS_ENDPOINT: <Paste the HTTP Metrics source URL from step 2.>

        MongoDBAtlas:
          ORGANIZATION_ID: <Paste the Organization ID from step 1.>
          PROJECT_ID: <Paste the Project ID from step 1.>
          PRIVATE_API_KEY: <Paste the Private Key from step 1.>
          PUBLIC_API_KEY: <Paste the Public Key from step 1.>
        ```
    * Run the below command to start the collector
        ```
            python -m sumomongodbatlascollector.main ~/sumo/mongodbatlas.yaml
        ```

2.  For deploying on test pypi account we perform these steps:
    * Run the following command:
        ```
        python -m twine upload dist/* --repository sumotestpypi
        ```
    * This deploys the package in the testing org of pypi via the credentials stored in the .pypirc file for the sumotestpypi section. You can find the file in the shared vault.
3.  For deploying on prod pypi account we perform these steps:
    * Run the following command:
        ```
        python -m twine upload dist/* --repository sumopypi
        ```
    * This deploys the package in the production org of pypi via the credentials stored in the .pypirc file for the sumopypi section. You can find the file in the shared vault.

### AWS

1.  For testing and deploying the lambda function, we perform these steps:
    * Update .aws file to use a personal aws account credentials.
    * Create a S3 bucket in the personal aws account.
    * In samconfig.toml file update s3_bucket, region parameters.
    * Generate credentials in Mongodb atlas portal and update parameter_overrides in samconfig.toml file.
    * Upgrade the SemanticVersion in the template.yaml file and s3_prefix in samconfig.toml file
    * Run the following commands:
        ```
            sam build
            sam package
            sam deploy
        ```
    * This deploys the package via a personal aws account onto AWS Serverless Application Repository
    * After deploying go the lambda function created by above command and run the function by clicking on test button.
2.  For publishing the sam application, we perform these steps:
    * Update the s3_bucket parameter to appdevstore bucket
    * Run the following command:
        ```
        sam publish
        ```
    * This deploys the package via the sumocontent aws account onto AWS Serverless Application Repository
