mport asyncio
import time
import json
from faker import Faker
from motor.motor_asyncio import AsyncIOMotorClient

# Initialize Faker
fake = Faker()

# MongoDB connection
client = AsyncIOMotorClient("mongo-connection-string")
db = client["dummy_database"]
collection1 = db["dummy_collection"]
collection2 = db["dummy_collection_1"]

async def generate_fake_data():
    data = {
        "personal_info": {
            "name": fake.name(),
            "email": fake.email(),
            "phone": fake.phone_number(),
            "birth_date": fake.date_of_birth().isoformat(),
            "ssn": fake.ssn(),
            "passport_number": fake.swift(length=8),
            "driver_license": fake.license_plate(),
        },
        "address": {
            "street": fake.street_address(),
            "city": fake.city(),
            "state": fake.state(),
            "zip_code": fake.postcode(),
            "country": fake.country(),
            "latitude": float(fake.latitude()),
            "longitude": float(fake.longitude()),
        },
        "employment": {
            "job": fake.job(),
            "company": fake.company(),
            "salary": fake.random_int(min=30000, max=100000),
            "start_date": fake.date_between(start_date="-10y", end_date="today").isoformat(),
            "end_date": fake.date_between(start_date="today", end_date="+5y").isoformat(),
            "title": fake.job(),
            "department": fake.catch_phrase(),
        },
        "education": {
            "major": fake.word(),
            "graduation_year": fake.random_int(min=1980, max=2023),
        },
    }
    return data

async def insert_data_batch(collection, data_batch):
    await collection.insert_many(data_batch)

async def generate_and_insert_data(collection, num_records, batch_size):
    num_batches = (num_records + batch_size - 1) // batch_size
    for _ in range(num_batches):
        data_batch = [await generate_fake_data() for _ in range(batch_size)]
        await insert_data_batch(collection, data_batch)

async def main():
    total_size = "500MB"
    batch_size = 10000  # Adjust the batch size as needed
    
    size_in_bytes = parse_size(total_size)
    record_size = len(json.dumps(await generate_fake_data()).encode())
    num_records = size_in_bytes // record_size
    
    num_batches = (num_records + batch_size - 1) // batch_size
    
    start_time = time.time()
    tasks = []

    await asyncio.gather(
        generate_and_insert_data(collection1, num_records, batch_size),
        generate_and_insert_data(collection2, num_records, batch_size)
    )

    end_time = time.time()
    execution_time = end_time - start_time

    print(f"Inserted approximately {num_records} records into each collection.")
    print(f"Execution time: {execution_time:.2f} seconds")


def parse_size(size_str):
    units = {"B": 1, "KB": 1024, "MB": 1024**2, "GB": 1024**3}
    size_value, unit = size_str[:-2], size_str[-2:]
    return int(size_value) * units[unit]

asyncio.run(main())
