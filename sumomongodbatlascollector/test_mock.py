import gzip
import json
import pytest
import time
from unittest.mock import Mock, patch

from sumoappclient.sumoclient.api import (
    AlertsAPI,
    DatabaseMetricsAPI,
    DiskMetricsAPI,
    FetchMixin,
    LogAPI,
    OrgEventsAPI,
    PaginatedFetchMixin,
    ProcessMetricsAPI,
    ProjectEventsAPI,
)
from sumoappclient.sumoclient.main import MongoDBAtlasCollector


@patch("sumoappclient.sumoclient.base.BaseAPI")
def test_mongodb_api(mock_base_api):
    mock_config = {
        "MongoDBAtlas": {
            "PUBLIC_API_KEY": "test_public_key",
            "PRIVATE_API_KEY": "test_private_key",
        }
    }

    api = MongoDBAtlasCollector(Mock(), mock_config)

    start_time, end_time = api.get_window(1000000)
    assert isinstance(start_time, float)
    assert isinstance(end_time, float)

    assert api._get_cluster_name("test-cluster-shard-0") == "test-cluster"
    assert (
        api._replace_cluster_name("test-cluster-shard-0", {"test-cluster": "alias"})
        == "alias-shard-0"
    )


@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_fetch_mixin(mock_client_mixin, mock_output_handler_factory):
    mock_output_handler = Mock()
    mock_output_handler_factory.get_handler.return_value = mock_output_handler

    mock_client_mixin.make_request.return_value = (True, [{"data": "test"}])

    fetch_mixin = FetchMixin(Mock(), {"MongoDBAtlas": {}})

    fetch_mixin.build_fetch_params = Mock(return_value=("http://test.com", {}))
    fetch_mixin.transform_data = Mock(
        return_value=([{"transformed": "data"}], {"state": "updated"})
    )
    fetch_mixin.build_send_params = Mock(return_value={})
    fetch_mixin.save_state = Mock()

    fetch_mixin.fetch()

    fetch_mixin.build_fetch_params.assert_called_once()
    mock_client_mixin.make_request.assert_called_once()
    fetch_mixin.transform_data.assert_called_once()
    mock_output_handler.send.assert_called_once()
    fetch_mixin.save_state.assert_called_once()


@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_paginated_fetch_mixin(mock_client_mixin, mock_output_handler_factory):
    mock_output_handler = Mock()
    mock_output_handler_factory.get_handler.return_value = mock_output_handler

    mock_session = Mock()
    mock_client_mixin.get_new_session.return_value = mock_session
    mock_client_mixin.make_request.side_effect = [
        (True, {"results": [{"data": "page1"}]}),
        (True, {"results": [{"data": "page2"}]}),
        (True, {"results": []}),  # No more results
    ]

    paginated_fetch_mixin = PaginatedFetchMixin(Mock(), {"MongoDBAtlas": {}})

    paginated_fetch_mixin.get_state = Mock(return_value={"last_time_epoch": 1000000})
    paginated_fetch_mixin.build_fetch_params = Mock(
        return_value=(
            "http://test.com",
            {
                "params": {
                    "pageNum": 1,
                    "minDate": "2023-01-01",
                    "maxDate": "2023-01-02",
                }
            },
        )
    )
    paginated_fetch_mixin.transform_data = Mock(
        return_value=([{"transformed": "data"}], {"state": "updated"})
    )
    paginated_fetch_mixin.build_send_params = Mock(return_value={})
    paginated_fetch_mixin.save_state = Mock()
    paginated_fetch_mixin.is_time_remaining = Mock(side_effect=[True, True, False])

    paginated_fetch_mixin.fetch()

    assert mock_client_mixin.make_request.call_count == 3
    assert paginated_fetch_mixin.transform_data.call_count == 2
    assert mock_output_handler.send.call_count == 2
    assert paginated_fetch_mixin.save_state.call_count == 1


