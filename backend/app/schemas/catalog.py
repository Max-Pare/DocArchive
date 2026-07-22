from pydantic import BaseModel, Field


class VisitTypeOut(BaseModel):
    id: int
    key: str
    label: str
    model_config = {"from_attributes": True}


class VisitTypeCreate(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=128)


class TagOut(BaseModel):
    id: int
    name: str
    model_config = {"from_attributes": True}


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
