import pytest
from unittest.mock import MagicMock, patch
# from datetime import datetime, timedelta
# import time
from requests.auth import HTTPDigestAuth

from sumoappclient.sumoclient.base import BaseAPI
# from sumoappclient.common.utils import get_current_timestamp
from sumomongodbatlascollector.api import MongoDBAPI


class ConcreteMongoDBAPI(MongoDBAPI):
    MOVING_WINDOW_DELTA = 0.001

    def get_key(self):
        return "test_key"

    def save_state(self, *args, **kwargs):
        pass

    def get_state(self):
        return {}

    def build_fetch_params(self):
        return {}

    def build_send_params(self):
        return {}

    def transform_data(self, content):
        return content

    def fetch(self):
        return []


@pytest.fixture
def mongodb_api():
    kvstore = MagicMock()
    config = {
        "MongoDBAtlas": {
            "PUBLIC_API_KEY": "public_key",
            "PRIVATE_API_KEY": "private_key",
            "Collection": {
                "MAX_REQUEST_WINDOW_LENGTH": 900,
                "MIN_REQUEST_WINDOW_LENGTH": 60,
            },
        },
        "Collection": {
            "END_TIME_EPOCH_OFFSET_SECONDS": 60,
            "TIMEOUT": 300,
            "BACKFILL_DAYS": 7,
            "ENVIRONMENT": "aws",
        },
        "Logging": {},
        "SumoLogic": {},
    }
    return ConcreteMongoDBAPI(kvstore, config)


def test_init(mongodb_api):
    assert isinstance(mongodb_api.digestauth, HTTPDigestAuth)
    assert mongodb_api.digestauth.username == "public_key"
    assert mongodb_api.digestauth.password == "private_key"
    assert mongodb_api.MAX_REQUEST_WINDOW_LENGTH == 900
    assert mongodb_api.MIN_REQUEST_WINDOW_LENGTH == 60
    assert isinstance(mongodb_api, MongoDBAPI)
    assert isinstance(mongodb_api, BaseAPI)


@pytest.mark.skip()
@patch("sumoappclient.common.utils.get_current_timestamp")
def test_get_window(mock_get_current_timestamp, mongodb_api):
    mock_get_current_timestamp.return_value = 1000000
    last_time_epoch = 999000
    with patch("time.sleep") as mock_sleep:
        start, end = mongodb_api.get_window(last_time_epoch)
        print(f"Case 1 - Start: {start}, End: {end}")
        assert start == 999000.001
        assert end == 999940
        mock_sleep.assert_not_called()

    # Test case 2: Window initially too small, requires sleep
    mock_get_current_timestamp.side_effect = [1000000, 1000060]
    last_time_epoch = 999999
    with patch("time.sleep") as mock_sleep:
        start, end = mongodb_api.get_window(last_time_epoch)
        print(f"Case 2 - Start: {start}, End: {end}")
        assert start == 999999.001
        assert end == 1000000
        mock_sleep.assert_called_once_with(60)

    # Test case 3: Window exceeds MAX_REQUEST_WINDOW_LENGTH
    mock_get_current_timestamp.return_value = 1005000
    last_time_epoch = 1000000
    with patch("time.sleep") as mock_sleep:
        start, end = mongodb_api.get_window(last_time_epoch)
        print(f"Case 3 - Start: {start}, End: {end}")
        assert start == 1000000.001
        assert end == 1003600.001  # start + MAX_REQUEST_WINDOW_LENGTH
        mock_sleep.assert_not_called()

    print(f"MIN_REQUEST_WINDOW_LENGTH: {mongodb_api.MIN_REQUEST_WINDOW_LENGTH}")
    print(f"MAX_REQUEST_WINDOW_LENGTH: {mongodb_api.MAX_REQUEST_WINDOW_LENGTH}")
    print(
        f"END_TIME_EPOCH_OFFSET_SECONDS: {mongodb_api.collection_config['END_TIME_EPOCH_OFFSET_SECONDS']}"
    )
