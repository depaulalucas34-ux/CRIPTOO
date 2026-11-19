"""Cripto Alertas: avisa por ntfy cuando una moneda se mueve fuerte y manda un resumen diario.
Pensado para correr cada 30 min en GitHub Actions. La configuración viene de variables de entorno."""
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

API = "https://api.coingecko.com/api/v3/coins/markets"
SIMBOLOS = {"usd": "US$", "eur": "€", "ars": "AR$"}
ALIAS = {
    "BTC": "bitcoin", "ETH": "ethereum", "XRP": "ripple", "SOL": "solana", "BNB": "binancecoin",
    "DOGE": "dogecoin", "ADA": "cardano", "TRX": "tron", "LINK": "chainlink", "AVAX": "avalanche-2",
    "LTC": "litecoin", "DOT": "polkadot", "XLM": "stellar", "SHIB": "shiba-inu", "TON": "the-open-network",
    "PEPE": "pepe", "SUI": "sui", "XMR": "monero",
}
ESTADO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "estado.json")


def env(nombre, defecto):
    return os.environ.get(nombre) or defecto


def config():
    return {
        "topic": env("NTFY_TOPIC", ""),
        "monedas": env("MONEDAS", "BTC, ETH, XRP, SOL"),
        "moneda": env("MONEDA", "usd").lower(),
        "umbral": float(env("UMBRAL", "5")),
        "hora_resumen": int(env("HORA_RESUMEN", "9")),
        "zona": env("ZONA", "America/Argentina/Buenos_Aires"),
        "enfriamiento": float(env("ENFRIAMIENTO_HORAS", "12")),
    }


def ids_de(texto):
    ids = []
    for t in texto.split(","):
        t = t.strip()
        if t:
            i = ALIAS.get(t.upper(), t.lower())
            if i not in ids:
                ids.append(i)
    return ids


def fmt(v):
    if v is None:
        return "—"
    d = 0 if v >= 1000 else 2 if v >= 1 else 4 if v >= 0.01 else 6
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v, d=1):
    return f"{abs(v):.{d}f}".replace(".", ",")


def traer_precios(ids, cur):
    headers = {"accept": "application/json"}
    clave = os.environ.get("COINGECKO_DEMO_KEY")
    if clave:
        headers["x-cg-demo-api-key"] = clave
    r = requests.get(API, params={"vs_currency": cur, "ids": ",".join(ids),
                                  "order": "market_cap_desc", "price_change_percentage": "24h"},
                     headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def enviar(topic, titulo, mensaje, prioridad=3, tags=("chart_with_upwards_trend",)):
    r = requests.post("https://ntfy.sh/", json={"topic": topic, "title": titulo, "message": mensaje,
                                                "priority": prioridad, "tags": list(tags)}, timeout=20)
    r.raise_for_status()


def cargar_estado():
    try:
        with open(ESTADO, encoding="utf-8") as f:
            e = json.load(f)
    except (OSError, ValueError):
        e = {}
    e.setdefault("monedas", {})
    e.setdefault("ultimo_resumen", "")
    return e


def guardar_estado(e):
    with open(ESTADO, "w", encoding="utf-8") as f:
        json.dump(e, f, indent=1, ensure_ascii=False, sort_keys=True)


def linea(r, sim):
    ch = r.get("price_change_percentage_24h") or 0
    flecha = "▲" if ch >= 0 else "▼"
    return f"{r['symbol'].upper()} {sim}{fmt(r['current_price'])}  {flecha}{pct(ch)}%"


def evaluar_alertas(rows, estado, ahora, umbral, enfriamiento):
    """Devuelve las filas que merecen alerta y actualiza el estado.
    Alerta si el cambio 24h supera el umbral y (es la primera vez, o el movimiento
    escaló a otro múltiplo del umbral, o pasó el tiempo de enfriamiento)."""
    alertas = []
    for r in rows:
        ch = r.get("price_change_percentage_24h")
        if ch is None:
            continue
        nivel = int(abs(ch) // umbral) * (1 if ch > 0 else -1)
        previo = estado["monedas"].get(r["id"], {"nivel": 0, "ts": None})
        if nivel == 0:
            estado["monedas"][r["id"]] = {"nivel": 0, "ts": None}
            continue
        if previo["ts"]:
            horas = (ahora - datetime.fromisoformat(previo["ts"])).total_seconds() / 3600
        else:
            horas = float("inf")
        escalo = (nivel * previo["nivel"] <= 0) or abs(nivel) > abs(previo["nivel"])
        if escalo or horas >= enfriamiento:
            alertas.append(r)
            estado["monedas"][r["id"]] = {"nivel": nivel, "ts": ahora.isoformat()}
    return alertas


def main():
    c = config()
    if not c["topic"]:
        sys.exit("Falta el secreto NTFY_TOPIC (ver README).")
    ids = ids_de(c["monedas"])
    if not ids:
        sys.exit("Falta configurar MONEDAS.")
    sim = SIMBOLOS.get(c["moneda"], "")
    rows = traer_precios(ids, c["moneda"])
    ahora = datetime.now(ZoneInfo(c["zona"]))
    estado = cargar_estado()

    alertas = evaluar_alertas(rows, estado, ahora, c["umbral"], c["enfriamiento"])
    if alertas:
        enviar(c["topic"], f"⚠️ Movimiento fuerte (±{c['umbral']:g}% en 24 h)",
               "\n".join(linea(r, sim) for r in alertas), prioridad=4, tags=("warning",))
        print("Alerta enviada:", [r["symbol"] for r in alertas])

    hoy = ahora.date().isoformat()
    if 0 <= c["hora_resumen"] <= 23 and ahora.hour >= c["hora_resumen"] and estado["ultimo_resumen"] != hoy:
        enviar(c["topic"], f"Cripto Diario - {ahora:%d/%m}", "\n".join(linea(r, sim) for r in rows))
        estado["ultimo_resumen"] = hoy
        print("Resumen diario enviado")

    guardar_estado(estado)
    print("Listo.", ahora.isoformat(timespec="minutes"))


if __name__ == "__main__":
    main()
