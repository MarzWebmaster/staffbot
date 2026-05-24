from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class NotificationChannelCreate(BaseModel):
    channel: str  # whatsapp / email / sms / in-app
    value: str


class NotificationChannelResponse(BaseModel):
    id: int
    client_id: int
    channel: str
    value: str
    is_active: bool
    is_primary: bool

    model_config = {"from_attributes": True}


class NotificationLogResponse(BaseModel):
    id: int
    type: str
    channel: str
    subject: Optional[str] = None
    status: str
    sent_at: datetime

    model_config = {"from_attributes": True}


class NotificationTest(BaseModel):
    channel: str
    value: str
    message: str = "This is a test notification from StaffBot.my"


class NotificationTestResponse(BaseModel):
    success: bool
    message: str
