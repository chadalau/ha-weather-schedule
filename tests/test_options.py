"""O que a tela de opções aceita salvar, e o que ela tem que recusar."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest

from custom_components.weather_schedule.config_flow import WeatherScheduleOptionsFlow
from custom_components.weather_schedule.const import (
    BOUNDS,
    CONF_PROFILES,
    DEFAULT_PROFILES,
)

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components" / "weather_schedule"


class FakeEntry:
    def __init__(self, options: dict, data: dict | None = None) -> None:
        self.options = options
        self.data = data or {"name": "Indoor"}


class OptionsFlowUnderTest(WeatherScheduleOptionsFlow):
    """`config_entry` é só de leitura no HA; aqui ela vem de um entry falso."""

    entry = FakeEntry({})

    @property
    def config_entry(self) -> FakeEntry:  # type: ignore[override]
        return self.entry


@pytest.fixture
def options():
    """A options flow sem o motor do HA: só o que os passos usam."""
    flow = object.__new__(OptionsFlowUnderTest)
    flow._phase = "veg_late"
    flow.entry = FakeEntry({})
    flow.saved = None
    flow.shown = None

    def async_create_entry(*, data, **_kwargs):
        flow.saved = data
        return {"type": "create_entry", "data": data}

    def async_show_form(**kwargs):
        flow.shown = kwargs
        return {"type": "form", **kwargs}

    flow.async_create_entry = async_create_entry
    flow.async_show_form = async_show_form
    return flow


def window(**changes) -> dict:
    return {**DEFAULT_PROFILES["veg_late"], **changes}


def submit(flow, values):
    return asyncio.run(flow.async_step_bounds(values))


def test_a_sane_window_is_saved(options):
    submit(options, window(vpd_min=0.9, vpd_max=1.4))

    saved = options.saved[CONF_PROFILES]["veg_late"]
    assert saved["vpd_min"] == 0.9 and saved["vpd_max"] == 1.4
    assert set(saved) == set(BOUNDS)


@pytest.mark.parametrize(
    ("low", "high"),
    [("vpd_min", "vpd_max"), ("temp_min", "temp_max"), ("rh_min", "rh_max"), ("co2_min", "co2_max")],
)
def test_an_inverted_window_is_refused_on_the_field_that_is_wrong(options, low, high):
    """Janela invertida julgaria a sala ao contrário para sempre."""
    values = window()
    values[low], values[high] = values[high], values[low]

    result = submit(options, values)

    assert result["type"] == "form"
    assert result["errors"] == {low: "min_above_max"}
    assert options.saved is None


def test_minimum_equal_to_maximum_is_allowed(options):
    """Faixa de um ponto só é estranha, mas é coerente — não é erro."""
    submit(options, window(vpd_min=1.1, vpd_max=1.1))
    assert options.saved is not None


def test_saving_one_phase_keeps_the_others(options):
    options.entry.options = {CONF_PROFILES: {"flower_late": {"vpd_min": 1.3}}}

    submit(options, window(vpd_min=0.9))

    profiles = options.saved[CONF_PROFILES]
    assert profiles["flower_late"] == {"vpd_min": 1.3}
    assert profiles["veg_late"]["vpd_min"] == 0.9


def test_saving_the_window_keeps_the_other_options(options):
    options.entry.options = {"alert_minutes": 30}
    submit(options, window())
    assert options.saved["alert_minutes"] == 30


def test_every_error_the_code_raises_has_a_message():
    """Um erro sem tradução aparece como a chave crua na tela."""
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    raised = set(re.findall(r'errors\[[^\]]+\]\s*=\s*"([a-z_]+)"', source))
    declared = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

    assert raised, "o teste perdeu o padrão que procura os erros"
    for key in raised:
        assert key in declared["options"]["error"], f"erro {key} sem texto"


@pytest.mark.parametrize("language", ["en", "pt-BR"])
def test_translations_mirror_the_strings_file(language):
    """Chave que existe só no strings.json vira texto em inglês no meio do pt."""
    declared = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    translated = json.loads(
        (COMPONENT / "translations" / f"{language}.json").read_text(encoding="utf-8")
    )

    missing: list[str] = []

    def compare(left, right, path=""):
        for key, value in left.items():
            if key not in right:
                missing.append(f"{path}{key}")
            elif isinstance(value, dict):
                compare(value, right[key], f"{path}{key}.")

    compare(declared, translated)
    assert missing == []


def test_the_three_declared_versions_agree():
    """A versão vive em três arquivos; divergir quebra o cache-busting do card."""
    const = re.search(r'VERSION: Final = "([^"]+)"', (COMPONENT / "const.py").read_text(encoding="utf-8"))
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["version"]
    card = re.search(
        r"const VERSION = '([^']+)'",
        (COMPONENT / "www" / "weather-schedule-card.js").read_text(encoding="utf-8"),
    )

    assert const and card, "o teste perdeu onde a versão é declarada"
    assert const.group(1) == manifest == card.group(1)
