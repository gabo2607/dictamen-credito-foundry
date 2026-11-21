"""
Motor de reglas determinístico (sin IA). Los umbrales son hipótesis didácticas,
no la política oficial de la Caja.

Política de decisión:
  - Si falla una regla EXCLUYENTE (R1, R2, R4)  -> RECHAZA
  - Si no, si falla una regla SUBSANABLE (R3, R5) -> RESERVA (pasa a revisión / completar expediente)
  - Si cumple todas                              -> APRUEBA
"""

TEA_REFERENCIAL = 0.30       # tasa efectiva anual usada para estimar la cuota
MAX_ENDEUDAMIENTO = 0.40     # R1: deuda total / ventas anuales < 40 %
MAX_DIAS_ATRASO = 0          # R2: sin atraso en centrales
MIN_ANTIGUEDAD_ANIOS = 2.0   # R3: antigüedad del negocio >= 2 años
MAX_CUOTA_INGRESO = 0.30     # R4: cuota / ventas mensuales <= 30 %


def cuota_mensual(monto: float, plazo_meses: int, tea: float = TEA_REFERENCIAL) -> float:
    """Cuota fija (método francés) con la TEA convertida a tasa mensual."""
    i = (1 + tea) ** (1 / 12) - 1
    return monto * i / (1 - (1 + i) ** -plazo_meses)


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %"


def evaluar(c: dict) -> dict:
    ingreso_anual = c["ventas_mensuales"] * 12
    endeudamiento = c["deuda_total"] / ingreso_anual if ingreso_anual else float("inf")
    cuota = cuota_mensual(c["monto_solicitado"], c["plazo_meses"])
    cuota_ingreso = cuota / c["ventas_mensuales"] if c["ventas_mensuales"] else float("inf")
    sustentos = [r for r in c.get("recibos", []) if r["tipo"] == "sustento_ingresos"]

    reglas = [
        {
            "codigo": "R1", "nombre": "Endeudamiento", "tipo": "excluyente",
            "umbral": f"< {_pct(MAX_ENDEUDAMIENTO)}", "valor": _pct(endeudamiento),
            "cumple": endeudamiento < MAX_ENDEUDAMIENTO,
            "calculo": f"deuda_total {c['deuda_total']:.2f} / ventas anuales {ingreso_anual:.2f}",
        },
        {
            "codigo": "R2", "nombre": "Sin atraso en centrales", "tipo": "excluyente",
            "umbral": f"<= {MAX_DIAS_ATRASO} días", "valor": f"{c['dias_atraso']} días",
            "cumple": c["dias_atraso"] <= MAX_DIAS_ATRASO,
            "calculo": "días de atraso reportados en centrales de riesgo",
        },
        {
            "codigo": "R3", "nombre": "Antigüedad del negocio", "tipo": "subsanable",
            "umbral": f">= {MIN_ANTIGUEDAD_ANIOS:g} años", "valor": f"{c['antiguedad_anios']:g} años",
            "cumple": c["antiguedad_anios"] >= MIN_ANTIGUEDAD_ANIOS,
            "calculo": "antigüedad declarada del negocio",
        },
        {
            "codigo": "R4", "nombre": "Cuota / ingreso", "tipo": "excluyente",
            "umbral": f"<= {_pct(MAX_CUOTA_INGRESO)}", "valor": _pct(cuota_ingreso),
            "cumple": cuota_ingreso <= MAX_CUOTA_INGRESO,
            "calculo": (f"cuota estimada {cuota:.2f} (S/ {c['monto_solicitado']:.2f}, {c['plazo_meses']} meses, "
                        f"TEA {_pct(TEA_REFERENCIAL)}) / ventas mensuales {c['ventas_mensuales']:.2f}"),
        },
        {
            "codigo": "R5", "nombre": "Sustento de ingresos", "tipo": "subsanable",
            "umbral": ">= 1 recibo de sustento de ingresos", "valor": f"{len(sustentos)} recibo(s)",
            "cumple": len(sustentos) > 0,
            "calculo": "recibos de tipo sustento_ingresos: " + (", ".join(r["id"] for r in sustentos) or "ninguno"),
        },
    ]

    falla = {r["tipo"] for r in reglas if not r["cumple"]}
    if "excluyente" in falla:
        decision = "RECHAZA"
    elif "subsanable" in falla:
        decision = "RESERVA"
    else:
        decision = "APRUEBA"

    return {
        "decision": decision,
        "reglas": reglas,
        "cuota_estimada": round(cuota, 2),
        "tea_referencial": TEA_REFERENCIAL,
    }
