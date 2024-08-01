import pytest
import yaml
import tempfile
import os
from unittest.mock import patch, MagicMock, call, PropertyMock
from main import MongoDBAtlasCollector
from sumoappclient.sumoclient.base import BaseCollector
from sumoappclient.provider.factory import ProviderFactory
from requests.auth import HTTPDigestAuth


@pytest.fixture
def mock_config():
    return {
        "MongoDBAtlas": {
            "PUBLIC_API_KEY": "test_public_key",
            "PRIVATE_API_KEY": "test_private_key",
            "BASE_URL": "https://cloud.mongodb.com/api/atlas/v1.0",
            "PROJECT_ID": "test_project_id",
            "PAGINATION_LIMIT": 100,
        },
        "Collection": {
            "MAX_RETRY": 3,
            "BACKOFF_FACTOR": 0.3,
            "DBNAME": "test_db",
            "NUM_WORKERS": 2,
            "TIMEOUT": 30,
            "Clusters": [
                "cluster1-shard-00-00.abc123.mongodb.net",
                "cluster2-shard-00-00.xyz789.mongodb.net",
            ],
            "DATA_REFRESH_TIME": 3600000,
        },
        "Logging": {
            "LOG_LEVEL": "DEBUG",
        },
    }


@pytest.fixture
def temp_config_dir(mock_config):
    with tempfile.TemporaryDirectory() as temp_dir:
        config_file_path = os.path.join(temp_dir, "mongodbatlas.yaml")
        with open(config_file_path, "w") as config_file:
            yaml.dump(mock_config, config_file)
        yield temp_dir


@pytest.fixture
def mock_provider(mock_config):
    mock_provider = MagicMock()
    mock_config_instance = MagicMock()
    mock_config_instance.get_config.return_value = mock_config
    mock_provider.get_config.return_value = mock_config_instance
    mock_provider.get_storage.return_value = MagicMock()
    return mock_provider


@pytest.fixture
def mongodb_atlas_collector(mock_config, mock_provider, temp_config_dir):
    def mock_base_init(self, project_dir):
        self.config = mock_config
        self.project_dir = project_dir
        self.kvstore = MagicMock()

    with patch(
        "sumoappclient.provider.factory.ProviderFactory.get_provider",
        return_value=mock_provider,
    ), patch("os.path.dirname", return_value=temp_config_dir), patch.object(
        BaseCollector, "__init__", mock_base_init
    ), patch.object(MongoDBAtlasCollector, "__init__", return_value=None):
        collector = MongoDBAtlasCollector()
        BaseCollector.__init__(
            collector, temp_config_dir
        )  # Call mocked BaseCollector.__init__

        # Manually set attributes specific to MongoDBAtlasCollector
        collector.api_config = collector.config["MongoDBAtlas"]
        collector.digestauth = HTTPDigestAuth(
            username=collector.api_config["PUBLIC_API_KEY"],
            password=collector.api_config["PRIVATE_API_KEY"],
        )
        collector.collection_config = collector.config["Collection"]
        collector.mongosess = MagicMock()
        collector.log = MagicMock()
        return collector


def test_mongodb_atlas_collector_init(
    mongodb_atlas_collector, mock_config, temp_config_dir
):
    config_file_path = os.path.join(temp_config_dir, "mongodbatlas.yaml")
    assert os.path.exists(config_file_path)
    assert mongodb_atlas_collector.config == mock_config
    assert mongodb_atlas_collector.project_dir == temp_config_dir
    assert mongodb_atlas_collector.api_config == mock_config["MongoDBAtlas"]
    assert isinstance(mongodb_atlas_collector.digestauth, HTTPDigestAuth)
    assert (
        mongodb_atlas_collector.digestauth.username
        == mock_config["MongoDBAtlas"]["PUBLIC_API_KEY"]
    )
    assert (
        mongodb_atlas_collector.digestauth.password
        == mock_config["MongoDBAtlas"]["PRIVATE_API_KEY"]
    )
    assert hasattr(mongodb_atlas_collector, "mongosess")


