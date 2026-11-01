"""What the family is told when the panel decides, in vetted words (English or Spanish).

The first live red team showed why this is code and not the model: asked to explain a finding, the interviewer wrote
"the medical examiner has determined", "officially connected to the storm" and "you can send the statement to FEMA
today". None of it was true. The model still decides how to ask; this decides how the outcome is said.
"""

from __future__ import annotations

import re

from .schemas import CaseFacts, DisasterContext, Label, Mechanism, PanelResult

MECHANISM = {
    Mechanism.DROWNING: ("drowning in flood or storm water", "ahogamiento en el agua de la inundación o la tormenta"),
    Mechanism.STRUCK_BY_OBJECT: ("being struck by debris or a falling tree", "un golpe de escombros o de un árbol caído"),
    Mechanism.STRUCTURAL_COLLAPSE: ("a building collapse", "el derrumbe de una estructura"),
    Mechanism.WIND_TRAUMA: ("injuries from the wind or a tornado", "lesiones causadas por el viento o un tornado"),
    Mechanism.WILDFIRE: ("burns or smoke from the fire", "quemaduras o humo del incendio"),
    Mechanism.ENVIRONMENTAL_TEMPERATURE: ("exposure to extreme cold or heat", "la exposición al frío o al calor extremo"),
    Mechanism.UTILITY_LOSS: ("the loss of power, water or heat", "la falta de electricidad, agua o calefacción"),
    Mechanism.HEALTHCARE_DISRUPTION: ("losing access to medical care", "la pérdida de acceso a la atención médica"),
    Mechanism.POWER_DEPENDENT_DEVICE: ("a medical device that stopped when the power failed",
                                       "un aparato médico que dejó de funcionar cuando se fue la luz"),
    Mechanism.CARBON_MONOXIDE: ("carbon monoxide poisoning", "una intoxicación por monóxido de carbono"),
    Mechanism.CLEANUP_OR_PREP_INJURY: ("an injury while preparing for the disaster or cleaning up after it",
                                       "una lesión al prepararse para el desastre o al limpiar después"),
    Mechanism.EVACUATION: ("evacuating or fleeing", "la evacuación o la huida"),
    Mechanism.VEHICLE_CRASH: ("a vehicle crash in the conditions the disaster created",
                              "un accidente de tránsito en las condiciones que causó el desastre"),
    Mechanism.FIRE_ALTERNATIVE_HEAT: ("a fire from a heater, candle or generator used during the outage",
                                      "un incendio por un calentador, una vela o un generador usado durante el apagón"),
    Mechanism.CHRONIC_EXACERBATION: ("a chronic illness the disaster made worse", "una enfermedad crónica que el desastre agravó"),
    Mechanism.STRESS_CARDIAC: ("strain on the heart caused by the disaster", "el esfuerzo que el desastre causó al corazón"),
    Mechanism.FALL: ("a fall in unsafe conditions the disaster created",
                     "una caída en condiciones peligrosas que causó el desastre"),
    Mechanism.ELECTROCUTION: ("electrocution", "una electrocución"),
    Mechanism.INFECTION: ("an infection from floodwater or an injury", "una infección por agua de inundación o por una lesión"),
}

_SPANISH = re.compile(r"\b(?:mi|mamá|papá|usted|murió|falleció|tormenta|huracán|luz|casa|tenía|vivía|que|por|para)\b", re.I)


def looks_spanish(text: str) -> bool:
    return len(_SPANISH.findall(text or "")) >= 3


def _disaster(facts: CaseFacts, ctx: DisasterContext) -> str:
    return facts.disaster_name or ctx.declaration_title or ("el desastre declarado" if facts.language == "es" else "the declared disaster")