@patch("sumoappclient.sumoclient.base.BaseAPI")
@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_log_api(mock_client_mixin, mock_output_handler_factory, mock_base_api):
    mock_kvstore = Mock()
    mock_config = {
        "MongoDBAtlas": {
            "PROJECT_ID": "test_project",
            "BASE_URL": "http://localhost:8247",
        }
    }
    mock_cluster_mapping = {"test-cluster": "alias"}

    log_api = LogAPI(
        mock_kvstore, "test-hostname", "mongodb.log", mock_config, mock_cluster_mapping
    )

    assert log_api.get_key() == "test_project-test-hostname-mongodb.log"

    log_api.save_state(1000000)
    mock_kvstore.set.assert_called_with(
        "test_project-test-hostname-mongodb.log", {"last_time_epoch": 1000000}
    )

    mock_kvstore.has_key.return_value = False
    log_api.get_state()
    mock_kvstore.set.assert_called_with(
        "test_project-test-hostname-mongodb.log",
        {"last_time_epoch": log_api.DEFAULT_START_TIME_EPOCH},
    )

    log_api.get_window = Mock(return_value=(1000000, 2000000))
    url, params = log_api.build_fetch_params()
    assert (
        url
        == "http://localhost:8247/groups/test_project/clusters/test-hostname/logs/mongodb.log"
    )
    assert params["params"] == {"startDate": 1000000, "endDate": 2000000}

    send_params = log_api.build_send_params()
    assert send_params == {
        "extra_headers": {"X-Sumo-Name": "mongodb.log"},
        "endpoint_key": "HTTP_LOGS_ENDPOINT",
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.get_current_timestamp",
        return_value=1600000,
    ):
        result, state = log_api.check_move_fetch_window(
            {"params": {"endDate": 1500000}}
        )
        assert result == True
        assert state == {"last_time_epoch": 1500000}

    sample_log = {"t": {"$date": "2023-07-26T12:00:00.000Z"}, "msg": "Test log message"}
    gzip_content = gzip.compress(json.dumps(sample_log).encode("utf-8"))

    transformed_data, state = log_api.transform_data(gzip_content)

    assert len(transformed_data) == 1
    assert transformed_data[0]["project_id"] == "test_project"
    assert transformed_data[0]["hostname"] == "alias-hostname"
    assert transformed_data[0]["cluster_name"] == "alias"
    assert "created" in transformed_data[0]
    assert "last_time_epoch" in state

    log_api.filename = "mongodb-audit-log.json"
    sample_audit_log = {
        "ts": {"$date": "2023-07-26T12:00:00.000Z"},
        "msg": "Test audit log message",
    }
    gzip_content = gzip.compress(json.dumps(sample_audit_log).encode("utf-8"))

    transformed_data, state = log_api.transform_data(gzip_content)

    assert len(transformed_data) == 1
    assert transformed_data[0]["project_id"] == "test_project"
    assert transformed_data[0]["hostname"] == "alias-hostname"
    assert transformed_data[0]["cluster_name"] == "alias"
    assert "created" in transformed_data[0]
    assert "last_time_epoch" in state


