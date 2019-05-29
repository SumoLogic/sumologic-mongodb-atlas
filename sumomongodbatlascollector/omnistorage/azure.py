# -*- coding: future_fstrings -*-
from base import Provider, KeyValueStorage
import boto3

from factory import ProviderFactory
from utils import get_logger
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


class AWSKVStorage(KeyValueStorage):
    KEY_COL = "key"
    VALUE_COL = "value"
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
        self.logger.info(f'''Fetched Item from {self.table_name} table''')
        return self._replace_decimals(value)

    def set(self, key, value):
        table = self.dynamodbcli.Table(self.table_name)
        response = table.put_item(Item={self.KEY_COL: key,
                                        self.VALUE_COL: value},
                                  ReturnConsumedCapacity='TOTAL')
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in put_item api: {response}''')
        self.logger.info(f'''Saved Item from {self.table_name} table response: {response}''')

    def has_key(self, key):
        # Todo catch item not found in get/delete
        is_present = True if self.get(key) else False
        return is_present

    def delete(self, key):
        table = self.dynamodbcli.Table(self.table_name)
        response = table.delete_item(Key={self.KEY_COL: key})
        if response.get('ResponseMetadata')['HTTPStatusCode'] != 200:
            raise Exception(f'''Error in delete_item api: {response}''')
        self.logger.info(f'''Deleted Item from {self.table_name} table response: {response}''')

    def destroy(self):
        table = self.dynamodbcli.Table(self.table_name)
        try:
            response = table.delete()
            table.wait_until_not_exists()
            self.logger.info(f'''Deleted Table {self.table_name} response: {response}''')
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceNotFoundException':
                raise e


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
    kvstore.destroy()
