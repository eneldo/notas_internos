from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class RatingCreate(BaseModel):
    estudiante_nombre: str = Field(..., min_length=3, max_length=200)
    estudiante_documento: str = Field(..., min_length=3, max_length=50)
    universidad: str = Field(..., min_length=2, max_length=200)
    semestre: str = Field(..., min_length=1, max_length=50)
    mes: str = Field(..., min_length=1, max_length=30)

    rotation_id: int = Field(..., ge=1)

    cognitiva: float = Field(..., ge=0.0, le=5.0)
    aptitudinal: float = Field(..., ge=0.0, le=5.0)
    actitudinal: float = Field(..., ge=0.0, le=5.0)
    evaluacion: float = Field(..., ge=0.0, le=5.0)
    cpc: float = Field(..., ge=0.0, le=5.0)

    porcentaje_fallas: float = Field(0.0, ge=0.0, le=100.0)

    especialista_nombre: str = Field(..., min_length=3, max_length=200)
    especialista_documento: str = Field(..., min_length=3, max_length=50)
    coordinador_nombre: str = Field(..., min_length=3, max_length=200)
    estudiante_firma_nombre: str = Field(..., min_length=3, max_length=200)

    comentarios: Optional[str] = Field("", max_length=2000)

class RatingOut(BaseModel):
    id: int
    nota_definitiva: float
    nota_en_letras: str
    pierde_por_fallas: int
    is_closed: bool
    is_void: bool
    created_at: datetime
    class Config:
        from_attributes = True

class RotationCreate(BaseModel):
    nombre: str = Field(..., min_length=2, max_length=120)