@patch("sumoappclient.sumoclient.base.BaseAPI")
@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_process_metrics_api(
    mock_client_mixin, mock_output_handler_factory, mock_base_api
):
    mock_kvstore = Mock()
    mock_config = {
        "MongoDBAtlas": {
            "PROJECT_ID": "test_project",
            "BASE_URL": "http://localhost:8247",
            "PAGINATION_LIMIT": 100,
            "METRIC_TYPES": {"PROCESS_METRICS": ["metric1", "metric2"]},
        }
    }
    mock_cluster_mapping = {"test-cluster": "alias"}

    process_metrics_api = ProcessMetricsAPI(
        mock_kvstore, "test-process-id", mock_config, mock_cluster_mapping
    )

    assert process_metrics_api.get_key() == "test_project-test-process-id"

    process_metrics_api.save_state(1000000)
    mock_kvstore.set.assert_called_with(
        "test_project-test-process-id", {"last_time_epoch": 1000000}
    )

    mock_kvstore.has_key.return_value = False
    process_metrics_api.get_state()
    mock_kvstore.set.assert_called_with(
        "test_project-test-process-id",
        {"last_time_epoch": process_metrics_api.DEFAULT_START_TIME_EPOCH},
    )

    with patch(
        "sumoappclient.sumoclient.mongodbapi.convert_epoch_to_utc_date",
        side_effect=["2023-07-26T00:00:00Z", "2023-07-26T01:00:00Z"],
    ):
        process_metrics_api.get_window = Mock(return_value=(1000000, 2000000))
        url, params = process_metrics_api.build_fetch_params()
        assert (
            url
            == "http://localhost:8247/groups/test_project/processes/test-process-id/measurements"
        )
        assert params["params"]["start"] == "2023-07-26T00:00:00Z"
        assert params["params"]["end"] == "2023-07-26T01:00:00Z"
        assert params["params"]["m"] == ["metric1", "metric2"]

    send_params = process_metrics_api.build_send_params()
    assert send_params == {
        "extra_headers": {"Content-Type": "application/vnd.sumologic.carbon2"},
        "endpoint_key": "HTTP_METRICS_ENDPOINT",
        "jsondump": False,
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.get_current_timestamp",
        return_value=1600000,
    ):
        with patch(
            "sumoappclient.sumoclient.mongodbapi.convert_utc_date_to_epoch",
            return_value=1500000,
        ):
            result, state = process_metrics_api.check_move_fetch_window(
                {"params": {"end": "2023-07-26T01:00:00Z"}}
            )
            assert result == True
            assert state == {"last_time_epoch": 1500000}

    sample_data = {
        "measurements": [
            {
                "name": "metric1",
                "units": "MB",
                "dataPoints": [
                    {"timestamp": "2023-07-26T00:00:00Z", "value": 100},
                    {"timestamp": "2023-07-26T00:01:00Z", "value": None},
                ],
            }
        ],
        "hostId": "test-cluster-host",
        "processId": "test-cluster-process",
        "groupId": "test_project",
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.convert_utc_date_to_epoch",
        return_value=1627257600,
    ):
        transformed_data, state = process_metrics_api.transform_data(sample_data)

    assert len(transformed_data) == 1
    assert "projectId=test_project" in transformed_data[0]
    assert "hostId=alias-host" in transformed_data[0]
    assert "processId=alias-process" in transformed_data[0]
    assert "metric=metric1" in transformed_data[0]
    assert "units=MB" in transformed_data[0]
    assert "cluster_name=alias" in transformed_data[0]
    assert "100 1627257600" in transformed_data[0]
    assert state == {"last_time_epoch": 1627257600}


@patch("sumoappclient.sumoclient.base.BaseAPI")
@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_disk_metrics_api(
    mock_client_mixin, mock_output_handler_factory, mock_base_api
):
    mock_kvstore = Mock()
    mock_config = {
        "MongoDBAtlas": {
            "PROJECT_ID": "test_project",
            "BASE_URL": "http://localhost:8247",
            "PAGINATION_LIMIT": 100,
            "METRIC_TYPES": {"DISK_METRICS": ["disk_metric1", "disk_metric2"]},
        }
    }
    mock_cluster_mapping = {"test-cluster": "alias"}

    disk_metrics_api = DiskMetricsAPI(
        mock_kvstore, "test-process-id", "test-disk", mock_config, mock_cluster_mapping
    )

    assert disk_metrics_api.get_key() == "test_project-test-process-id-test-disk"

    disk_metrics_api.save_state(1000000)
    mock_kvstore.set.assert_called_with(
        "test_project-test-process-id-test-disk", {"last_time_epoch": 1000000}
    )

    mock_kvstore.has_key.return_value = False
    disk_metrics_api.get_state()
    mock_kvstore.set.assert_called_with(
        "test_project-test-process-id-test-disk",
        {"last_time_epoch": disk_metrics_api.DEFAULT_START_TIME_EPOCH},
    )

    with patch(
        "sumoappclient.sumoclient.mongodbapi.convert_epoch_to_utc_date",
        side_effect=["2023-07-26T00:00:00.000Z", "2023-07-26T01:00:00.000Z"],
    ):
        disk_metrics_api.get_window = Mock(return_value=(1000000, 2000000))
        url, params = disk_metrics_api.build_fetch_params()
        assert (
            url
            == "http://localhost:4287/groups/test_project/processes/test-process-id/disks/test-disk/measurements"
        )
        assert params["params"]["start"] == "2023-07-26T00:00:00.000Z"
        assert params["params"]["end"] == "2023-07-26T01:00:00.000Z"
        assert params["params"]["m"] == ["disk_metric1", "disk_metric2"]

    send_params = disk_metrics_api.build_send_params()
    assert send_params == {
        "extra_headers": {"Content-Type": "application/vnd.sumologic.carbon2"},
        "endpoint_key": "HTTP_METRICS_ENDPOINT",
        "jsondump": False,
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.get_current_timestamp",
        return_value=1600000,
    ):
        with patch(
            "sumoappclient.sumoclient.mongodbapi.convert_utc_date_to_epoch",
            return_value=1500000,
        ):
            result, state = disk_metrics_api.check_move_fetch_window(
                {"params": {"end": "2023-07-26T01:00:00.000Z"}}
            )
            assert result == True
            assert state == {"last_time_epoch": 1500000}

    sample_data = {
        "measurements": [
            {
                "name": "disk_metric1",
                "units": "GB",
                "dataPoints": [
                    {"timestamp": "2023-07-26T00:00:00Z", "value": 50},
                    {"timestamp": "2023-07-26T00:01:00Z", "value": None},
                ],
            }
        ],
        "hostId": "test-cluster-host",
        "processId": "test-cluster-process",
        "groupId": "test_project",
        "partitionName": "test-partition",
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.convert_utc_date_to_epoch",
        return_value=1627257600,
    ):
        transformed_data, state = disk_metrics_api.transform_data(sample_data)

    assert len(transformed_data) == 1
    assert "projectId=test_project" in transformed_data[0]
    assert "partitionName=test-partition" in transformed_data[0]
    assert "hostId=alias-host" in transformed_data[0]
    assert "processId=alias-process" in transformed_data[0]
    assert "metric=disk_metric1" in transformed_data[0]
    assert "units=GB" in transformed_data[0]
    assert "cluster_name=alias" in transformed_data[0]
    assert "50 1627257600" in transformed_data[0]
    assert state == {"last_time_epoch": 1627257600}


