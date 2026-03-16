from pydantic import BaseModel


class RegisterRequest(BaseModel):
    username: str
    password: str


class InviteRequest(BaseModel):
    username: str
