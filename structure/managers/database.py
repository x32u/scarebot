from json import dumps, loads
from typing import Any, Optional

from asyncpg import Connection, Pool
from asyncpg import Record as DefaultRecord
from asyncpg import create_pool
from munch import DefaultMunch, Munch

from structure.config import Database


class Record(DefaultRecord):
    def __getattr__(self: "Record", attr: str) -> Any:
        return self.get(attr)


def encode_jsonb(value: Any) -> str:
    return dumps(value)


def decode_jsonb(value: str) -> Munch:
    return DefaultMunch.fromDict(loads(value))


async def init(connection: Connection) -> None:
    await connection.set_type_codec(
        "jsonb",
        schema="pg_catalog",
        encoder=encode_jsonb,
        decoder=decode_jsonb,
    )


async def setup(pool: Pool) -> Pool:
    with open("structure/schema.sql", "r", encoding="UTF-8") as buffer:
        schema = buffer.read()
        await pool.execute(schema)

    return pool


async def connect(dbname: str) -> Pool:
    pool: Optional[Pool] = await create_pool(
        host=Database.host,
        port=Database.port,
        password=Database.password,
        user=Database.user,
        database=dbname,
        init=init,
        record_class=Record,
    )
    if not pool:
        raise Exception("Could not establish a connection to the PostgreSQL server!")

    return await setup(pool)
