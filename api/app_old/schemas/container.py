from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional, List


class ContainerBase(BaseModel):
    name: str = "StaffBot 1"


class ContainerCreate(ContainerBase):
    name: str = "StaffBot 1"
    skills: Optional[List[str]] = None


class ContainerUpdate(BaseModel):
    name: Optional[str] = None
    skills: Optional[List[str]] = None
    status: Optional[str] = None


class ContainerResponse(BaseModel):
    id: int
    client_id: int
    name: str
    container_name: Optional[str] = None
    image: str
    port: Optional[int] = None
    status: str
    skills: Optional[list] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ContainerStatusUpdate(BaseModel):
    status: str
    message: Optional[str] = None