def message(facts: CaseFacts, ctx: DisasterContext | None, panel: PanelResult) -> str:
    ctx = ctx or DisasterContext()
    v, es = panel.final, facts.language == "es"
    d = _disaster(facts, ctx)
    how = MECHANISM.get(v.mechanism) if v.mechanism else None
    county = f"{facts.county} County" if facts.county else None
    if v.label in (Label.DIRECT, Label.INDIRECT):
        if es:
            label = "directamente" if v.label == Label.DIRECT else "indirectamente"
            ia = f" (FEMA aprobó la Asistencia Individual para el condado de {facts.county})" if ctx.individual_assistance and facts.county else ""
            return (f"Gracias por contarme todo esto. Así están las cosas.\n\n"
                    f"Con lo que usted me contó y los registros públicos, la revisión de Counted preparó este hallazgo en borrador: "
                    f"la muerte fue causada {label} por {d}" + (f", a través de {how[1]}" if how else "") + ". "
                    f"Counted es un programa, no un médico, y esto es un borrador, no una decisión. Un médico forense, o el médico "
                    f"que firmó el certificado de defunción, lo revisa, y solo esa persona puede firmarlo.\n\n"
                    f"Preparé tres documentos: una declaración en borrador para esa persona, un paquete para su familia sobre cómo "
                    f"pedir la asistencia funeraria de FEMA{ia}, y un registro para el departamento de salud. Cuando la declaración "
                    f"esté firmada, su familia puede presentar la solicitud; FEMA decide. ¿Quiere que repasemos juntos el paquete?")
        label = "directly" if v.label == Label.DIRECT else "indirectly"
        ia = f" (FEMA approved Individual Assistance for {county})" if ctx.individual_assistance and county else ""
        return (f"Thank you for telling me all of this. Here is where things stand.\n\n"
                f"From what you described and the public records, Counted's review drafted this finding: the death was "
                f"{label} caused by {d}" + (f", through {how[0]}" if how else "") + ". "
                f"Counted is software, not a doctor, and this is a draft, not a decision. A medical examiner, or the doctor who "
                f"signed the death certificate, reviews it, and only they can sign it.\n\n"
                f"I've prepared three things: a draft statement for them, a packet for your family on applying for FEMA "
                f"funeral assistance{ia}, and a record for the health department. Once the statement is signed, your family "
                f"can apply; FEMA decides. Would you like to go through the family packet together?")
    if v.label == Label.NOT_RELATED:
        if es:
            return (f"Gracias por contármelo. Tengo que ser honesto con usted: con lo que me contó y los registros públicos, la "
                    f"revisión de Counted no encontró una relación entre {d} y la muerte. La asistencia funeraria de FEMA es solo "
                    f"para muertes que un desastre causó, así que no puedo preparar una declaración que diga que lo causó. Si hay "
                    f"algo de esos días que no me haya contado, como un corte de luz, una atención médica que se perdió o una "
                    f"lesión, puede decírmelo ahora y Counted lo revisará de nuevo. Un médico forense también puede revisar la "
                    f"muerte; esa persona toma la decisión final.")
        return (f"Thank you for telling me. I have to be honest with you: from what you described and the public records, "
                f"Counted's review did not find a link between {d} and the death. FEMA funeral assistance is only for deaths a "
                f"disaster caused, so I can't prepare a statement saying it did. If there is something about those days you "
                f"haven't mentioned, like a power cut, missed medical care or an injury, you can tell me now and Counted will "
                f"look again. A medical examiner can also review the death; they make the final decision.")
    if es:
        return (f"Gracias. Con lo que usted me contó y los registros públicos, la revisión de Counted no pudo decidir si {d} "
                f"causó la muerte, así que no preparé un hallazgo en ningún sentido. Preparé un borrador que pide a un médico "
                f"forense que revise el caso; solo esa persona puede decidir. Si recuerda algo más de esos días, puede "
                f"decírmelo ahora.")
    return (f"Thank you. From what you described and the public records, Counted's review could not decide whether {d} "
            f"caused the death, so I haven't drafted a finding either way. I've prepared a draft that asks a medical examiner "
            f"to review the case; only they can decide. If you remember anything else about those days, you can tell me now.")
