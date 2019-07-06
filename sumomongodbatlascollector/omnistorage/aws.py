# -*- coding: future_fstrings -*-
import copy
import os
import sys
import time

if __name__ == "__main__":
    cur_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, cur_dir)


import decimal
import json
import boto3
from datetime import datetime
import dateutil.parser
from botocore.exceptions import ClientError
from common.logger import get_logger
from omnistorage.base import Provider, KeyValueStorage
from omnistorage.factory import ProviderFactory


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)


if sys.version_info > (3, 2):
    from datetime import timezone
    utc = timezone.utc
else:
    from datetime import tzinfo, timedelta
    ZERO = timedelta(0)

    class UTC(tzinfo):

        def utcoffset(self, dt):
            return ZERO

        def tzname(self, dt):
            return "UTC"

        def dst(self, dt):
            return ZERO

    utc = UTC()

def convert_date_to_epoch(datestr):
    dateobj = dateutil.parser.parse(datestr)
    if sys.version_info > (3, 3):
        return dateobj.timestamp()
    else:
        return (dateobj - datetime(1970, 1, 1, tzinfo=utc)).total_seconds()


def get_current_datetime():
    return datetime.now(tz=utc)



class AWSKVStorage(KeyValueStorage):
    KEY_COL = "key_col"
    VALUE_COL = "value_col"
    LOCK_DATE_COL = "last_locked_date"

    KEY_TYPE = "S"

    def setup(self, name, region_name, key_type=KEY_TYPE, force_create=False, *args, **kwargs):
        self.region_name = region_name
        self.dynamodbcli = boto3.resource('dynamodb', region_name=self.region_name)
        self.table_name = name
        self.key_type = key_type
        if force_create:
            self.destroy()
        if not self.table_exists(self.table_name, self.region_name):
            self._create_table()

    def _replace_decimals(self, obj):
        if isinstance(obj, list):
            for i in range(len(obj)):
                obj[i] = self._replace_decimals(obj[i])
            return obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = self._replace_decimals(v)
            return obj
        elif isinstance(obj, set):
            return set(self._replace_decimals(i) for i in obj)
        elif isinstance(obj, decimal.Decimal):
            if obj % 1 == 0:
                return int(obj)
            else:
                return float(obj)
        else:
            return obj

    def _put_decimals(self, obj):
        if isinstance(obj, list):
            for i in range(len(obj)):
                obj[i] = self._put_decimals(obj[i])
            return obj
        elif isinstance(obj, dict):
            for k, v in obj.items():
                obj[k] = self._put_decimals(v)
            return obj
        elif isinstance(obj, set):
            return set(self._put_decimals(i) for i in obj)
        elif isinstance(obj, float):
            # refer https://github.com/boto/boto3/issues/665
            return decimal.Decimal(str(obj))
        else:
            return obj

    def get(self, key):
        table = self.dynamodbcli.Table(self.table_name)
        response = table.get_item(Key={self.KEY_COL: key},
                                  ConsistentRead=True,
                                  ReturnConsumedCapacity='TOTAL')
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in get_item api: {response}''')
        value = response["Item"][self.VALUE_COL] if response.get("Item") else None
        self.log.debug(f'''Fetched Item {key} from {self.table_name} table''')
        return self._replace_decimals(value)

    def _get_item(self, key, default=None):
        table = self.dynamodbcli.Table(self.table_name)
        response = table.get_item(Key={self.KEY_COL: key},
                                  ConsistentRead=True,
                                  ReturnConsumedCapacity='TOTAL')
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in get_item api: {response}''')
        item = response.get("Item", {})
        if not item:
            self.log.warning("Key %s not Found" % key)
            return default
        item[self.VALUE_COL] = self._replace_decimals(item[self.VALUE_COL])
        self.log.debug(f'''Fetched Item {key} from {self.table_name} table''')
        return item

    def set(self, key, value):
        cpvalue = copy.deepcopy(value)
        cpvalue = self._put_decimals(cpvalue)
        table = self.dynamodbcli.Table(self.table_name)
        response = table.put_item(Item={self.KEY_COL: key,
                                        self.VALUE_COL: cpvalue
                                        },
                                  ReturnConsumedCapacity='TOTAL')
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in put_item api: {response}''')
        self.log.debug(f'''Saved Item {key} from {self.table_name} table response: {response}''')

    def has_key(self, key):
        # Todo catch item not found in get/delete
        is_present = False if self.get(key) is None else True
        return is_present

    def delete(self, key):
        table = self.dynamodbcli.Table(self.table_name)
        response = table.delete_item(Key={self.KEY_COL: key})
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in delete_item api: {response}''')
        self.log.debug(f'''Deleted Item {key} from {self.table_name} table response: {response}''')

    def destroy(self):
        table = self.dynamodbcli.Table(self.table_name)
        try:
            response = table.delete()
            table.wait_until_not_exists()
            self.log.debug(f'''Deleted Table {self.table_name} response: {response}''')
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceNotFoundException':
                raise e

    def acquire_lock(self, key):
        lock_key = self._get_lock_key(key)
        table = self.dynamodbcli.Table(self.table_name)
        try:
            if self.has_key(lock_key):
                response = table.update_item(
                    Key={
                        self.KEY_COL: lock_key
                    },
                    ReturnValues='UPDATED_NEW',
                    ReturnConsumedCapacity='TOTAL',
                    ReturnItemCollectionMetrics='NONE',
                    UpdateExpression=f'''set {self.VALUE_COL} = :val1, {self.LOCK_DATE_COL} = :val3''',
                    ConditionExpression=f'''{self.VALUE_COL} = :val2''',
                    ExpressionAttributeValues={
                        ':val1': decimal.Decimal('1'),
                        ':val2': decimal.Decimal('0'),
                        ':val3': get_current_datetime().isoformat()
                    }
                )
            else:
                # create key
                response = table.update_item(
                    Key={
                        self.KEY_COL: lock_key
                    },
                    ReturnValues='UPDATED_NEW',
                    ReturnConsumedCapacity='TOTAL',
                    ReturnItemCollectionMetrics='NONE',
                    UpdateExpression=f'''set {self.VALUE_COL} = :val1, {self.LOCK_DATE_COL} = :val3''',
                    ConditionExpression=f'''attribute_not_exists({self.VALUE_COL})''',
                    ExpressionAttributeValues={
                        ':val1': decimal.Decimal('1'),
                        ':val3': get_current_datetime().isoformat()
                    }
                )
            if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
                raise Exception(f'''Error in put_item api: {response}''')
        except ClientError as e:
            if e.response['Error']['Code'] == "ConditionalCheckFailedException":
                self.log.warning(f'''Failed to acquire lock on key: {key} Message: {e.response['Error']['Message']}''')
            else:
                self.log.error(f'''Error in Acquiring lock {str(e)}''')
            return False
        else:
            self.log.debug(f'''Lock acquired key: {key} Message: {response["Attributes"]}''')
            return True

    def release_lock_on_expired_key(self, key, expiry_min=5):
        lock_key = self._get_lock_key(key)
        data = self._get_item(lock_key)
        if data and self.LOCK_DATE_COL in data:
            now = time.time()
            past = convert_date_to_epoch(data[self.LOCK_DATE_COL])
            if (now - past) > expiry_min*60:
                self.log.debug(f'''Lock time expired key: {key} passed time: {(now-past)/60} min''')
                self.release_lock(key)

    def release_lock(self, key):

        lock_key = self._get_lock_key(key)
        table = self.dynamodbcli.Table(self.table_name)
        try:
            response = table.update_item(
                Key={
                    self.KEY_COL: lock_key
                },
                ReturnValues='UPDATED_NEW',
                ReturnConsumedCapacity='TOTAL',
                ReturnItemCollectionMetrics='NONE',
                UpdateExpression=f'''set {self.VALUE_COL} = :val1''',
                ConditionExpression=f'''{self.VALUE_COL} = :val2''',
                ExpressionAttributeValues={
                    ':val1': decimal.Decimal(0),
                    ':val2': decimal.Decimal(1)
                }
            )
            if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
                raise Exception(f'''Error in put_item api: {response}''')
        except ClientError as e:
            if e.response['Error']['Code'] == "ConditionalCheckFailedException":
                self.log.warning(f'''Failed to release lock on key: {key} Message: {e.response['Error']['Message']}''')
            else:
                self.log.error(f'''Error in Releasing lock {str(e)}''')
            return False
        else:
            self.log.debug(f'''Lock released key: {key} Message: {response["Attributes"]}''')
            return True



    @classmethod
    def table_exists(cls, table_name, region_name, logger=get_logger(__name__)):

        dynamodbcli = boto3.client('dynamodb', region_name=region_name)
        try:
            response = dynamodbcli.describe_table(TableName=table_name)
            if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
                raise Exception("Error in describe_table api: %s" % response)
            logger.info(f'''Table {table_name} already exists''')
            return True
        except dynamodbcli.exceptions.ResourceNotFoundException:
            return False

    def _create_table(self):
        table = self.dynamodbcli.create_table(
            TableName=self.table_name,
            KeySchema=[
                {
                    'AttributeName': self.KEY_COL,
                    'KeyType': 'HASH'
                },
            ],
            AttributeDefinitions=[
                {
                    'AttributeName': self.KEY_COL,
                    'AttributeType': self.key_type
                },
            ],
            ProvisionedThroughput={
                'ReadCapacityUnits': 30,
                'WriteCapacityUnits': 20
            }
        )
        table.wait_until_exists()
        self.log.debug(f'''Table {self.table_name} created''')

    @classmethod
    def batch_insert(cls, dynamodbcli, rows, table_name, logger=get_logger(__name__)):
        # Todo handle unwritten items https://stackoverflow.com/questions/22201967/how-do-i-detect-unwritten-items-in-dynamodb2
        if len(rows) > 0:
            table = dynamodbcli.Table(table_name)
            with table.batch_writer() as batch:
                for item in rows:
                    batch.put_item(Item=item)
            logger.info(f'''Inserted Items into {table_name} table Count: {len(rows)}''')

    @classmethod
    def batch_get_items(cls, dynamodbcli, rowkeys, table_name, key=None, logger=get_logger(__name__)):
        # Todo in future add pagination here currently len(values) <= 100 and add support for unprocessed keys
        # https://stackoverflow.com/questions/12122006/simple-example-of-retrieving-500-items-from-dynamodb-using-python
        keycol = key or cls.KEY_COL
        response = dynamodbcli.batch_get_item(
            RequestItems={
                table_name: {
                    'Keys': [{keycol: val} for val in set(rowkeys)],
                    'ConsistentRead': True
                }
            },
            ReturnConsumedCapacity='TOTAL'
        )
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception("Error in batch_get_item api: %s" % response)
        items = response['Responses'][table_name]
        logger.info(f'''Fetched Items from {table_name} table Count: {len(items)} UnprocessedKeys: {response["UnprocessedKeys"]}''')
        return items


