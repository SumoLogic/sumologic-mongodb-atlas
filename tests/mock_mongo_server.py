from flask import Flask, jsonify, request
import random
from datetime import datetime

app = Flask(__name__)


def generate_dummy_data():
    return {
        "cpu_usage": random.uniform(0, 100),
        "memory_usage": random.uniform(0, 100),
        "disk_usage": random.uniform(0, 100),
        "connections": random.randint(0, 1000),
        "operations": random.randint(0, 10000),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.route("/api/atlas/v1.0/groups/<group_id>/processes", methods=["GET"])
def get_processes(group_id):
    processes = [
        {
            "id": f"process-{i}",
            "hostname": f"host-{i}.example.com",
            "userAlias": f"cluster-{i}",
            "port": 27017,
            "typeName": "REPLICA_PRIMARY",
        }
        for i in range(1, 4)
    ]
    return jsonify({"results": processes})


@app.route(
    "/api/atlas/v1.0/groups/<group_id>/processes/<process_id>/databases",
    methods=["GET"],
)
def get_databases(group_id, process_id):
    databases = [{"databaseName": f"db-{i}"} for i in range(1, 4)]
    return jsonify({"results": databases})


@app.route(
    "/api/atlas/v1.0/groups/<group_id>/processes/<process_id>/disks", methods=["GET"]
)
def get_disks(group_id, process_id):
    disks = [{"partitionName": f"disk-{i}"} for i in range(1, 3)]
    return jsonify({"results": disks})


@app.route(
    "/api/atlas/v1.0/groups/<group_id>/processes/<process_id>/measurements",
    methods=["GET"],
)
def get_measurements(group_id, process_id):
    start = request.args.get("start", type=int)
    end = request.args.get("end", type=int)
    granularity = request.args.get("granularity", type=str)

    measurements = [generate_dummy_data() for _ in range(10)]
    return jsonify({"measurements": measurements})


if __name__ == "__main__":
    app.run(port=8247)
