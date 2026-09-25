from pydantic import BaseModel


class DzzConnectRequest(BaseModel):
    login: str = ""
    password: str = ""
    service_url: str | None = None