def test_get_current_dir(mongodb_atlas_collector):
    expected_dir = os.path.dirname(os.path.abspath(__file__))
    assert mongodb_atlas_collector.get_current_dir() == expected_dir


def test_get_cluster_name(mongodb_atlas_collector):
    assert (
        mongodb_atlas_collector._get_cluster_name("cluster1-shard-00-01") == "cluster1"
    )
    assert (
        mongodb_atlas_collector._get_cluster_name("cluster2-shard-00-02") == "cluster2"
    )


def test_get_user_provided_cluster_name(mongodb_atlas_collector):
    assert mongodb_atlas_collector._get_user_provided_cluster_name() == [
        "cluster1-shard-00-00.abc123.mongodb.net",
        "cluster2-shard-00-00.xyz789.mongodb.net",
    ]

    mongodb_atlas_collector.collection_config.pop("Clusters")
    assert mongodb_atlas_collector._get_user_provided_cluster_name() == []


@pytest.mark.skip()
def test_getpaginateddata(mongodb_atlas_collector):
    url = "https://test.com/api"
    kwargs = {"auth": mongodb_atlas_collector.digestauth, "params": {"pageNum": 1}}

    with patch("main.ClientMixin.make_request") as mock_make_request:
        mock_make_request.side_effect = [
            (True, {"results": [{"id": 1}, {"id": 2}]}),
            (True, {"results": [{"id": 3}]}),
            (True, {"results": []}),
        ]

        result = mongodb_atlas_collector.getpaginateddata(url, **kwargs)

        assert len(result) == 2
        assert result[0]["results"] == [{"id": 1}, {"id": 2}]
        assert result[1]["results"] == [{"id": 3}]

        assert mock_make_request.call_count == 3
        mock_make_request.assert_has_calls(
            [
                call(
                    url,
                    method="get",
                    session=mongodb_atlas_collector.mongosess,
                    logger=mongodb_atlas_collector.log,
                    TIMEOUT=30,
                    MAX_RETRY=3,
                    BACKOFF_FACTOR=0.3,
                    auth=mongodb_atlas_collector.digestauth,
                    params={"pageNum": 1},
                ),
                call(
                    url,
                    method="get",
                    session=mongodb_atlas_collector.mongosess,
                    logger=mongodb_atlas_collector.log,
                    TIMEOUT=30,
                    MAX_RETRY=3,
                    BACKOFF_FACTOR=0.3,
                    auth=mongodb_atlas_collector.digestauth,
                    params={"pageNum": 2},
                ),
                call(
                    url,
                    method="get",
                    session=mongodb_atlas_collector.mongosess,
                    logger=mongodb_atlas_collector.log,
                    TIMEOUT=30,
                    MAX_RETRY=3,
                    BACKOFF_FACTOR=0.3,
                    auth=mongodb_atlas_collector.digestauth,
                    params={"pageNum": 3},
                ),
            ]
        )


@patch("main.MongoDBAtlasCollector.getpaginateddata")
def test_get_all_processes_from_project(mock_getpaginateddata, mongodb_atlas_collector):
    mock_data = [
        {
            "results": [
                {
                    "id": "process1",
                    "hostname": "cluster1-shard-00-00.abc123.mongodb.net",
                    "userAlias": "Cluster1-shard-00-00",
                },
                {
                    "id": "process2",
                    "hostname": "cluster2-shard-00-00.xyz789.mongodb.net",
                    "userAlias": "Cluster2-shard-00-00",
                },
            ]
        }
    ]
    mock_getpaginateddata.return_value = mock_data

    process_ids, hostnames, cluster_mapping = (
        mongodb_atlas_collector._get_all_processes_from_project()
    )

    assert process_ids == ["process1", "process2"]
    assert set(hostnames) == {
        "cluster1-shard-00-00.abc123.mongodb.net",
        "cluster2-shard-00-00.xyz789.mongodb.net",
    }
    assert cluster_mapping == {"cluster1": "Cluster1", "cluster2": "Cluster2"}

    expected_url = f"{mongodb_atlas_collector.api_config['BASE_URL']}/groups/{mongodb_atlas_collector.api_config['PROJECT_ID']}/processes"
    expected_kwargs = {
        "auth": mongodb_atlas_collector.digestauth,
        "params": {
            "itemsPerPage": mongodb_atlas_collector.api_config["PAGINATION_LIMIT"]
        },
    }
    mock_getpaginateddata.assert_called_once_with(expected_url, **expected_kwargs)