@patch("sumoappclient.sumoclient.base.BaseAPI")
@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_database_metrics_api(
    mock_client_mixin, mock_output_handler_factory, mock_base_api
):
    mock_kvstore = Mock()
    mock_config = {
        "MongoDBAtlas": {
            "PROJECT_ID": "test_project",
            "BASE_URL": "http://localhost:8247",
            "PAGINATION_LIMIT": 100,
            "METRIC_TYPES": {"DATABASE_METRICS": ["db_metric1", "db_metric2"]},
        }
    }
    mock_cluster_mapping = {"test-cluster": "alias"}

    db_metrics_api = DatabaseMetricsAPI(
        mock_kvstore,
        "test-process-id",
        "test-database",
        mock_config,
        mock_cluster_mapping,
    )

    assert db_metrics_api.get_key() == "test_project-test-process-id-test-database"

    db_metrics_api.save_state(1000000)
    mock_kvstore.set.assert_called_with(
        "test_project-test-process-id-test-database", {"last_time_epoch": 1000000}
    )

    mock_kvstore.has_key.return_value = False
    db_metrics_api.get_state()
    mock_kvstore.set.assert_called_with(
        "test_project-test-process-id-test-database",
        {"last_time_epoch": db_metrics_api.DEFAULT_START_TIME_EPOCH},
    )

    with patch(
        "sumoappclient.sumoclient.mongodbapi.convert_epoch_to_utc_date",
        side_effect=["2023-07-26T00:00:00.000Z", "2023-07-26T01:00:00.000Z"],
    ):
        db_metrics_api.get_window = Mock(return_value=(1000000, 2000000))
        url, params = db_metrics_api.build_fetch_params()
        assert (
            url
            == "http://localhost:8247/groups/test_project/processes/test-process-id/databases/test-database/measurements"
        )
        assert params["params"]["start"] == "2023-07-26T00:00:00.000Z"
        assert params["params"]["end"] == "2023-07-26T01:00:00.000Z"
        assert params["params"]["m"] == ["db_metric1", "db_metric2"]

    send_params = db_metrics_api.build_send_params()
    assert send_params == {
        "extra_headers": {"Content-Type": "application/vnd.sumologic.carbon2"},
        "endpoint_key": "HTTP_METRICS_ENDPOINT",
        "jsondump": False,
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.get_current_timestamp",
        return_value=1600000,
    ):
        with patch(
            "sumoappclient.sumoclient.mongodbapi.convert_utc_date_to_epoch",
            return_value=1500000,
        ):
            result, state = db_metrics_api.check_move_fetch_window(
                {"params": {"end": "2023-07-26T01:00:00.000Z"}}
            )
            assert result == True
            assert state == {"last_time_epoch": 1500000}

    sample_data = {
        "measurements": [
            {
                "name": "db_metric1",
                "units": "MB",
                "dataPoints": [
                    {"timestamp": "2023-07-26T00:00:00Z", "value": 100},
                    {"timestamp": "2023-07-26T00:01:00Z", "value": None},
                ],
            }
        ],
        "hostId": "test-host",
        "processId": "test-cluster-process",
        "groupId": "test_project",
        "databaseName": "test-database",
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.convert_utc_date_to_epoch",
        return_value=1627257600,
    ):
        transformed_data, state = db_metrics_api.transform_data(sample_data)

    assert len(transformed_data) == 1
    assert "projectId=test_project" in transformed_data[0]
    assert "databaseName=test-database" in transformed_data[0]
    assert "hostId=test-host" in transformed_data[0]
    assert "processId=alias-process" in transformed_data[0]
    assert "metric=db_metric1" in transformed_data[0]
    assert "units=MB" in transformed_data[0]
    assert "cluster_name=alias" in transformed_data[0]
    assert "100 1627257600" in transformed_data[0]
    assert state == {"last_time_epoch": 1627257600}


