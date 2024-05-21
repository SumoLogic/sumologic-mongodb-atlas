import asyncio
from faker import Faker
from motor.motor_asyncio import AsyncIOMotorClient

# Initialize Faker
fake = Faker()

# MongoDB connection
client = AsyncIOMotorClient("mongo-connection-string")
db = client["database-name"]
# Define the collections where data is to be inserted
collection1 = db["dummy_collection"]
collection2 = db["dummy_collection_1"]

async def generate_fake_data():
    data = {
        "name": fake.name(),
        "email": fake.email(),
        "address": fake.address(),
        "phone": fake.phone_number(),
        "job": fake.job(),
        "company": fake.company(),
        "salary": fake.random_int(min=30000, max=100000),
        "age": fake.random_int(min=18, max=65),
    }
    return data

async def insert_data(collection, data):
    await collection.insert_one(data)

async def main():
    num_records = 10000
    tasks = []

    for _ in range(num_records):
        data = await generate_fake_data()
        tasks.append(asyncio.create_task(insert_data(collection1, data)))
        tasks.append(asyncio.create_task(insert_data(collection2, data)))

    await asyncio.gather(*tasks)

    print(f"Inserted {num_records} records into each collection.")

asyncio.run(main())
