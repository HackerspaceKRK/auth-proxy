import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime, UTC
from typing import Annotated, Any

import httpx

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi_utilities import repeat_every
from pydantic import AliasPath, BaseModel, Field, field_validator, model_validator
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
    authentik_token: str | None = None
    authentik_token_file: str | None = None

    @model_validator(mode='after')
    def set_token(self) -> "Settings":
        if self.authentik_token:
            return self
        if self.authentik_token_file:
            try:
                with open(self.authentik_token_file) as f:
                    self.authentik_token = f.read().strip()
            except FileNotFoundError:
                raise ValueError(f"Token file not found: {self.authentik_token_file}")
            return self
        raise ValueError("Either AUTHENTIK_TOKEN or AUTHENTIK_TOKEN_FILE must be set")


config = Settings()


users: list[User] = []
users_by_card: dict[str, User] = {}
users_last_success_run: datetime | None = None
users_last_failed_run: datetime | None = None
users_last_failed_reason: Any = None


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
            timeout=30.0,
        ) as client:
        url = (
            "https://auth.apps.hskrk.pl/api/v3/core/users/?"
            "attributes={\"membershipExpirationTimestamp__gt\": 100}&page_size=50"
        )
        response = await client.get(url)
        parsed_response = response.json()
        results = parsed_response["results"]
        while parsed_response["pagination"]["next"]:
            response = await client.get(f"{url}&page={parsed_response["pagination"]["next"]}")
            parsed_response = response.json()
            results += parsed_response["results"]
        return [
            User(**u)
            for u in results
        ]


@repeat_every(seconds=300)
async def fetch_users():
    global users
    global users_by_card
    try:
        logging.debug("Fetching users from Authentik")
        users = await fetch()
    except Exception as ex:
        logging.exception("Failed to fetch users")
        global users_last_failed_run
        global users_last_failed_reason
        users_last_failed_run = datetime.now(tz=UTC)
        users_last_failed_reason = ex
    else:
        global users_last_success_run
        users_last_success_run = datetime.now(tz=UTC)
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
        logging.debug(f"Fetched {len(users)} users ({len(users_by_card)} cards) from Authentik")


@app.get("/users/-/stats")
async def get_user_stats():
    return {
        "last_success_run": users_last_success_run.isoformat().replace("+00:00", "Z") if users_last_success_run else None,
        "last_failed_run": users_last_failed_run.isoformat().replace("+00:00", "Z") if users_last_failed_run else None,
        "last_failed_reason": str(users_last_failed_reason) if users_last_failed_reason else None,
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
        logging.warning("[WS] Card %s not found", card_id)
        raise HTTPException(status_code=404, detail="Item not found")
    logging.info("[HTTP] User %s (%s) found", user.uid, card_id)
    return user


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    logging.debug("[WS] New connection")
    await websocket.accept()
    try:
        async for message in websocket.iter_json():
            logging.debug("[WS] WS Request %r", message)
            match message:
                case {"action": "get", "object": "user", **kwargs}:
                    logging.debug("[WS] Get user %r", kwargs)
                    if "card_id" in kwargs and isinstance(kwargs["card_id"], str):
                        user = users_by_card.get(kwargs["card_id"].lower())
                    else:
                        user = None

                    if user is None:
                        logging.warning("[WS] Card %s not found", kwargs.get("card_id"))
                        await websocket.send_json(
                            {"status": "error", "error": "user not found"}
                        )
                    else:
                        logging.info("[WS] User %s (%s) found", user.uid, kwargs.get("card_id"))
                        await websocket.send_json(
                            {"status": "ok", "object": user.model_dump()}
                        )

    except WebSocketDisconnect:
        pass
