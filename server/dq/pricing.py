"""Token prices in USD per 1 million tokens, used to show the cost of every run in the console.

Prices change. These are the published Gemini API paid-tier rates checked on 11 Nov 2026.
Gemini 4 Argon moves from 2/10 to 4/20 on 1 Dec 2026 and Gemini 3.8 Flash from 0.75/3.75 to 1.50/7.50 on
1 Jan 2027. Update this table, or set DQ_PRICE_OVERRIDES='{"gemini-3.8-flash":[1.5,7.5]}', when they do."""
import json
import os

from . import config

PRICES = {  # model id: (input, output)
    "gemini-3.8-flash": (0.75, 3.75),
    "gemini-3.5-flash-lite": (0.30, 2.50),
    "gemini-4-argon": (2.00, 10.00),
    "gemini-4-carbon": (2.00, 10.00),
    "mock": (0.75, 3.75),  # mock runs are priced like Flash so dashboards look realistic in rehearsal
}
PRICES.update({k: tuple(v) for k, v in json.loads(os.getenv("DQ_PRICE_OVERRIDES", "{}")).items()})


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    key = next((k for k in PRICES if model and model.startswith(k)), "gemini-3.8-flash")
    pin, pout = PRICES[key]
    return round(input_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 6)


def cost_inr(model: str, input_tokens: int, output_tokens: int) -> float:
    return round(cost_usd(model, input_tokens, output_tokens) * config.USD_INR, 4)
