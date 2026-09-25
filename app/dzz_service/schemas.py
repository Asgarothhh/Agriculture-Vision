from pydantic import BaseModel


class DzzConnectRequest(BaseModel):
    login: str = ""
    password: str = ""
    url: str | None = None
    service_url: str | None = None

    @property
    def service(self) -> str | None:
        return self.url or self.service_url


class WmtsCapabilitiesRequest(BaseModel):
    url: str | None = None
    login: str = ""
    password: str = ""
