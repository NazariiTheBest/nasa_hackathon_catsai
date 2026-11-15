"""Soil properties used by the water balance and the erosion index."""

from __future__ import annotations

import math
from dataclasses import dataclass

from fieldshift.settings import EngineConfig

SOC_TO_OM = 1.724  # van Bemmelen factor: organic matter = organic carbon x 1.724
K_US_TO_SI = 0.1317


def saxton_rawls(sand_pct: float, clay_pct: float, om_pct: float) -> tuple[float, float]:
    """Wilting point and field capacity as volumetric fractions (Saxton & Rawls 2006)."""
    s, c, om = sand_pct / 100, clay_pct / 100, min(om_pct, 8.0)
    t1500 = -0.024 * s + 0.487 * c + 0.006 * om + 0.005 * s * om - 0.013 * c * om + 0.068 * s * c + 0.031
    wilting = t1500 + (0.14 * t1500 - 0.02)
    t33 = -0.251 * s + 0.195 * c + 0.011 * om + 0.006 * s * om - 0.027 * c * om + 0.452 * s * c + 0.299
    capacity = t33 + (1.283 * t33**2 - 0.374 * t33 - 0.015)
    return wilting, capacity


def derive_awc_mm_per_m(sand_pct: float, clay_pct: float, soc_pct: float) -> float:
    """Plant-available water capacity in mm per metre of soil."""
    wilting, capacity = saxton_rawls(sand_pct, clay_pct, soc_pct * SOC_TO_OM)
    return max(capacity - wilting, 0.02) * 1000


def derive_k_factor(sand_pct: float, clay_pct: float, soc_pct: float) -> float:
    """Soil erodibility in SI units, t ha h / (ha MJ mm), by the EPIC equation (Williams 1995)."""
    silt_pct = max(100 - sand_pct - clay_pct, 0.0)
    sn1 = 1 - sand_pct / 100
    f_sand = 0.2 + 0.3 * math.exp(-0.0256 * sand_pct * (1 - silt_pct / 100))
    f_clay_silt = (silt_pct / max(clay_pct + silt_pct, 1e-6)) ** 0.3
    f_carbon = 1 - 0.25 * soc_pct / (soc_pct + math.exp(3.72 - 2.95 * soc_pct))
    f_high_sand = 1 - 0.7 * sn1 / (sn1 + math.exp(-5.51 + 22.9 * sn1))
    return f_sand * f_clay_silt * f_carbon * f_high_sand * K_US_TO_SI


@dataclass
class SoilProps:
    awc_mm_per_m: float
    awc_status: str  # supplied | derived | assumed
    k_factor: float | None
    k_status: str  # supplied | derived | unavailable
    slope_pct: float | None = None
    elevation_m: float | None = None
    clay_pct: float | None = None
    sand_pct: float | None = None
    soc_pct: float | None = None
    ph: float | None = None

    @property
    def derived_or_assumed(self) -> int:
        """Number of inputs that were derived or assumed instead of supplied."""
        return int(self.awc_status != "supplied") + int(self.k_status == "derived")


def resolve_soil(static: dict | None, cfg: EngineConfig) -> SoilProps:
    """Soil properties for a unit; derived from texture where not supplied, assumed with no data."""
    if not static:
        return SoilProps(awc_mm_per_m=cfg.default_awc_mm_per_m, awc_status="assumed", k_factor=None, k_status="unavailable")
    sand, clay, soc = static.get("sand_pct"), static.get("clay_pct"), static.get("soc_pct")
    has_texture = None not in (sand, clay, soc)

    if static.get("awc_mm_per_m") is not None:
        awc, awc_status = float(static["awc_mm_per_m"]), "supplied"
    elif has_texture:
        awc, awc_status = derive_awc_mm_per_m(sand, clay, soc), "derived"
    else:
        awc, awc_status = cfg.default_awc_mm_per_m, "assumed"

    if static.get("k_factor") is not None:
        k, k_status = float(static["k_factor"]), "supplied"
    elif has_texture:
        k, k_status = derive_k_factor(sand, clay, soc), "derived"
    else:
        k, k_status = None, "unavailable"

    return SoilProps(
        awc_mm_per_m=round(awc, 1), awc_status=awc_status,
        k_factor=None if k is None else round(k, 4), k_status=k_status,
        slope_pct=static.get("slope_pct"), elevation_m=static.get("elevation_m"),
        clay_pct=clay, sand_pct=sand, soc_pct=soc, ph=static.get("ph"),
    )


def terrain_factor(soil: SoilProps, cfg: EngineConfig) -> tuple[float, bool]:
    """Multiplier (0.4-1.0) for erosion exposure, and whether it fell back to rainfall alone."""
    if soil.slope_pct is None or soil.k_factor is None:
        return cfg.neutral_terrain_factor, True
    factor = 0.4 + 0.3 * min(soil.slope_pct / 5.0, 1.0) + 0.3 * min(soil.k_factor / 0.05, 1.0)
    return min(max(factor, 0.4), 1.0), False
