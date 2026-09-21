from pydantic import BaseModel, Field


class DzzConnectRequest(BaseModel):
    login: str = Field(min_length=1)
    password: str = Field(min_length=1)
    service_url: str | None = None