@patch("sumoappclient.sumoclient.base.BaseAPI")
@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_project_events_api(
    mock_client_mixin, mock_output_handler_factory, mock_base_api
):
    mock_kvstore = Mock()
    mock_config = {
        "MongoDBAtlas": {
            "PROJECT_ID": "test_project",
            "BASE_URL": "http://localhost:8247",
            "PAGINATION_LIMIT": 100,
        }
    }

    project_events_api = ProjectEventsAPI(mock_kvstore, mock_config)

    assert project_events_api.get_key() == "test_project-projectevents"

    project_events_api.save_state({"last_time_epoch": 1000000, "page_num": 1})
    mock_kvstore.set.assert_called_with(
        "test_project-projectevents", {"last_time_epoch": 1000000, "page_num": 1}
    )

    mock_kvstore.has_key.return_value = False
    state = project_events_api.get_state()
    mock_kvstore.set.assert_called_with(
        "test_project-projectevents",
        {"last_time_epoch": project_events_api.DEFAULT_START_TIME_EPOCH, "page_num": 0},
    )

    with patch(
        "sumoappclient.sumoclient.mongodbapi.convert_epoch_to_utc_date",
        side_effect=["2023-07-26T00:00:00.000Z", "2023-07-26T01:00:00.000Z"],
    ):
        project_events_api.get_window = Mock(return_value=(1000000, 2000000))
        url, params = project_events_api.build_fetch_params()
        assert url == "http://localhost:8247/groups/test_project/events"
        assert params["params"]["minDate"] == "2023-07-26T00:00:00.000Z"
        assert params["params"]["maxDate"] == "2023-07-26T01:00:00.000Z"
        assert params["params"]["pageNum"] == 1

    send_params = project_events_api.build_send_params()
    assert send_params == {
        "extra_headers": {"X-Sumo-Name": "events"},
        "endpoint_key": "HTTP_LOGS_ENDPOINT",
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.get_current_timestamp",
        return_value=1600000,
    ):
        with patch(
            "sumoappclient.sumoclient.mongodbapi.convert_utc_date_to_epoch",
            return_value=1500000,
        ):
            result, state = project_events_api.check_move_fetch_window(
                {"params": {"maxDate": "2023-07-26T01:00:00.000Z"}}
            )
            assert result == True
            assert state == {"last_time_epoch": 1500000, "page_num": 0}

    sample_data = {
        "results": [
            {
                "created": "2023-07-26T00:00:00Z",
                "eventType": "TEST_EVENT",
                "id": "test-event-id",
            }
        ]
    }

    with patch(
        "sumoappclient.sumoclient.mongodbapi.convert_date_to_epoch",
        return_value=1627257600,
    ):
        transformed_data, state = project_events_api.transform_data(sample_data)

    assert len(transformed_data) == 1
    assert transformed_data[0]["eventType"] == "TEST_EVENT"
    assert transformed_data[0]["id"] == "test-event-id"
    assert state == {"last_time_epoch": 1627257600}