@patch("main.MongoDBAtlasCollector.getpaginateddata")
def test_get_all_processes_from_project_with_user_provided_clusters(
    mock_getpaginateddata, mongodb_atlas_collector
):
    mock_data = [
        {
            "results": [
                {
                    "id": "process1",
                    "hostname": "cluster1-shard-00-00.abc123.mongodb.net",
                    "userAlias": "Cluster1-shard-00-00",
                },
                {
                    "id": "process2",
                    "hostname": "cluster2-shard-00-00.xyz789.mongodb.net",
                    "userAlias": "Cluster2-shard-00-00",
                },
                {
                    "id": "process3",
                    "hostname": "cluster3-shard-00-00.def456.mongodb.net",
                    "userAlias": "Cluster3-shard-00-00",
                },
            ]
        }
    ]
    mock_getpaginateddata.return_value = mock_data

    process_ids, hostnames, cluster_mapping = (
        mongodb_atlas_collector._get_all_processes_from_project()
    )

    assert process_ids == ["process1", "process2", "process3"]
    assert set(hostnames) == {
        "cluster1-shard-00-00.abc123.mongodb.net",
        "cluster2-shard-00-00.xyz789.mongodb.net",
        "cluster3-shard-00-00.def456.mongodb.net",
    }
    assert cluster_mapping == {"cluster1": "Cluster1", "cluster2": "Cluster2"}

    expected_url = f"{mongodb_atlas_collector.api_config['BASE_URL']}/groups/{mongodb_atlas_collector.api_config['PROJECT_ID']}/processes"
    expected_kwargs = {
        "auth": mongodb_atlas_collector.digestauth,
        "params": {
            "itemsPerPage": mongodb_atlas_collector.api_config["PAGINATION_LIMIT"]
        },
    }
    mock_getpaginateddata.assert_called_once_with(expected_url, **expected_kwargs)


@patch("main.MongoDBAtlasCollector.getpaginateddata")
def test_get_all_disks_from_host(mock_getpaginateddata, mongodb_atlas_collector):
    mock_data = [
        {
            "results": [
                {"partitionName": "disk1"},
                {"partitionName": "disk2"},
            ]
        },
        {
            "results": [
                {"partitionName": "disk2"},
                {"partitionName": "disk3"},
            ]
        },
    ]
    mock_getpaginateddata.return_value = mock_data

    process_ids = ["process1", "process2"]
    disks = mongodb_atlas_collector._get_all_disks_from_host(process_ids)

    assert set(disks) == {"disk1", "disk2", "disk3"}

    expected_calls = [
        call(
            f"{mongodb_atlas_collector.api_config['BASE_URL']}/groups/{mongodb_atlas_collector.api_config['PROJECT_ID']}/processes/{process_id}/disks",
            auth=mongodb_atlas_collector.digestauth,
            params={
                "itemsPerPage": mongodb_atlas_collector.api_config["PAGINATION_LIMIT"]
            },
        )
        for process_id in process_ids
    ]
    mock_getpaginateddata.assert_has_calls(expected_calls)


@patch("main.MongoDBAtlasCollector._get_all_databases")
@patch("main.get_current_timestamp")
def test_set_database_names(
    mock_get_current_timestamp, mock_get_all_databases, mongodb_atlas_collector
):
    mock_get_all_databases.return_value = ["db1", "db2", "db3"]
    mock_get_current_timestamp.return_value = 1234567890

    process_ids = ["process1", "process2"]
    mongodb_atlas_collector._set_database_names(process_ids)

    mock_get_all_databases.assert_called_once_with(process_ids)
    mock_get_current_timestamp.assert_called_once_with(milliseconds=True)

    mongodb_atlas_collector.kvstore.set.assert_called_once_with(
        "database_names",
        {
            "last_set_date": 1234567890,
            "values": ["db1", "db2", "db3"],
        },
    )


