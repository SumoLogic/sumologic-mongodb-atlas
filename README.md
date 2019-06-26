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
         LOGS_SUMO_ENDPOINT: <Paste the URL for the HTTP Logs source from step 2.>
         METRICS_SUMO_ENDPOINT: <Paste the URL for the HTTP Metrics source from step 2.>

        MongoDBAtlas:
         ORGANIZATION_ID: Paste the Organization ID from step 1.
         PROJECT_ID: Paste the Project ID from step 1.
         PRIVATE_KEY: Paste the Private Key from step 1.
         PUBLIC_KEY: Paste the Public Key from step 1.
    ```
    * Create a cron job  for running the collector every 5 minutes by using the crontab -e and adding the below line

        `*/5 * * * *  /usr/bin/python -m sumogsuitealertscollector.main > /dev/null 2>&1`

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

