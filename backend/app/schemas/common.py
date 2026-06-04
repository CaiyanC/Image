from typing import Annotated
from uuid import UUID
from pydantic import BeforeValidator


def uuid_to_str(v: object) -> str:
    if isinstance(v, UUID):
        return str(v)
    return str(v)


UuidStr = Annotated[str, BeforeValidator(uuid_to_str)]
