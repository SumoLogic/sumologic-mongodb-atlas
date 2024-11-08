import json
from datetime import datetime, timedelta
import random


def process_metric_mock():
    current_time = datetime.utcnow()
    end_time = current_time.replace(second=0, microsecond=0)
    start_time = end_time - timedelta(minutes=5)

    def generate_datapoints(start_value, end_value):
        datapoints = []
        for i in range(6):
            timestamp = start_time + timedelta(minutes=i)
            value = start_value + (end_value - start_value) * i / 5
            value += random.uniform(-value * 0.1, value * 0.1)
            datapoints.append(
                {
                    "timestamp": timestamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "value": round(value, 2),
                }
            )
        return datapoints

    mock_response = {
        "databaseName": "myDatabase",
        "end": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "granularity": "PT1M",
        "groupId": "32b6e34b3d91647abb20e7b8",
        "hostId": "cluster0-shard-00-00.mongodb.net:27017",
        "links": [
            {
                "href": "https://cloud.mongodb.com/api/atlas/v1.0/groups/32b6e34b3d91647abb20e7b8/processes/cluster0-shard-00-00.mongodb.net:27017/measurements",
                "rel": "self",
            }
        ],
        "measurements": [
            {
                "dataPoints": generate_datapoints(1024, 3072),
                "name": "CACHE_BYTES_READ_INTO",
                "units": "BYTES",
            },
            {
                "dataPoints": generate_datapoints(50, 65),
                "name": "CONNECTIONS",
                "units": "SCALAR",
            },
        ],
        "partitionName": "P0",
        "processId": "cluster0-shard-00-00.mongodb.net:27017",
        "start": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    return json.dumps(mock_response, indent=2)


# print(get_mock_mongodb_metrics())
