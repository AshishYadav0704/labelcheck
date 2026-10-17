"""Request / response schemas shared by the API, the services and the clients."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal[
    "instant_noodles", "chips_namkeen", "biscuits_cookies", "chocolate_confectionery",
    "sugary_drink", "fruit_juice", "energy_drink", "breakfast_cereal", "health_drink_powder",
    "dairy_drink", "yogurt_dessert", "ice_cream", "bread_bakery", "sauce_spread", "ready_meal",
    "processed_meat", "sweets_mithai", "cooking_oil_fat", "other",
]
CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]

Condition = Literal[
    "diabetes", "hypertension", "heart_disease", "kidney_disease", "pregnancy",
    "pku", "gout", "asthma", "thyroid_condition", "weight_loss",
]
AgeGroup = Literal["child", "teen", "adult", "senior"]
Language = Literal["en", "hi"]
Diet = Literal["any", "vegetarian", "eggetarian", "vegan", "jain"]
VegMark = Literal["veg", "non_veg"]


class Nutrition(BaseModel):
    """Nutrition per 100 g (solids) or per 100 ml (drinks)."""

    model_config = ConfigDict(extra="ignore")

    energy_kcal: Optional[float] = Field(default=None, ge=0, le=1000)
    fat_g: Optional[float] = Field(default=None, ge=0, le=100)
    saturated_fat_g: Optional[float] = Field(default=None, ge=0, le=100)
    trans_fat_g: Optional[float] = Field(default=None, ge=0, le=100)
    carbohydrates_g: Optional[float] = Field(default=None, ge=0, le=100)
    sugars_g: Optional[float] = Field(default=None, ge=0, le=100)
    added_sugars_g: Optional[float] = Field(default=None, ge=0, le=100)
    fiber_g: Optional[float] = Field(default=None, ge=0, le=100)
    protein_g: Optional[float] = Field(default=None, ge=0, le=100)
    salt_g: Optional[float] = Field(default=None, ge=0, le=100)
    sodium_mg: Optional[float] = Field(default=None, ge=0, le=40000)

    @model_validator(mode="after")
    def _fill_salt_sodium(self) -> "Nutrition":
        # Salt (g) = sodium (g) x 2.5. Labels in India usually give sodium in mg.
        if self.salt_g is None and self.sodium_mg is not None:
            self.salt_g = round(self.sodium_mg * 2.5 / 1000, 3)
        elif self.sodium_mg is None and self.salt_g is not None:
            self.sodium_mg = round(self.salt_g * 1000 / 2.5, 1)
        return self


class ProductData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = Field(default="Unknown product", max_length=200)
    brand: Optional[str] = Field(default=None, max_length=120)
    barcode: Optional[str] = Field(default=None, max_length=32)
    category: Category = "other"
    is_liquid: bool = False
    net_quantity: Optional[str] = Field(default=None, max_length=60)
    serving_size_g: Optional[float] = Field(default=None, gt=0, le=2000)
    ingredients_text: Optional[str] = Field(default=None, max_length=6000)
    ingredients: list[str] = Field(default_factory=list, max_length=150)
    additive_codes: list[str] = Field(default_factory=list, max_length=80)
    allergens_declared: list[str] = Field(default_factory=list, max_length=30)
    traces: list[str] = Field(default_factory=list, max_length=30)
    nutrition: Nutrition = Field(default_factory=Nutrition)
    fruit_veg_nuts_percent: Optional[float] = Field(default=None, ge=0, le=100)
    veg_mark: Optional[VegMark] = None  # FSSAI green dot (veg) or brown triangle (non-veg)
    image_url: Optional[str] = Field(default=None, max_length=500)
    source: Literal["label_photo", "label_text", "barcode", "manual"] = "manual"
    read_by: Optional[Literal["claude", "gemini", "ocr", "text", "open_food_facts"]] = None
    reviewed: bool = False  # the user checked/edited the values before analysis
    extraction_confidence: Optional[Literal["high", "medium", "low"]] = None
    extraction_notes: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("barcode")
    @classmethod
    def _digits_only(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        digits = "".join(ch for ch in v if ch.isdigit())
        return digits or None


class Profile(BaseModel):
    """Optional personal context. Never stored on the server."""

    model_config = ConfigDict(extra="ignore")

    age_group: AgeGroup = "adult"
    diet: Diet = "any"
    conditions: list[Condition] = Field(default_factory=list, max_length=10)
    allergies: list[str] = Field(default_factory=list, max_length=15)
    language: Language = "en"


class AnalyzeProductRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product: ProductData
    profile: Profile = Field(default_factory=Profile)
    explain: bool = True


class LabelTextRequest(BaseModel):
    """Label text typed or pasted by the user (or copied from another app)."""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(min_length=10, max_length=12000)
    name: Optional[str] = Field(default=None, max_length=200)
    brand: Optional[str] = Field(default=None, max_length=120)
