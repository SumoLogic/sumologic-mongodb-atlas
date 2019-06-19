# -*- coding: future_fstrings -*-
from sys import path
path.append("/Users/hpal/git/sumologic-mongodb-atlas/sumomongodbatlascollector/")

from base import Provider, KeyValueStorage
import boto3
from datetime import datetime, timezone
from factory import ProviderFactory
from common.logger import get_logger
import json
import os
import decimal
from botocore.exceptions import ClientError


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, decimal.Decimal):
            if o % 1 > 0:
                return float(o)
            else:
                return int(o)
        return super(DecimalEncoder, self).default(o)


def get_current_datetime():
    return datetime.now(tz=timezone.utc)


class AWSKVStorage(KeyValueStorage):
    KEY_COL = "key_col"
    VALUE_COL = "value_col"
    LOCK_DATE_COL = "last_locked_date"

    KEY_TYPE = "S"

    def setup(self, name, region_name, key_type=KEY_TYPE, force_create=False, *args, **kwargs):
        self.region_name = region_name
        self.dynamodbcli = boto3.resource('dynamodb', region_name=self.region_name)
        self.table_name = name
        self.logger = get_logger(__name__)
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

    def get(self, key):
        table = self.dynamodbcli.Table(self.table_name)
        response = table.get_item(Key={self.KEY_COL: key},
                                  ConsistentRead=True,
                                  ReturnConsumedCapacity='TOTAL')
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in get_item api: {response}''')
        value = response["Item"][self.VALUE_COL] if response.get("Item") else None
        self.logger.info(f'''Fetched Item {key} from {self.table_name} table''')
        return self._replace_decimals(value)

    def set(self, key, value):
        table = self.dynamodbcli.Table(self.table_name)
        response = table.put_item(Item={self.KEY_COL: key,
                                        self.VALUE_COL: value
                                        },
                                  ReturnConsumedCapacity='TOTAL')
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in put_item api: {response}''')
        self.logger.info(f'''Saved Item {key} from {self.table_name} table response: {response}''')

    def has_key(self, key):
        # Todo catch item not found in get/delete
        is_present = True if self.get(key) else False
        return is_present

    def delete(self, key):
        table = self.dynamodbcli.Table(self.table_name)
        response = table.delete_item(Key={self.KEY_COL: key})
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in delete_item api: {response}''')
        self.logger.info(f'''Deleted Item {key} from {self.table_name} table response: {response}''')

    def destroy(self):
        table = self.dynamodbcli.Table(self.table_name)
        try:
            response = table.delete()
            table.wait_until_not_exists()
            self.logger.info(f'''Deleted Table {self.table_name} response: {response}''')
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceNotFoundException':
                raise e

    def _get_lock_key(self, key):
        return "lockon_%s" % key

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
                self.logger.warning(f'''Failed to acquire lock on key: {key} Message: {e.response['Error']['Message']}''')
            else:
                self.logger.error(f'''Error in Acquiring lock {str(e)}''')
            return False
        else:
            self.logger.info(f'''Lock acquired key: {key} Message: {response["Attributes"]}''')
            return True

    def release_lock(self, key):

        lock_key = "lockon_%s" % key
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
                self.logger.warning(f'''Failed to release lock on key: {key} Message: {e.response['Error']['Message']}''')
            else:
                self.logger.error(f'''Error in Releasing lock {str(e)}''')
            return False
        else:
            self.logger.info(f'''Lock released key: {key} Message: {response["Attributes"]}''')
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
        self.logger.info(f'''Table {self.table_name} created''')

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
    value = {"name": "Himanshu"}
    cli = ProviderFactory.get_provider("aws", region_name="us-east-1")
    kvstore = cli.get_storage("keyvalue", name='kvstore', force_create=True)
    kvstore.set(key, value)
    print(kvstore.get(key) == value)
    print(kvstore.has_key(key) == True)
    kvstore.delete(key)
    print(kvstore.has_key(key) == False)
    print(kvstore.acquire_lock(key) == True)
    print(kvstore.acquire_lock(key) == False)
    print(kvstore.acquire_lock("blah") == True)
    print(kvstore.release_lock(key) == True)
    print(kvstore.release_lock(key) == False)
    print(kvstore.release_lock("blahblah") == False)
    kvstore.destroy()
