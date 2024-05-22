import memory_profiler
import pyinstrument
from api import (
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
from main import MongoDBAtlasCollector
from mocks import generate_mock_config


@memory_profiler.profile
def profile_fetch_mixin():
    mock_config = generate_mock_config()
    fetch_mixin = FetchMixin(kvstore=None, config=mock_config)
    fetch_mixin.fetch()


@memory_profiler.profile
def profile_paginated_fetch_mixin():
    mock_config = generate_mock_config()
    paginated_fetch_mixin = PaginatedFetchMixin(
        kvstore=None, config=mock_config
    )
    paginated_fetch_mixin.fetch()


@memory_profiler.profile
def profile_process_metrics_api():
    mock_config = generate_mock_config()
    process_metrics_api = ProcessMetricsAPI(
        kvstore=None, config=mock_config, process_id=0, cluster_mapping=dict()
    )
    process_metrics_api.fetch()


@memory_profiler.profile
def profile_project_events_api():
    mock_config = generate_mock_config()
    project_events_api = ProjectEventsAPI(kvstore=None, config=mock_config)
    project_events_api.fetch()


@memory_profiler.profile
def profile_org_events_api():
    mock_config = generate_mock_config()
    org_events_api = OrgEventsAPI(kvstore=None, config=mock_config)
    org_events_api.fetch()


@memory_profiler.profile
def profile_disk_metrics_api():
    mock_config = generate_mock_config()
    disk_metrics_api = DiskMetricsAPI(kvstore=None, config=mock_config)
    disk_metrics_api.fetch()


@memory_profiler.profile
def profile_log_api():
    mock_config = generate_mock_config()
    log_api = LogAPI(kvstore=None, config=mock_config)
    log_api.fetch()


@memory_profiler.profile
def profile_alerts_api():
    mock_config = generate_mock_config()
    alerts_api = AlertsAPI(kvstore=None, config=mock_config)
    alerts_api.fetch()


@memory_profiler.profile
def profile_database_metrics_api():
    mock_config = generate_mock_config()
    database_metrics_api = DatabaseMetricsAPI(kvstore=None, config=mock_config)
    database_metrics_api.fetch()


@memory_profiler.profile
def profile_build_task_params(collector):
    collector.build_task_params()


@memory_profiler.profile
def profile_run(collector):
    collector.run()


@memory_profiler.profile
def profile_test(collector):
    collector.test()


def generate_flamegraph():
    profiler = pyinstrument.Profiler()
    profiler.start()

    mock_config = generate_mock_config()
    process_metrics_api = ProcessMetricsAPI(kvstore=None, config=mock_config)
    process_metrics_api.fetch()

    project_events_api = ProjectEventsAPI(kvstore=None, config=mock_config)
    project_events_api.fetch()

    org_events_api = OrgEventsAPI(kvstore=None, config=mock_config)
    org_events_api.fetch()

    disk_metrics_api = DiskMetricsAPI(kvstore=None, config=mock_config)
    disk_metrics_api.fetch()

    log_api = LogAPI(kvstore=None, config=mock_config)
    log_api.fetch()

    alerts_api = AlertsAPI(kvstore=None, config=mock_config)
    alerts_api.fetch()

    database_metrics_api = DatabaseMetricsAPI(kvstore=None, config=mock_config)
    database_metrics_api.fetch()

    profiler.stop()

    with open("flamegraph.html", "w") as f:
        f.write(profiler.output_html())


def generate_flamegraph_collector(collector):
    profiler = pyinstrument.Profiler()
    profiler.start()

    collector.build_task_params()
    collector.run()
    collector.test()

    profiler.stop()

    with open("flamegraph_collector.html", "w") as f:
        f.write(profiler.output_html())


if __name__ == "__main__":
    print("Profiling ProcessMetricsAPI...")
    profile_process_metrics_api()

    print("Profiling ProjectEventsAPI...")
    profile_project_events_api()

    print("Profiling OrgEventsAPI...")
    profile_org_events_api()

    print("Profiling DiskMetricsAPI...")
    profile_disk_metrics_api()

    print("Profiling LogAPI...")
    profile_log_api()

    print("Profiling AlertsAPI...")
    profile_alerts_api()

    print("Profiling DatabaseMetricsAPI...")
    profile_database_metrics_api()

    print("Generating flame graph...")
    generate_flamegraph()
    print("Flame graph generated: flamegraph.html")

    collector = MongoDBAtlasCollector()

    # Profile build_task_params
    print("Profiling build_task_params...")
    profile_build_task_params(collector)

    # Profile run
    print("Profiling run...")
    profile_run(collector)

    # Profile test
    print("Profiling test...")
    profile_test(collector)

    # Generate flame graph
    print("Generating flame graph...")
    generate_flamegraph_collector(collector)
    print("Flame graph generated: flamegraph_collector.html")
