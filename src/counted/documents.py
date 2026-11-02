"""The three artifacts Counted leaves behind, rendered from templates (no model writes these):

1. Certifier statement draft  -> the medical examiner / physician reviews and signs (FEMA accepts a signed
                                  certifier statement in place of an amended certificate).
2. Family FEMA packet          -> what to gather and file for Funeral Assistance, in the family's language.
3. Surveillance record         -> one row for the county's disaster-mortality surveillance (CDC fields).
"""

from __future__ import annotations

from datetime import date

from .schemas import CaseFacts, DisasterContext, Label, Mechanism, PanelResult

FEMA_GUIDE = "https://www.fema.gov/sites/default/files/documents/fema_ia_qrg_help_with_funerals_and_burials_20250715.pdf"
CDC_GUIDE = "https://www.cdc.gov/nchs/data/nvss/vsrg/vsrg01.pdf"
NAME_PAPER = "https://pubmed.ncbi.nlm.nih.gov/37527356/"

# Indirect deaths whose manner is usually natural. "How injury occurred" (Item 43) may not be available for a natural
# death, so the CDC guide and the National Association of Medical Examiners (2023) put the disaster in Part II, by name.
_PART_II = {
    Mechanism.POWER_DEPENDENT_DEVICE: "Loss of electric power to a medical device",
    Mechanism.HEALTHCARE_DISRUPTION: "Interruption of medical care",
    Mechanism.CHRONIC_EXACERBATION: "Exacerbation of chronic illness under disaster conditions",
    Mechanism.STRESS_CARDIAC: "Physical and emotional stress",
    Mechanism.UTILITY_LOSS: "Loss of utilities",
    Mechanism.INFECTION: "Infection from floodwater or a disaster injury",
}


def _disaster(facts: CaseFacts, ctx: DisasterContext) -> str:
    name = facts.disaster_name or ctx.declaration_title or "the declared disaster"
    return f"{name} ({ctx.declaration})" if ctx.declaration else name


def part_ii(facts: CaseFacts, ctx: DisasterContext, verdict) -> str:
    """Draft Part II line for a natural-manner indirect death, naming the disaster and its month; empty otherwise."""
    phrase = _PART_II.get(verdict.mechanism) if verdict.label == Label.INDIRECT else None
    if not phrase:
        return ""
    name = facts.disaster_name or ctx.declaration_title or "the declared disaster"
    when = ctx.incident_begin or facts.date_of_death
    return f"{phrase} during {name}" + (f" ({when:%B %Y})" if when else "")


def certifier_statement(facts: CaseFacts, ctx: DisasterContext, panel: PanelResult) -> str:
    v = panel.final
    d = _disaster(facts, ctx)
    if v.label in (Label.DIRECT, Label.INDIRECT):
        finding = f"In my opinion this death was **{v.label.value}ly caused** by {d}."
        fema = f"This death was {v.label.value}ly caused by {d}."
    elif v.label == Label.NOT_RELATED:
        finding = f"The information gathered does **not** support attributing this death to {d}."
        fema = "Not applicable."
    else:
        finding = "Counted could **not** reach a determination. Medicolegal review is required."
        fema = "Not applicable until reviewed."
    evidence = "\n".join(f"- \"{e.quote}\" ({e.mechanism.value.replace('_', ' ')})" for e in facts.evidence if e.quote) or "- none recorded"
    seats = {"CDC decision tree": panel.rules, "Examiner (Claude)": panel.examiner,
             "Examiner (Amazon Nova)": panel.second_examiner, "Adjudicator": panel.adjudicator}
    panel_lines = "\n".join(f"| {k} | {s.label.value} | {s.confidence:.2f} |" for k, s in seats.items() if s)
    return f"""# DRAFT: Certifier statement on disaster relationship

> **Draft prepared by Counted for review. Not a death certificate. Not valid until reviewed and signed by the
> certifying medical examiner, coroner or physician.**

| | |
|---|---|
| Case | {facts.case_id} |
| Decedent | age {facts.decedent_age or "unknown"}, {facts.decedent_sex or "sex not stated"} |
| Date of death | {facts.date_of_death or "unknown"} |
| Location | {facts.county or "?"} County, {facts.state or "?"} |
| Disaster | {d}; incident period {ctx.incident_begin} to {ctx.incident_end or "ongoing"} |
| NWS warnings in force | {", ".join(ctx.nws_warnings[:5]) or "none found"} |
| Cause on certificate (per family) | {facts.certificate_cause or "not known"} |

## Determination (CDC 2017 Reference Guide)
{finding}

**Causal chain:** {v.causal_chain}

**Proposed "How injury occurred" (Item 43):** {v.how_injury_occurred or "n/a"}

**Proposed Part II, other significant conditions** (use if the manner of death is natural): {part_ii(facts, ctx, v) or "n/a"}

**Proposed wording for FEMA Funeral Assistance** (FEMA rejects "may have been caused by"):
> {fema}

## Family account (verbatim)
{evidence}

## Panel
| Seat | Determination | Confidence |
|---|---|---|
{panel_lines}

Unanimous: {"yes" if panel.unanimous else "no, adjudicated"}. Open questions: {"; ".join(v.missing) or "none"}.

## Certification
I have reviewed the information above. [ ] I concur  [ ] I do not concur  [ ] Amended certificate to follow

Signature: ______________________  Name / title: ______________________  Date: __________

<sub>Sources: CDC/NCHS Reference Guide ({CDC_GUIDE}); National Association of Medical Examiners position paper on disaster-related deaths, 2023 ({NAME_PAPER}); FEMA Help with Funerals and Burials, July 2025 ({FEMA_GUIDE}); OpenFEMA; NWS archive.</sub>
"""


