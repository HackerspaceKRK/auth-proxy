import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

import httpx

from fastapi import FastAPI, HTTPException
from fastapi_utilities import repeat_every
from pydantic import AliasPath, BaseModel, Field, field_validator
from pydantic_core import PydanticUseDefault
from pydantic_settings import BaseSettings


def transform_card_number_to_unique(card_number: str):
    """
    For new, longer card ID format, we need to transform it to the old format
    New card ID is returned in the exact byte order that's on card, not reversed while shorter format was reversed
    to match the decimal representation printed on key fobs, so it can be just converted to hex and put in LDAP.
    """
    if len(card_number) == 8:
        return card_number[4:6] + card_number[2:4] + card_number[0:2]
    else:
        return card_number


def transform_card_number_to_mifare(card_number: str):
    """
    For new, longer card ID format, we need to transform it to the old format
    New card ID is returned in the exact byte order that's on card, not reversed while shorter format was reversed
    to match the decimal representation printed on key fobs, so it can be just converted to hex and put in LDAP.
    """
    if len(card_number) == 6:
        return card_number[4:6] + card_number[2:4] + card_number[0:2] + "00"
    else:
        return card_number


class User(BaseModel):
    uid: Annotated[str, Field(validation_alias="username")]
    mifare_card_ids: Annotated[list[str], Field(validation_alias=AliasPath("attributes", "mifareCardId"))] = []
    unique_card_ids: Annotated[list[str], Field(validation_alias=AliasPath("attributes", "uniquecardId"))] = []
    membership_expiration: Annotated[
        int,
        Field(validation_alias=AliasPath("attributes", "membershipExpirationTimestamp"))
    ]

    @field_validator("mifare_card_ids", "unique_card_ids", mode='plain')
    def use_default_for_missing_cards(cls, v) -> str:
        if v is None:
            raise PydanticUseDefault()
        return v


class Settings(BaseSettings):
    authentik_token: str = ...


config = Settings()


users: list[User] = []
users_by_card: dict[str, User] = {}
users_last_success_run: datetime | None
users_last_failed_run: datetime | None
users_last_failed_reason: Any


@asynccontextmanager
async def lifespan(app: FastAPI):
    await fetch_users()
    yield


app = FastAPI(lifespan=lifespan)


def auth():
    return


async def fetch() -> list[User]:
    async with httpx.AsyncClient(
            headers={"Authorization": f"Bearer {config.authentik_token}"},
            timeout=15.0,
        ) as client:
        response = await client.get(
            "https://auth.apps.hskrk.pl/api/v3/core/users/"
            "?attributes={\"membershipExpirationTimestamp__gt\": 1734998400}&page_size=200",
        )
        return [
            User(**u)
            for u in response.json()['results']
        ]


@repeat_every(seconds=300)
async def fetch_users():
    global users
    global users_by_card
    try:
        users = await fetch()
    except Exception:
        logging.exception("Failed to fetch users")
    else:
        users_by_card = {
            **{
                mifare.lower(): user
                for user in users for mifare in user.mifare_card_ids
            },
            **{
                transform_card_number_to_unique(mifare).lower(): user
                for user in users for mifare in user.mifare_card_ids
            },
            **{
                unique.lower(): user
                for user in users for unique in user.unique_card_ids
            },
            **{
                transform_card_number_to_mifare(unique).lower(): user
                for user in users for unique in user.unique_card_ids
            },
        }


@app.get("/users/-/stats")
async def get_user_stats():
    return {
        "users": {
            "count": len(users),
        },
        "cards": {
            "count": len(users_by_card),
        },
    }


@app.get("/users/-/by-card/{card_id}")
async def get_user_by_card(card_id: str):
    user = users_by_card.get(card_id.lower())
    if user is None:
        raise HTTPException(status_code=404, detail="Item not found")
    return user
