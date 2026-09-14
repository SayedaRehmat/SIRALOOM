from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass


VALID_MODELS = {"AD", "AR", "X_LINKED", "MITOCHONDRIAL", "DE_NOVO", "UNKNOWN"}
VALID_STATUS = {"AFFECTED", "UNAFFECTED", "UNKNOWN"}

@dataclass(frozen=True)
class FamilyObservation:
    member_id: str
    sex: str | None
    affected_status: str
    genotype: str | None
    zygosity: str | None

def normalize_model(model: str) -> str:
    value = model.strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {"AUTOSOMAL_DOMINANT":"AD", "AUTOSOMAL_RECESSIVE":"AR", "X_LINKED":"X_LINKED", "XL":"X_LINKED", "MITO":"MITOCHONDRIAL", "MT":"MITOCHONDRIAL", "DE_NOVO":"DE_NOVO"}
    value = aliases.get(value, value)
    if value not in VALID_MODELS:
        raise ValueError(f"Unsupported inheritance model: {model}")
    return value

def normalize_genotype(genotype: str | None) -> str | None:
    if genotype is None: return None
    g = genotype.strip().upper().replace(" ", "")
    if g in {"", ".", "./.", ".|."}: return None
    return g

def carrier_state(obs: FamilyObservation) -> str:
    g = normalize_genotype(obs.genotype)
    z = (obs.zygosity or "").upper()
    if g in {"1/1", "1|1", "HOM_ALT", "HOMOZYGOUS_ALT"} or z in {"HOM_ALT", "HOMOZYGOUS_ALT"}: return "BIALLELIC"
    if g in {"0/1", "1/0", "0|1", "1|0", "HET", "HETEROZYGOUS", "CARRIER"} or z in {"HET", "HETEROZYGOUS", "CARRIER"}: return "HET"
    if g in {"1", "HEMI", "HEMIZYGOUS"} or z in {"HEMI", "HEMIZYGOUS"}: return "HEMI"
    if g in {"0/0", "0|0", "HOM_REF", "HOMOZYGOUS_REF"} or z in {"HOM_REF", "HOMOZYGOUS_REF"}: return "REF"
    return "UNKNOWN"

def assess_model(model: str, observations: list[FamilyObservation]) -> dict:
    model = normalize_model(model)
    known = [o for o in observations if o.affected_status in VALID_STATUS and carrier_state(o) != "UNKNOWN"]
    if not known:
        return {"model": model, "status":"INSUFFICIENT_DATA", "score":0, "rationale":"No interpretable genotype/phenotype observations are available."}
    supporting = contradictory = 0
    reasons=[]
    for o in known:
        state=carrier_state(o); affected=o.affected_status == "AFFECTED"
        if model == "AD":
            if affected and state in {"HET","HEMI","BIALLELIC"}: supporting += 1; reasons.append(f"{o.member_id}: affected with variant")
            elif not affected and state == "REF": supporting += 1; reasons.append(f"{o.member_id}: unaffected without observed variant")
            elif not affected and state in {"HET","HEMI","BIALLELIC"}: contradictory += 1; reasons.append(f"{o.member_id}: unaffected despite observed variant")
        elif model == "AR":
            if affected and state == "BIALLELIC": supporting += 1; reasons.append(f"{o.member_id}: affected with biallelic state")
            elif not affected and state in {"HET","REF"}: supporting += 1; reasons.append(f"{o.member_id}: unaffected compatible with recessive model")
            elif affected and state == "HET": contradictory += 1; reasons.append(f"{o.member_id}: affected heterozygous state is not sufficient for AR")
        elif model == "X_LINKED":
            if affected and state in {"HEMI","BIALLELIC","HET"}: supporting += 1; reasons.append(f"{o.member_id}: affected compatible with X-linked state")
            elif not affected and state == "REF": supporting += 1; reasons.append(f"{o.member_id}: unaffected without observed variant")
            elif not affected and state == "HEMI": contradictory += 1; reasons.append(f"{o.member_id}: unaffected hemizygous variant requires review")
        elif model == "MITOCHONDRIAL":
            if affected and state in {"HET","BIALLELIC","HEMI"}: supporting += 1; reasons.append(f"{o.member_id}: affected with mitochondrial variant")
            elif not affected and state == "REF": supporting += 1; reasons.append(f"{o.member_id}: unaffected without observed variant")
        elif model == "DE_NOVO":
            if affected and state in {"HET","HEMI","BIALLELIC"}: supporting += 1; reasons.append(f"{o.member_id}: affected proband/case carrier")
            elif not affected and state == "REF": supporting += 1; reasons.append(f"{o.member_id}: unaffected reference-compatible member")
    if contradictory: status="CONTRADICTED"
    elif supporting >= 2: status="CONSISTENT"
    else: status="INSUFFICIENT_DATA"
    score=max(0,min(100, 60 + 10*supporting - 30*contradictory)) if status != "INSUFFICIENT_DATA" else 25
    return {"model":model,"status":status,"score":score,"supporting_observations":supporting,"contradictory_observations":contradictory,"rationale":"; ".join(reasons) or "No model-specific interpretation available."}

def fingerprint(observations: list[FamilyObservation]) -> str:
    payload=[o.__dict__ for o in sorted(observations,key=lambda x:x.member_id)]
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(",",":" )).encode()).hexdigest()
