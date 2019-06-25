# sumologic-mongodb-atlas

Solution to pull alerts from Mongo DB Atlas to Sumo Logic


## Installation

This collector can be deployed both onprem and on cloud.
 

### Deploying the collector on a VM
 
1. Setup the Alert Center API by referring to the following [docs](https://developers.google.com/admin-sdk/alertcenter/guides/prerequisites). Here while creating key in service account make a note of the location of Service Account JSON file that has been downloaded in your computer you will need it later.

2. Add a Hosted Collector and one HTTP Logs and Metrics Source

    * To create a new Sumo Logic Hosted Collector, perform the steps in [Configure a Hosted Collector](https://help.sumologic.com/03Send-Data/Hosted-Collectors/Configure-a-Hosted-Collector).
    * Add an [HTTP Logs and Metrics Source](https://help.sumologic.com/03Send-Data/Sources/02Sources-for-Hosted-Collectors/HTTP-Source). Under Advanced you'll see options regarding timestamps and time zones and when you select Timestamp parsing specify the custom time stamp format as shown below: 
      - Format: `yyyy-MM-dd'T'HH:mm:ss.SSS'Z'` 
      - Timestamp locator: `\"created\": (.*),`.
    * Add another HTTP Source this time for metric
    
3. Configuring the **sumologic-mongodbatlas** collector
    
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