class AWSProvider(Provider):  # should we disallow direct access to these classes

    def setup(self, *args, **kwargs):
        self.region_name = kwargs.get('region_name', os.getenv("AWS_REGION"))

    def get_kvstorage(self, name, *args, **kwargs):
        return AWSKVStorage(name, self.region_name, *args, **kwargs)



if __name__ == "__main__":
    key = "abc"
    key2 = 101
    # keys in value should of same type 1 cannot be a key in below example
    # similarly key or primary key should be same
    value = {"name": "Himanshu", '1': 23423, "fv": 12.344}
    cli = ProviderFactory.get_provider("aws", region_name="us-east-1")
    kvstore = cli.get_storage("keyvalue", name='kvstore', force_create=True)
    kvstore.set(key, value)
    assert(kvstore.get(key) == value)
    assert(kvstore.has_key(key) == True)
    kvstore.delete(key)
    assert(kvstore.has_key(key) == False)
    # assert(kvstore.acquire_lock(key) == True)
    # assert(kvstore.acquire_lock(key) == False)
    # assert(kvstore.acquire_lock("blah") == True)
    # assert(kvstore.release_lock(key) == True)
    # assert(kvstore.release_lock(key) == False)
    # assert(kvstore.release_lock("blahblah") == False)
    kvstore.destroy()
    kvstore = cli.get_storage("keyvalue", name='kvstore', key_type='N', force_create=True)
    kvstore.set(key2, value)
    assert(kvstore.get(key2) == value)
    assert(kvstore.has_key(key2) == True)
    kvstore.delete(key2)
    assert(kvstore.has_key(key2) == False)
    kvstore.destroy()
