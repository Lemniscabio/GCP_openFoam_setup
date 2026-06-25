"""Conversational geometry-spec agent.

Turns a natural-language conversation into a validated STRParams spec — the same object
the form produces. The agent only fills the spec; it never computes physics or geometry.
It asks clarifying questions when something required is missing, and when it has enough it
emits the spec in a fenced ```json block. The spec is validated server-side against the
REAL STRParams schema, so an invalid spec can never be handed off (the agent is asked to
fix it). The deterministic generator then builds the geometry from the spec.
"""
import json
import re
from typing import Callable

from str_cad.schema import STRParams, SchemaError

from core.schema_doc import str_params_schema_doc

DEFAULT_MODEL = "gemini-2.5-flash"
MAX_FIX_RETRIES = 2

_SYSTEM_PREAMBLE = """\
You help an engineer specify a stirred-tank-reactor geometry by chatting in plain language.

Behaviour:
- Read the WHOLE conversation and extract every value the user has given, in any phrasing
  or units. Briefly acknowledge what you captured.
- If several required fields are still missing, ask for them ALL in ONE concise message as
  a short bulleted list. Do NOT ask one question at a time or drip-feed.
- Convert units sensibly: kL (kilolitre) = m^3; L (litre) = 1e-3 m^3; cm = 0.01 m;
  mm = 0.001 m.
- A reactor VOLUME (e.g. "100 kL", "30 kL") does NOT by itself fix the geometry — both tank
  diameter and height are needed. Acknowledge the stated volume, then ask for the tank
  diameter and height (or a height:diameter ratio). As a sanity check the liquid volume is
  ~ pi * (diameter/2)^2 * liquid_height. Never silently ignore a value the user gave.
- You CAN and SHOULD answer volume questions from the dimensions you already have:
  liquid volume ~ pi * (tank.diameter_m/2)^2 * liquid.height_m; cylindrical tank volume
  ~ pi * (tank.diameter_m/2)^2 * tank.height_m. Report in m^3 AND litres (1 m^3 = 1000 L,
  so m^3 * 1000 = L, and kL = m^3). Don't refuse — compute it.
- Do not ask about auto-filled fields unless the user raises them. Never invent a value the
  user hasn't given or implied for a required field — ask instead.
- When (and only when) you have every required field, reply with a brief one-line
  confirmation of what you'll build, then a SINGLE fenced ```json block containing the
  complete spec. Do not include a json block before then.
"""

# A fenced ```json { ... } ``` block, or a bare ```{ ... }``` block.
_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)

Generator = Callable[[list[dict], str], str]


def run_geometry_chat(
    messages: list[dict],
    *,
    api_key: str | None,
    model: str = DEFAULT_MODEL,
    generate: Generator | None = None,
) -> dict:
    """Run one chat turn.

    messages: [{"role": "user"|"model", "content": str}, ...] — the full conversation.
    Returns {"reply": str, "spec": dict | None}. spec is non-null only when the agent has
    produced a complete, schema-valid STRParams spec.

    generate: injectable text generator (messages, system) -> str (for tests). Defaults to
    Gemini.
    """
    system = _SYSTEM_PREAMBLE + "\n\n" + str_params_schema_doc()
    gen = generate or _gemini_generator(api_key, model)

    convo = list(messages)
    for _ in range(MAX_FIX_RETRIES + 1):
        text = gen(convo, system)
        raw = _extract_json_block(text)
        if raw is None:
            return {"reply": text.strip(), "spec": None}  # still clarifying
        try:
            spec_obj = json.loads(raw)
            validated = STRParams.model_validate(spec_obj)
        except (json.JSONDecodeError, SchemaError, ValueError) as exc:
            # Invalid spec — ask the model to fix it, then retry.
            convo = convo + [
                {"role": "model", "content": text},
                {"role": "user", "content": f"That spec was invalid: {exc}. "
                                             "Please correct it and resend the full spec."},
            ]
            continue
        return {"reply": _strip_json_block(text).strip(), "spec": validated.model_dump(mode="json")}

    return {
        "reply": "I couldn't put together a valid spec from that. Could you clarify, or "
                 "use “Do it manually” to fill the form?",
        "spec": None,
    }


def _extract_json_block(text: str) -> str | None:
    match = _JSON_BLOCK.search(text or "")
    return match.group(1) if match else None


def _strip_json_block(text: str) -> str:
    return _JSON_BLOCK.sub("", text or "")


def _gemini_generator(api_key: str | None, model: str) -> Generator:
    def generate(messages: list[dict], system: str) -> str:
        from google import genai

        client = genai.Client(api_key=api_key)
        contents = [
            {"role": m["role"], "parts": [{"text": m["content"]}]} for m in messages
        ]
        resp = client.models.generate_content(
            model=model,
            contents=contents,
            config={"system_instruction": system, "temperature": 0.2},
        )
        return resp.text or ""

    return generate
