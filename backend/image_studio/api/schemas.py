"""Validated browser requests; keep resource limits at the API boundary."""

from typing import Literal
from pydantic import BaseModel, Field, field_validator

from image_studio.core import providers

LOCAL_MODELS = ('realistic', 'accurate', 'turbo')
LOCAL_EDITORS = ('kontext', 'photocraft')


def model_choice(value, local):
    """A local model id, or a cloud one written provider:model (core/providers.py)."""
    if value in local:
        return value
    provider, model = providers.split(value)
    if provider and model and len(value) <= 200:
        return value
    raise ValueError(f'Choose one of {", ".join(local)}, or a connected cloud model.')


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=6000)
    model: str = 'realistic'

    @field_validator('model')
    @classmethod
    def known_model(cls, value):
        return model_choice(value, LOCAL_MODELS)

    size: str
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    steps: int = Field(default=30, ge=1, le=50)
    guidance: float = Field(default=5, ge=0, le=15)
    negative_prompt: str = Field(default='', max_length=6000)
    detail: Literal['Off', '1.5× size', '2× size'] = 'Off'
    detail_strength: float = Field(default=0.35, ge=0.1, le=0.7)
    count: int = Field(default=1, ge=1, le=4)
    smart: bool = False
    sketch: str | None = Field(default=None, max_length=40_000_000)
    sketch_freedom: float = Field(default=0.65, ge=0.1, le=1)
    vary: bool = True
    check: bool = False
    attempts: int = Field(default=2, ge=1, le=4)
    repair: bool = True
    repair_strength: float = Field(default=0.3, ge=0.1, le=0.7)
    photo_style: Literal['Natural photo', 'Polished'] = 'Natural photo'
    photo_finish: Literal['Off', 'Light', 'Film'] = 'Light'
    combine: bool = True
    references: bool = True
    realism: float = Field(default=0.6, ge=0, le=1)
    personal: float = Field(default=0, ge=0, le=1)


class EditRequest(BaseModel):
    engine: str = 'kontext'

    @field_validator('engine')
    @classmethod
    def known_engine(cls, value):
        return model_choice(value, LOCAL_EDITORS)

    image: str = Field(max_length=40_000_000)
    mask: str | None = Field(default=None, max_length=40_000_000)
    prompt: str = Field(min_length=1, max_length=6000)
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    steps: int = Field(default=28, ge=4, le=50)
    guidance: float = Field(default=2.5, ge=1, le=10)
    smart: bool = False


class SketchRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=6000)
    size: str


class FavoriteRequest(BaseModel):
    name: str = Field(min_length=5, max_length=200)
    favorite: bool = True


class MemoryRequest(BaseModel):
    action: Literal['forget', 'forget_all', 'reset_strength', 'teach']
    phrase: str = Field(default='', max_length=200)
    means: str = Field(default='', max_length=500)


class PersonalLoraRequest(BaseModel):
    action: Literal['train', 'nightly']
    if_needed: bool = False
    enabled: bool = True


class KritaRequest(BaseModel):
    action: Literal['launch', 'open', 'import', 'prompt', 'undo', 'stop', 'save', 'new_canvas']
    text: str = Field(default='', max_length=6000)
    image: str | None = Field(default=None, max_length=40_000_000)