@pytest.mark.parametrize("num_records", [10000, 100000, 1000000])
@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_log_api_load(mock_client_mixin, mock_output_handler_factory, num_records):
    mock_kvstore = Mock()
    mock_config = {
        "MongoDBAtlas": {
            "PROJECT_ID": "test_project",
            "BASE_URL": "http://localhost:8247",
        }
    }
    mock_cluster_mapping = {"test-cluster": "alias"}

    log_api = LogAPI(
        mock_kvstore, "test-hostname", "mongodb.log", mock_config, mock_cluster_mapping
    )

    bulk_data = [
        {
            "t": {"$date": f"2023-07-26T12:00:{i:02d}.000Z"},
            "msg": f"Test log message {i}",
        }
        for i in range(num_records)
    ]

    mock_client_mixin.make_request.return_value = (True, bulk_data)

    start_time = time.time()
    log_api.fetch()
    end_time = time.time()

    execution_time = end_time - start_time

    print(f"Log API load test results for {num_records} records:")
    print(f"Execution time: {execution_time:.2f} seconds")

    assert (
        execution_time < 300
    ), f"Processing {num_records} log records took more than 5 minutes"


@pytest.mark.parametrize("num_records", [10000, 100000, 1000000])
@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_process_metrics_api_load(
    mock_client_mixin, mock_output_handler_factory, num_records
):
    mock_kvstore = Mock()
    mock_config = {
        "MongoDBAtlas": {
            "PROJECT_ID": "test_project",
            "BASE_URL": "http://localhost:8247",
            "PAGINATION_LIMIT": 100,
            "METRIC_TYPES": {"PROCESS_METRICS": ["metric1", "metric2"]},
        }
    }
    mock_cluster_mapping = {"test-cluster": "alias"}

    process_metrics_api = ProcessMetricsAPI(
        mock_kvstore, "test-process-id", mock_config, mock_cluster_mapping
    )

    bulk_data = {
        "measurements": [
            {
                "name": "metric1",
                "units": "MB",
                "dataPoints": [
                    {"timestamp": f"2023-07-26T{i//60:02d}:{i%60:02d}:00Z", "value": i}
                    for i in range(num_records)
                ],
            }
        ],
        "hostId": "test-cluster-host",
        "processId": "test-cluster-process",
        "groupId": "test_project",
    }

    mock_client_mixin.make_request.return_value = (True, bulk_data)

    start_time = time.time()
    process_metrics_api.fetch()
    end_time = time.time()

    execution_time = end_time - start_time
    print(f"Process Metrics API load test results for {num_records} records:")
    print(f"Execution time: {execution_time:.2f} seconds")

    # Modify the time range to verify assertion
    assert (
        execution_time < 300
    ), f"Processing {num_records} process metric records took more than 5 minutes"


@pytest.mark.parametrize("num_records", [10000, 100000, 1000000])
@patch("sumoappclient.sumoclient.factory.OutputHandlerFactory")
@patch("sumoappclient.sumoclient.httputils.ClientMixin")
def test_disk_metrics_api_load(
    mock_client_mixin, mock_output_handler_factory, num_records
):
    mock_kvstore = Mock()
    mock_config = {
        "MongoDBAtlas": {
            "PROJECT_ID": "test_project",
            "BASE_URL": "http://localhost:8247",
            "PAGINATION_LIMIT": 100,
            "METRIC_TYPES": {"DISK_METRICS": ["disk_metric1", "disk_metric2"]},
        }
    }
    mock_cluster_mapping = {"test-cluster": "alias"}

    disk_metrics_api = DiskMetricsAPI(
        mock_kvstore, "test-process-id", "test-disk", mock_config, mock_cluster_mapping
    )

    bulk_data = {
        "measurements": [
            {
                "name": "disk_metric1",
                "units": "GB",
                "dataPoints": [
                    {"timestamp": f"2023-07-26T{i//60:02d}:{i%60:02d}:00Z", "value": i}
                    for i in range(num_records)
                ],
            }
        ],
        "hostId": "test-cluster-host",
        "processId": "test-cluster-process",
        "groupId": "test_project",
        "partitionName": "test-disk",
    }

    mock_client_mixin.make_request.return_value = (True, bulk_data)
    start_time = time.time()
    disk_metrics_api.fetch()
    end_time = time.time()

    execution_time = end_time - start_time
    print(f"Disk Metrics API load test results for {num_records} records:")
    print(f"Execution time: {execution_time:.2f} seconds")

    assert (
        execution_time < 300
    ), f"Processing {num_records} disk metric records took more than 5 minutes"