@pytest.fixture
def mock_get_current_timestamp():
    with patch("main.get_current_timestamp") as mock:
        mock.return_value = 1627776000000  # Example timestamp
        yield mock


def test_set_processes(mongodb_atlas_collector, mock_get_current_timestamp):
    mongodb_atlas_collector._get_all_processes_from_project = MagicMock(
        return_value=(
            ["process1", "process2"],
            ["host1", "host2"],
            {"cluster1": ["process1"], "cluster2": ["process2"]},
        )
    )

    mongodb_atlas_collector._set_processes()

    mongodb_atlas_collector.kvstore.set.assert_has_calls(
        [
            call(
                "processes",
                {
                    "last_set_date": 1627776000000,
                    "process_ids": ["process1", "process2"],
                    "hostnames": ["host1", "host2"],
                },
            ),
            call(
                "cluster_mapping",
                {
                    "last_set_date": 1627776000000,
                    "values": {"cluster1": ["process1"], "cluster2": ["process2"]},
                },
            ),
        ],
        any_order=True,
    )


def test_set_disk_names(mongodb_atlas_collector, mock_get_current_timestamp):
    # Mock the _get_all_disks_from_host method
    mongodb_atlas_collector._get_all_disks_from_host = MagicMock(
        return_value={"process1": ["disk1", "disk2"], "process2": ["disk3", "disk4"]}
    )

    # Call the method
    process_ids = ["process1", "process2"]
    mongodb_atlas_collector._set_disk_names(process_ids)

    # Assert that kvstore.set was called with the correct arguments
    mongodb_atlas_collector.kvstore.set.assert_called_once_with(
        "disk_names",
        {
            "last_set_date": 1627776000000,
            "values": {"process1": ["disk1", "disk2"], "process2": ["disk3", "disk4"]},
        },
    )


