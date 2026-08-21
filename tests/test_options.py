"""O que a tela de opções aceita salvar, e o que ela tem que recusar."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re

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


# --------------------------------------------------------------------------- #
# O passo que o card usa: tudo numa gravação só.
# --------------------------------------------------------------------------- #


def save_card(flow, payload):
    return asyncio.run(flow.async_step_card(payload))


def full_payload(**changes) -> dict:
    payload = {
        "air_temperature": ["sensor.air"],
        "relative_humidity": ["sensor.rh"],
        "leaf_drop": 2.0,
        "trip_minutes": 15,
        "clear_minutes": 5,
        "ambient_co2": False,
        "fans": ["fan.exhaust"],
        "fan_names": {"fan.exhaust": "Exaustor"},
        "fan_powers": {"fan.exhaust": ""},
        "fan_cycles": {"fan.exhaust": {"on": 15, "off": 45, "enabled": True}},
    }
    payload.update(changes)
    return payload


def test_the_card_saves_sensors_alert_and_fans_in_one_entry(options):
    """Eram três passos e três recargas; cada recarga zerava o alerta."""
    result = save_card(options, full_payload())

    assert result["type"] == "create_entry"
    saved = options.saved
    assert saved["air_temperature"] == ["sensor.air"]
    assert saved["trip_minutes"] == 15
    assert saved["fans"] == [
        {
            "entity_id": "fan.exhaust",
            "name": "Exaustor",
            "power": "",
            "cycle": {"on": 15, "off": 45, "enabled": True},
        }
    ]


def test_the_card_step_keeps_what_the_other_steps_wrote(options):
    options.entry.options = {"profiles": {"veg_late": {"vpd_min": 0.9}}}
    save_card(options, full_payload())
    assert options.saved["profiles"] == {"veg_late": {"vpd_min": 0.9}}


def test_clearing_an_optional_sensor_sticks(options):
    options.entry.options = {"carbon_dioxide": "sensor.co2", "leaf_sensor": "sensor.leaf"}
    save_card(options, full_payload())
    assert options.saved["carbon_dioxide"] is None
    assert options.saved["leaf_sensor"] is None


def test_a_room_without_its_two_sensors_is_refused(options):
    result = save_card(options, full_payload(relative_humidity=[]))

    assert result["type"] == "form"
    assert result["errors"] == {"base": "needs_sensors"}
    assert options.saved is None


def test_the_card_step_shows_a_form_before_it_is_given_anything(options):
    """O card navega até o passo e só depois envia o payload."""
    assert save_card(options, None)["type"] == "form"
    assert options.saved is None


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        ({"fan_names": ["Exaustor"]}, "nome como lista em vez de dicionário"),
        ({"fan_powers": "sensor.watts"}, "potência como texto solto"),
        ({"fan_cycles": None}, "ciclos ausentes"),
        ({"fans": "fan.exhaust"}, "escolha como texto em vez de lista"),
    ],
)
def test_a_malformed_fan_payload_never_raises(options, payload, reason):
    """Achado B10: estes campos entram por ALLOW_EXTRA, sem schema nenhum."""
    result = save_card(options, full_payload(**payload))
    assert result["type"] == "create_entry", reason


def test_a_fan_outside_its_domains_is_dropped(options):
    """O seletor filtra o domínio na tela; o POST pode trazer o que quiser."""
    save_card(options, full_payload(fans=["light.grow", "fan.exhaust"]))

    assert [fan["entity_id"] for fan in options.saved["fans"]] == ["fan.exhaust"]


@pytest.mark.parametrize(
    ("field", "sent", "expected"),
    [
        ("trip_minutes", 9000, 240),
        ("trip_minutes", 0, 1),
        ("clear_minutes", "muitos", 5),
    ],
)
def test_numbers_from_the_card_are_kept_inside_their_range(options, field, sent, expected):
    """Sem schema, o número chega cru: quem limita é o passo."""
    save_card(options, full_payload(**{field: sent}))
    assert options.saved[field] == expected


def test_the_leaf_drop_never_reaches_the_options(options):
    """Achado M2: o valor mora na entidade `number`, e só nela.

    Guardado também nas opções, o estado restaurado da entidade passava por
    cima da opção recém-salva a cada reload, e a edição sumia sem aviso.
    """
    save_card(options, full_payload(leaf_drop=4.0))
    assert "leaf_drop" not in options.saved


def test_the_sensors_step_ignores_a_leaf_drop_that_is_sent_to_it(options):
    """Nem pelo formulário nativo: um valor antigo não pode reescrever o novo."""
    options.entry.options = {"leaf_drop": 2.0}

    asyncio.run(
        options.async_step_sensors(
            {
                "air_temperature": ["sensor.air"],
                "relative_humidity": ["sensor.rh"],
                "leaf_drop": 5.5,
            }
        )
    )

    # O 5,5 é descartado; o que já estava guardado atravessa o merge intacto.
    assert options.saved["leaf_drop"] == 2.0
    assert options.saved["air_temperature"] == ["sensor.air"]


def test_the_setup_form_still_seeds_the_leaf_drop():
    """Na criação da sala não há entidade a quem perguntar."""
    from custom_components.weather_schedule.config_flow import _sensor_schema

    setup = {str(key) for key in _sensor_schema({}, seed_leaf_drop=True).schema}
    later = {str(key) for key in _sensor_schema({}).schema}

    assert "leaf_drop" in setup
    assert "leaf_drop" not in later


def test_every_error_the_code_raises_has_a_message():
    """Um erro sem tradução aparece como a chave crua na tela."""
    source = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
    # Duas formas no código: atribuir numa chave do dicionário de erros, e
    # montar o dicionário inteiro na chamada do formulário.
    raised = set(re.findall(r'errors\[[^\]]+\]\s*=\s*"([a-z_]+)"', source))
    raised |= set(re.findall(r'errors=\{[^}]*"([a-z_]+)"\s*\}', source))
    declared = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))

    assert len(raised) > 1, "o teste perdeu o padrão que procura os erros"
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
