import math
from typing import Any

from pydantic import BaseModel, Field, computed_field

from str_cad.geometry.assembly import REGION_NAMES


class CaseParamsError(ValueError):
    pass


class Run(BaseModel):
    end_time: int = 5000
    write_interval: int = 500
    cores: int = 28
    verify: bool = False
    verify_steps: int = 5


def _default_patch_roles() -> dict[str, str]:
    return {
        region: "slip" if region == "liquidSurface" else "wall"
        for region in REGION_NAMES
    }


class CaseParams(BaseModel):
    rpm: float
    viscosity_m2_s: float = 1e-6
    run: Run = Run()
    patch_roles: dict[str, str] = Field(default_factory=_default_patch_roles)

    @computed_field
    @property
    def omega_rad_s(self) -> float:
        return self.rpm * 2 * math.pi / 60

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any) -> "CaseParams":
        instance = super().model_validate(obj, *args, **kwargs)
        instance._check_cross_fields()
        return instance

    def _check_cross_fields(self) -> None:
        if self.rpm < 0:
            raise CaseParamsError("rpm must not be negative")

        allowed_roles = {"wall", "slip", "inlet", "outlet"}
        if any(role not in allowed_roles for role in self.patch_roles.values()):
            raise CaseParamsError("patch roles must be wall, slip, inlet, or outlet")
