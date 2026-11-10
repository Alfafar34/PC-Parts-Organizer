"""Internal storage unit classification (T17.9-R2).

Pure; no I/O. Distinguishes confirmed / possible / contradictory connectivity
so unknown data never becomes a favorable certainty.

Demands (per unit):
- sata: 'confirmed' (verified SATA/ATA consumer), 'possible' (could need a
  motherboard SATA data port), 'none' (confirmed non-consumer).
- bay25 / bay35: 'confirmed' (verified need), 'possible' (could need),
  'none' (confirmed no need for that bay size).
- m2: 'confirmed' (verified m2), 'possible' (could be M.2), 'none'.

Status (reporting):
- confirmed_sata_data_consumer
- confirmed_m2_device
- confirmed_pcie_addin
- confirmed_other_non_bay_device
- confirmed_bay_only_device (2.5/3.5 verified, SATA confirmed none)
- indeterminate_storage
- contradictory_storage_data
"""
from __future__ import annotations

from dataclasses import dataclass

from .engine import attr_low_confidence, attr_verified, get_attr

CONFIRMED_SATA = "confirmed_sata_data_consumer"
CONFIRMED_M2 = "confirmed_m2_device"
CONFIRMED_ADDIN = "confirmed_pcie_addin"
CONFIRMED_OTHER_NON_BAY = "confirmed_other_non_bay_device"
CONFIRMED_BAY_ONLY = "confirmed_bay_only_device"
INDETERMINATE = "indeterminate_storage"
CONTRADICTORY = "contradictory_storage_data"


def _is_verified(attr) -> bool:
    return attr is not None and attr_verified(attr) and not attr_low_confidence(attr)


@dataclass(frozen=True)
class StorageClassification:
    component_id: str
    status: str
    form_factor: str | None
    ff_verified: bool
    interface: str | None
    iface_verified: bool
    command_set: str | None
    cmd_verified: bool
    contradictory: bool
    sata: str  # confirmed|possible|none
    bay25: str
    bay35: str
    m2: str  # confirmed|possible|none
    reasons: tuple = ()


def classify_unit(component_id: str, profile) -> StorageClassification:
    ff = get_attr(profile, "storage_form_factor")
    iface = get_attr(profile, "storage_interface")
    cmd = get_attr(profile, "storage_command_set")
    ffv = ff.value if ff is not None else None
    iv = iface.value if iface is not None else None
    cv = cmd.value if cmd is not None else None
    ff_ok = _is_verified(ff)
    if_ok = _is_verified(iface)
    cmd_ok = _is_verified(cmd)

    contradictory = (
        isinstance(iv, str)
        and isinstance(cv, str)
        and iv in ("sata", "pcie")
        and cv in ("ata", "nvme")
        and (iv, cv) not in (("sata", "ata"), ("pcie", "nvme"))
    )
    if contradictory:
        return StorageClassification(
            component_id=component_id, status=CONTRADICTORY,
            form_factor=ffv, ff_verified=ff_ok, interface=iv,
            iface_verified=if_ok, command_set=cv, cmd_verified=cmd_ok,
            contradictory=True, sata="possible", bay25="possible",
            bay35="possible", m2="possible",
            reasons=("interface_command_set_contradiction",),
        )

    # M.2 dimension: relevance is declared value; verification gates certainty.
    if ff is not None and ffv == "m2" and ff_ok:
        m2 = "confirmed"
    elif ff is not None and ffv == "m2":
        m2 = "possible"  # declared but not verified
    elif ff is not None and ff_ok and ffv in ("2_5_in", "3_5_in", "pcie_addin", "other"):
        m2 = "none"
    else:
        # missing or unverified non-m2: cannot exclude M.2
        m2 = "possible"

    # SATA demand
    if m2 == "confirmed":
        sata = "none"  # M.2 uses slot, never motherboard SATA data port
    elif ff is not None and ffv == "pcie_addin" and ff_ok:
        sata = "none"  # confirmed add-in card
    elif iv == "sata" and if_ok and cv == "ata" and cmd_ok:
        if m2 == "none":
            sata = "confirmed"
        else:
            sata = "possible"  # could be M.2 SATA vs 2.5/3.5 SATA
    elif iv == "pcie" and if_ok and cv == "nvme" and cmd_ok:
        sata = "none"
    else:
        sata = "possible"

    # Bay demands
    if ff is not None and ffv == "2_5_in" and ff_ok:
        bay25, bay35 = "confirmed", "none"
    elif ff is not None and ffv == "3_5_in" and ff_ok:
        bay25, bay35 = "none", "confirmed"
    elif ff is not None and ffv in ("m2", "pcie_addin") and ff_ok:
        bay25, bay35 = "none", "none"
    elif ff is not None and ffv == "other" and ff_ok:
        # 'other' is explicitly not 2.5/3.5/m2/addin: no 2.5/3.5 bay need.
        bay25, bay35 = "none", "none"
    else:
        # missing or unverified: could need either bay size
        bay25, bay35 = "possible", "possible"

    # Overall status
    if m2 == "confirmed":
        status = CONFIRMED_M2
    elif ff is not None and ffv == "pcie_addin" and ff_ok:
        status = CONFIRMED_ADDIN
    elif sata == "confirmed":
        status = CONFIRMED_SATA
    elif ff is not None and ffv in ("2_5_in", "3_5_in") and ff_ok and sata == "none":
        status = CONFIRMED_BAY_ONLY
    elif ff is not None and ffv == "other" and ff_ok and sata == "none":
        status = CONFIRMED_OTHER_NON_BAY
    else:
        status = INDETERMINATE

    return StorageClassification(
        component_id=component_id, status=status,
        form_factor=ffv, ff_verified=ff_ok, interface=iv,
        iface_verified=if_ok, command_set=cv, cmd_verified=cmd_ok,
        contradictory=False, sata=sata, bay25=bay25, bay35=bay35, m2=m2,
    )


def is_collection_complete(attr) -> bool:
    """Defense-in-depth completeness gate.

    TechnicalAttribute validation already enforces the complete contract
    (verified + high + evidence + date + scope on eligible keys), and every
    engine evaluation runs through validated profiles. This helper re-checks
    the full contract so direct rule invocations cannot treat a hand-built
    complete flag as proven exhaustiveness.
    """
    if attr is None:
        return False
    if getattr(attr, "collection_completeness", "unknown") != "complete":
        return False
    if not (attr_verified(attr) and not attr_low_confidence(attr)):
        return False
    if getattr(attr, "confidence", None) != "high":
        return False
    if not getattr(attr, "evidence_ref", None) or not getattr(attr, "verified_at", None):
        return False
    return bool(getattr(attr, "completeness_scope", None))


def classify_all(ctx) -> dict[str, StorageClassification]:
    out: dict[str, StorageClassification] = {}
    for st in ctx.components_by_category.get("Storage", []):
        out[st.id] = classify_unit(st.id, ctx.profiles_by_component_id.get(st.id))
    return out
