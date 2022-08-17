# sumologic-mongodb-atlas

Solution to pull alerts from Mongo DB Atlas to Sumo Logic


## Installation

This collector can be deployed both onprem and on cloud.


### Deploying the collector on a VM
1. Get Authentication information from the MongoDB Atlas portal
    * Generate Programmatic API Keys with Project owner permissions using the instructions in the Atlas docs. Copy the Public Key and Private Key. These serve the same function as a username and API Key respectively. Note: If you want to use the AWS Lambda function for collection, do not Select Add Whitelist Entry.
    * Go to your project and then click on settings. Copy the project ID as shown below:

    * Go to your organization by using context drop down at the top. Then click on settings and copy the organization ID.


2. Add a Hosted Collector and one HTTP Logs and Metrics Source

    * To create a new Sumo Logic Hosted Collector, perform the steps in [Configure a Hosted Collector](https://help.sumologic.com/03Send-Data/Hosted-Collectors/Configure-a-Hosted-Collector).
    * Add an [HTTP Logs and Metrics Source](https://help.sumologic.com/03Send-Data/Sources/02Sources-for-Hosted-Collectors/HTTP-Source). Under Advanced you'll see options regarding timestamps and time zones and when you select Timestamp parsing specify the custom time stamp format as shown below:
      - Format: `yyyy-MM-dd'T'HH:mm:ss.SSS'Z'`
      - Timestamp locator: `\"created\": (.*),`.
    * Add another HTTP Source this time for metric

3. Method 1 - Configuring the **sumologic-mongodbatlas** collector

    Below instructions assume pip is already installed if not then, see the pip [docs](https://pip.pypa.io/en/stable/installing/) on how to download and install pip.
    *sumologic-mongodbatlas* is compatible with python 3.7 and python 2.7. It has been tested on Ubuntu 18.04 LTS and Debian 4.9.130.
    Login to a Linux machine and download and follow the below steps:

    * Install the collector using below command
      ``` pip install sumologic-mongodbatlas```

    * Create a configuration file named mongodbatlas.yaml in home directory by copying the below snippet.

    ```
        SumoLogic:
         HTTP_LOGS_ENDPOINT: <Paste the URL for the HTTP Logs source from step 2.>
         HTTP_METRICS_ENDPOINT: <Paste the URL for the HTTP Metrics source from step 2.>

        MongoDBAtlas:
         ORGANIZATION_ID: Paste the Organization ID from step 1.
         PROJECT_ID: Paste the Project ID from step 1.
         PRIVATE_API_KEY: Paste the Private Key from step 1.
         PUBLIC_API_KEY: Paste the Public Key from step 1.
    ```
    * Create a cron job  for running the collector every 5 minutes by using the crontab -e and adding the below line

        `*/5 * * * *  /usr/bin/python -m sumomongodbatlascollector.main > /dev/null 2>&1`

   Method 2 - Collection via an AWS Lambda function
   To install Sumo Logic’s AWS Lambda script, follow the instructions below:

    * Go to https://serverlessrepo.aws.amazon.com/applications
Search for “sumologic-mongodb-atlas” and select the app as shown below:

    * When the page for the Sumo app appears as shown below, click the Deploy button as shown below:


    * In the Configure application parameters panel, shown below:

        * HTTPLogsEndpoint: Paste the URL for the HTTP Logs source from step 2.
        * HTTPMetricsEndpoint: Paste the URL for the HTTP Metrics source from step 2.
        * OrganizationID: Paste the Organization ID from step 1.
        * ProjectID: Paste the Project ID from step 1.
        * Private API Key: Paste the Private Key from step 1.
        * Public API Key: Paste the Public Key from step 1.
    * Click Deploy.
    * Whitelisting Lambda's IP Address
        * Search for Lambda in the AWS console, select Functions tab and open the function just created.
        * Go to the Configuration>Permissions tab of the function>click on the Execution role name link to open up the IAM window containing all the permission policies.
        * Click on Add permissions>Create inline policy. Choose JSON and copy this policy statement:
        ```
        { "Version": "2012-10-17", "Statement": [ { "Effect": "Allow", "Action": [ "ec2:DescribeNetworkInterfaces", "ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface", "ec2:DescribeInstances", "ec2:AttachNetworkInterface" ], "Resource": "*" } ] }
        ```
        Click on Review policy>give an appropriate name>click on Create policy.
        Some users might already have these permissions enabled.
        * We then [follow these steps](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/generate-a-static-outbound-ip-address-using-a-lambda-function-amazon-vpc-and-a-serverless-architecture.html) to create elastic ip/ips for the lambda function and add a vpc to our function. We note down the elastic ips.
        * We go to the mongo console>click on Organization Access>Access Manager>API Keys>click on ‘...’ of the API Key used above>Edit Permissions.
        * Click Next>Add Access List Entry>Enter the elastic ips noted above and save>Done.
        * The lambda function should be working now in sending logs to Sumo. You can check the cloudwatch logs in Monitor>Logs to see the logs of the function.