def test_set_processes_empty_results(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    mongodb_atlas_collector._get_all_processes_from_project = MagicMock(
        return_value=([], [], {})
    )
    mongodb_atlas_collector._set_processes()
    mongodb_atlas_collector.kvstore.set.assert_has_calls(
        [
            call(
                "processes",
                {"last_set_date": 1627776000000, "process_ids": [], "hostnames": []},
            ),
            call("cluster_mapping", {"last_set_date": 1627776000000, "values": {}}),
        ],
        any_order=True,
    )


def test_set_processes_large_number(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    large_process_ids = [f"process{i}" for i in range(1000)]
    large_hostnames = [f"host{i}" for i in range(1000)]
    large_cluster_mapping = {f"cluster{i}": [f"process{i}"] for i in range(1000)}
    mongodb_atlas_collector._get_all_processes_from_project = MagicMock(
        return_value=(large_process_ids, large_hostnames, large_cluster_mapping)
    )
    mongodb_atlas_collector._set_processes()
    mongodb_atlas_collector.kvstore.set.assert_has_calls(
        [
            call(
                "processes",
                {
                    "last_set_date": 1627776000000,
                    "process_ids": large_process_ids,
                    "hostnames": large_hostnames,
                },
            ),
            call(
                "cluster_mapping",
                {"last_set_date": 1627776000000, "values": large_cluster_mapping},
            ),
        ],
        any_order=True,
    )


def test_set_processes_exception(mongodb_atlas_collector, mock_get_current_timestamp):
    mongodb_atlas_collector._get_all_processes_from_project = MagicMock(
        side_effect=Exception("API Error")
    )
    with pytest.raises(Exception):
        mongodb_atlas_collector._set_processes()
    assert not mongodb_atlas_collector.kvstore.set.called


def test_set_disk_names_empty_results(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    mongodb_atlas_collector._get_all_disks_from_host = MagicMock(return_value={})
    mongodb_atlas_collector._set_disk_names([])
    mongodb_atlas_collector.kvstore.set.assert_called_once_with(
        "disk_names", {"last_set_date": 1627776000000, "values": {}}
    )


def test_set_disk_names_some_empty(mongodb_atlas_collector, mock_get_current_timestamp):
    mongodb_atlas_collector._get_all_disks_from_host = MagicMock(
        return_value={
            "process1": ["disk1", "disk2"],
            "process2": [],
            "process3": ["disk3"],
        }
    )
    mongodb_atlas_collector._set_disk_names(["process1", "process2", "process3"])
    mongodb_atlas_collector.kvstore.set.assert_called_once_with(
        "disk_names",
        {
            "last_set_date": 1627776000000,
            "values": {
                "process1": ["disk1", "disk2"],
                "process2": [],
                "process3": ["disk3"],
            },
        },
    )


def test_set_disk_names_large_number(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    large_disks = {f"process{i}": [f"disk{j}" for j in range(100)] for i in range(100)}
    mongodb_atlas_collector._get_all_disks_from_host = MagicMock(
        return_value=large_disks
    )
    mongodb_atlas_collector._set_disk_names([f"process{i}" for i in range(100)])
    mongodb_atlas_collector.kvstore.set.assert_called_once_with(
        "disk_names", {"last_set_date": 1627776000000, "values": large_disks}
    )


def test_set_disk_names_exception(mongodb_atlas_collector, mock_get_current_timestamp):
    mongodb_atlas_collector._get_all_disks_from_host = MagicMock(
        side_effect=Exception("API Error")
    )
    with pytest.raises(Exception):
        mongodb_atlas_collector._set_disk_names(["process1", "process2"])
    assert not mongodb_atlas_collector.kvstore.set.called


def test_get_database_names_initial_fetch(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    mongodb_atlas_collector.kvstore.has_key = MagicMock(return_value=False)
    mongodb_atlas_collector._get_process_names = MagicMock(
        return_value=(["process1", "process2"], None)
    )
    mongodb_atlas_collector._set_database_names = MagicMock()
    mongodb_atlas_collector.kvstore.get = MagicMock(
        return_value={"last_set_date": 1627776000000, "values": ["db1", "db2"]}
    )

    # Execute
    result = mongodb_atlas_collector._get_database_names()

    # Assert
    assert result == ["db1", "db2"]
    mongodb_atlas_collector._get_process_names.assert_called_once()
    mongodb_atlas_collector._set_database_names.assert_called_once_with(
        ["process1", "process2"]
    )
    mongodb_atlas_collector.kvstore.get.assert_called_with("database_names")


def test_get_database_names_refresh(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    # Setup
    mongodb_atlas_collector.kvstore.has_key = MagicMock(return_value=True)
    mongodb_atlas_collector._get_process_names = MagicMock(
        return_value=(["process1", "process2"], None)
    )
    mongodb_atlas_collector._set_database_names = MagicMock()
    mongodb_atlas_collector.kvstore.get = MagicMock(
        side_effect=[
            {"last_set_date": 1627772400000, "values": []},  # Old data
            {"last_set_date": 1627776000000, "values": ["db1", "db2"]},  # New data
        ]
    )
    mongodb_atlas_collector.DATA_REFRESH_TIME = 3600000  # 1 hour

    # Execute
    result = mongodb_atlas_collector._get_database_names()

    # Assert
    assert result == ["db1", "db2"]
    assert mongodb_atlas_collector._get_process_names.call_count == 1
    assert mongodb_atlas_collector._set_database_names.call_count == 1
    assert mongodb_atlas_collector.kvstore.get.call_count == 2


def test_get_disk_names_initial_fetch(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    mongodb_atlas_collector.kvstore.has_key = MagicMock(return_value=False)
    mongodb_atlas_collector._get_process_names = MagicMock(
        return_value=(["process1", "process2"], None)
    )
    mongodb_atlas_collector._set_disk_names = MagicMock()
    mongodb_atlas_collector.kvstore.get = MagicMock(
        return_value={
            "last_set_date": 1627776000000,
            "values": {"process1": ["disk1", "disk2"], "process2": ["disk3"]},
        }
    )

    # Execute
    result = mongodb_atlas_collector._get_disk_names()

    # Assert
    assert result == {"process1": ["disk1", "disk2"], "process2": ["disk3"]}
    mongodb_atlas_collector._get_process_names.assert_called_once()
    mongodb_atlas_collector._set_disk_names.assert_called_once_with(
        ["process1", "process2"]
    )
    mongodb_atlas_collector.kvstore.get.assert_called_with("disk_names")


def test_get_disk_names_refresh(mongodb_atlas_collector, mock_get_current_timestamp):
    # Setup
    mongodb_atlas_collector.kvstore.has_key = MagicMock(return_value=True)
    mongodb_atlas_collector._get_process_names = MagicMock(
        return_value=(["process1", "process2"], None)
    )
    mongodb_atlas_collector._set_disk_names = MagicMock()
    mongodb_atlas_collector.kvstore.get = MagicMock(
        side_effect=[
            {"last_set_date": 1627772400000, "values": {}},  # Old data
            {
                "last_set_date": 1627776000000,
                "values": {"process1": ["disk1", "disk2"], "process2": ["disk3"]},
            },  # New data
        ]
    )
    mongodb_atlas_collector.DATA_REFRESH_TIME = 3600000  # 1 hour

    # Execute
    result = mongodb_atlas_collector._get_disk_names()

    # Assert
    assert result == {"process1": ["disk1", "disk2"], "process2": ["disk3"]}
    assert mongodb_atlas_collector._get_process_names.call_count == 1
    assert mongodb_atlas_collector._set_disk_names.call_count == 1
    assert mongodb_atlas_collector.kvstore.get.call_count == 2


def test_get_database_names_no_refresh_needed(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    # Setup
    mongodb_atlas_collector.kvstore.has_key = MagicMock(return_value=True)
    mongodb_atlas_collector.kvstore.get = MagicMock(
        return_value={
            "last_set_date": 1627775000000,  # 1000 seconds ago
            "values": ["db1", "db2"],
        }
    )
    mongodb_atlas_collector.DATA_REFRESH_TIME = 3600000  # 1 hour
    mongodb_atlas_collector._get_process_names = MagicMock()
    mongodb_atlas_collector._set_database_names = MagicMock()

    # Execute
    result = mongodb_atlas_collector._get_database_names()

    # Assert
    assert result == ["db1", "db2"]
    mongodb_atlas_collector._get_process_names.assert_not_called()
    mongodb_atlas_collector._set_database_names.assert_not_called()
    assert mongodb_atlas_collector.kvstore.get.call_count == 2
    mongodb_atlas_collector.kvstore.get.assert_has_calls(
        [call("database_names"), call("database_names")]
    )


def test_get_disk_names_no_refresh_needed(
    mongodb_atlas_collector, mock_get_current_timestamp
):
    # Setup
    mongodb_atlas_collector.kvstore.has_key = MagicMock(return_value=True)
    mongodb_atlas_collector.kvstore.get = MagicMock(
        return_value={
            "last_set_date": 1627775000000,  # 1000 seconds ago
            "values": {"process1": ["disk1", "disk2"], "process2": ["disk3"]},
        }
    )
    mongodb_atlas_collector.DATA_REFRESH_TIME = 3600000  # 1 hour
    mongodb_atlas_collector._get_process_names = MagicMock()
    mongodb_atlas_collector._set_disk_names = MagicMock()

    # Execute
    result = mongodb_atlas_collector._get_disk_names()

    # Assert
    assert result == {"process1": ["disk1", "disk2"], "process2": ["disk3"]}
    mongodb_atlas_collector._get_process_names.assert_not_called()
    mongodb_atlas_collector._set_disk_names.assert_not_called()
    assert mongodb_atlas_collector.kvstore.get.call_count == 2
    mongodb_atlas_collector.kvstore.get.assert_has_calls(
        [call("disk_names"), call("disk_names")]
    )
