from typing import Any

from pydantic import BaseModel, computed_field, model_validator


class SchemaError(ValueError):
    pass


class Tank(BaseModel):
    diameter_m: float
    height_m: float
    bottom: str


class Liquid(BaseModel):
    height_m: float


class Baffles(BaseModel):
    count: int
    width_m: float
    height_m: float
    arrangement: str


class Shaft(BaseModel):
    central: bool


class Impellers(BaseModel):
    count: int
    type: str
    blades: int
    diameter_ratio: float
    blade_height_m: float | None = None
    blade_length_m: float | None = None
    lowest_clearance_m: float
    inter_impeller_clearance_m: float


class STRParams(BaseModel):
    family: str
    tank: Tank
    liquid: Liquid
    baffles: Baffles
    shaft: Shaft
    impellers: Impellers

    @computed_field
    @property
    def impeller_diameter_m(self) -> float:
        return self.tank.diameter_m * self.impellers.diameter_ratio

    @model_validator(mode="after")
    def _fill_blade_dimensions(self) -> "STRParams":
        diameter = self.impeller_diameter_m
        if self.impellers.blade_length_m is None:
            self.impellers.blade_length_m = diameter / 4
        if self.impellers.blade_height_m is None:
            self.impellers.blade_height_m = diameter / 5
        return self

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "STRParams":
        instance = super().model_validate(obj, *args, **kwargs)
        instance._check_cross_fields()
        return instance

    def _check_cross_fields(self) -> None:
        if self.liquid.height_m > self.tank.height_m:
            raise SchemaError("liquid height must not exceed tank height")

        highest_impeller_m = (
            self.impellers.lowest_clearance_m
            + (self.impellers.count - 1)
            * self.impellers.inter_impeller_clearance_m
        )
        if highest_impeller_m >= self.liquid.height_m:
            raise SchemaError("impellers must fit below the liquid height")

        diameter = self.impeller_diameter_m
        expected_length = diameter / 4
        expected_height = diameter / 5
        if abs(self.impellers.blade_length_m - expected_length) > 0.1 * expected_length:
            raise SchemaError("blade length must be within 10% of D/4")
        if abs(self.impellers.blade_height_m - expected_height) > 0.1 * expected_height:
            raise SchemaError("blade height must be within 10% of D/5")