_PACKET = {
    "en": {
        "title": "Funeral Assistance: what to gather",
        "intro": "We are very sorry for your loss. FEMA may help with funeral costs when a death was caused directly or indirectly by a declared disaster.",
        "ia_yes": "Good news: FEMA Individual Assistance was approved for {county} County under {decl}. Funeral Assistance is part of that program.",
        "ia_no": "We could not confirm Individual Assistance for {county} County yet. Check DisasterAssistance.gov or call 1-800-621-3362; declarations are often expanded later.",
        "items": [
            "Death certificate, OR the signed certifier statement Counted drafted (ask the medical examiner or doctor to review and sign it)",
            "Funeral home contract or itemized receipts",
            "Proof of any other help received (insurance, burial societies, donations)",
            "The decedent's and applicant's names and addresses",
        ],
        "apply": "Apply at DisasterAssistance.gov or call 1-800-621-3362. If FEMA says no, you can appeal in writing using the appeal letter below.",
        "appeal_h": "Appeal letter (fill in and sign)",
        "appeal": "I am appealing FEMA's decision on Funeral Assistance for {name}, who died on {dod} in {county} County. The enclosed statement from the certifier states the death was {label}ly caused by {disaster}: {chain}. I ask FEMA to reconsider.",
        "note": "Counted cannot promise any outcome. FEMA makes the decision.",
    },
    "es": {
        "title": "Asistencia funeraria: qué reunir",
        "intro": "Lamentamos mucho su pérdida. FEMA puede ayudar con los gastos funerarios cuando una muerte fue causada directa o indirectamente por un desastre declarado.",
        "ia_yes": "Buenas noticias: FEMA aprobó la Asistencia Individual para el condado de {county} bajo {decl}. La Asistencia Funeraria es parte de ese programa.",
        "ia_no": "Todavía no pudimos confirmar la Asistencia Individual para el condado de {county}. Consulte DisasterAssistance.gov o llame al 1-800-621-3362; las declaraciones a menudo se amplían después.",
        "items": [
            "Certificado de defunción, O la declaración firmada del certificador que Counted preparó (pida al médico forense o al doctor que la revise y firme)",
            "Contrato de la funeraria o recibos detallados",
            "Comprobante de cualquier otra ayuda recibida (seguros, donaciones)",
            "Nombres y direcciones del fallecido y del solicitante",
        ],
        "apply": "Solicite en DisasterAssistance.gov o llame al 1-800-621-3362. Si FEMA dice que no, puede apelar por escrito con la carta de abajo.",
        "appeal_h": "Carta de apelación (complete y firme)",
        "appeal": "Apelo la decisión de FEMA sobre la Asistencia Funeraria para {name}, quien falleció el {dod} en el condado de {county}. La declaración adjunta del certificador indica que la muerte fue causada {label_es} por {disaster}: {chain}. Pido a FEMA que reconsidere.",
        "note": "Counted no puede prometer ningún resultado. FEMA toma la decisión.",
    },
}


def family_packet(facts: CaseFacts, ctx: DisasterContext, panel: PanelResult) -> str:
    t = _PACKET.get(facts.language if facts.language in _PACKET else "en")
    v = panel.final
    county = facts.county or "your"
    lines = [f"# {t['title']}", "", t["intro"], ""]
    lines.append((t["ia_yes"] if ctx.individual_assistance else t["ia_no"]).format(county=county, decl=ctx.declaration or ""))
    lines += ["", *[f"- [ ] {i}" for i in t["items"]], "", t["apply"]]
    if v.label in (Label.DIRECT, Label.INDIRECT):
        lines += ["", f"## {t['appeal_h']}", "", "> " + t["appeal"].format(
            name="__________", dod=facts.date_of_death or "____", county=county, label=v.label.value,
            label_es="directamente" if v.label == Label.DIRECT else "indirectamente",
            disaster=_disaster(facts, ctx), chain=v.causal_chain.strip().rstrip("."),
        )]
    lines += ["", f"_{t['note']}_"]
    return "\n".join(lines)


def surveillance_record(facts: CaseFacts, ctx: DisasterContext, panel: PanelResult) -> dict:
    """Fields follow the CDC disaster-related mortality surveillance approach (who, when, where, how, relation)."""
    v = panel.final
    return {
        "case_id": facts.case_id,
        "reported": date.today().isoformat(),
        "state": facts.state,
        "county": facts.county,
        "county_fips": facts.county_fips,
        "date_of_death": facts.date_of_death.isoformat() if facts.date_of_death else None,
        "age": facts.decedent_age,
        "sex": facts.decedent_sex,
        "place_of_death": facts.place_of_death,
        "disaster": facts.disaster_name or ctx.declaration_title,
        "fema_declaration": ctx.declaration,
        "relationship_to_disaster": v.label.value,
        "circumstance": v.mechanism.value if v.mechanism else None,
        "all_circumstances": sorted({e.mechanism.value for e in facts.evidence}),
        "chronic_conditions": facts.chronic_conditions,
        "panel_unanimous": panel.unanimous,
        "source": "family interview (Counted)",
    }


def build_documents(facts: CaseFacts, ctx: DisasterContext, panel: PanelResult) -> dict:
    return {
        "certifier_statement": certifier_statement(facts, ctx, panel),
        "family_packet": family_packet(facts, ctx, panel),
        "surveillance_record": surveillance_record(facts, ctx, panel),
    }
