from typing import Any, Literal

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
    width_m: float | None = None
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


class Sparger(BaseModel):
    ring_diameter_m: float | None = None
    n_holes: int | None = None


class Operating(BaseModel):
    rpm: float | None = None
    gas_flow_vvm: float | None = None
    sparger: Sparger | None = None


class STRParams(BaseModel):
    family: str
    physics: Literal["single_phase", "two_phase"] = "single_phase"
    tank: Tank
    liquid: Liquid
    baffles: Baffles
    shaft: Shaft
    impellers: Impellers
    operating: Operating | None = None

    @computed_field
    @property
    def impeller_diameter_m(self) -> float:
        return self.tank.diameter_m * self.impellers.diameter_ratio

    def derived(self) -> dict:
        diameter = self.impeller_diameter_m
        return {
            "blade_length_m": self.impellers.blade_length_m,  # geometry.internals blade size
            "blade_height_m": self.impellers.blade_height_m,  # geometry.internals blade size
            "shaft_radius_m": max(0.03, diameter / 20),  # geometry.internals build_shaft
            "hub_radius_m": diameter / 12,  # geometry.internals build_impellers
            "baffle_width_m": self.baffles.width_m,  # geometry.baffles
            "mrf_rotor_radius_m": 0.55 * diameter,  # ofcase.mrf rotor cell zone
            "mesh_refinement_radius_m": 0.65 * diameter,  # meshcase snappy refinement region
        }

    @model_validator(mode="after")
    def _fill_blade_dimensions(self) -> "STRParams":
        diameter = self.impeller_diameter_m
        if self.impellers.blade_length_m is None:
            self.impellers.blade_length_m = diameter / 4
        if self.impellers.blade_height_m is None:
            self.impellers.blade_height_m = diameter / 5
        return self

    @model_validator(mode="after")
    def _fill_baffle_width(self) -> "STRParams":
        if self.baffles.width_m is None:
            self.baffles.width_m = self.tank.diameter_m / 12
        return self

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "STRParams":
        instance = super().model_validate(obj, *args, **kwargs)
        instance._check_cross_fields()
        return instance

    def _check_cross_fields(self) -> None:
        if self.liquid.height_m > self.tank.height_m:
            raise SchemaError("liquid height must not exceed tank height")

        if self.physics == "two_phase":
            if self.operating is None:
                raise SchemaError(
                    "two_phase physics requires an `operating` block with a usable gas input"
                )
            has_gas_flow = (
                self.operating.gas_flow_vvm is not None
                and self.operating.gas_flow_vvm > 0
            )
            sparger = self.operating.sparger
            has_sparger = (
                sparger is not None
                and sparger.ring_diameter_m is not None
                and sparger.ring_diameter_m > 0
                and (sparger.n_holes is None or sparger.n_holes > 0)
            )
            if not has_gas_flow and not has_sparger:
                raise SchemaError(
                    "two_phase physics requires a usable gas input: "
                    "operating.gas_flow_vvm > 0 or operating.sparger.ring_diameter_m > 0"
                )

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
