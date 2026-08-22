/**
 * Testes do card, sem navegador e sem dependências.
 *
 * O card é um arquivo de browser: não exporta nada e estende HTMLElement. Em
 * vez de montar um DOM inteiro, este teste carrega o arquivo *de verdade*
 * dentro de um contexto `vm` com o mínimo que ele toca ao ser lido, e depois
 * exercita as funções puras que ficaram no escopo do módulo.
 *
 * Rodar com:  node --test tests/card/
 */

import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const CARD = join(here, '..', '..', 'custom_components', 'weather_schedule', 'www',
    'weather-schedule-card.js');

/** Carrega o card num contexto isolado e devolve o escopo global dele. */
function loadCard() {
    const scope = {
        // O que o arquivo toca só de ser lido, e nada além disso.
        window: {customCards: []},
        customElements: {get: () => undefined, define: () => {}},
        document: {createElement: () => ({})},
        console: {info: () => {}, warn: () => {}, error: () => {}},
    };
    scope.globalThis = scope;
    // HTMLElement precisa ser construível: o card faz `extends HTMLElement`.
    scope.HTMLElement = class {};
    vm.createContext(scope);
    vm.runInContext(readFileSync(CARD, 'utf8'), scope, {filename: CARD});
    return scope;
}

const card = loadCard();

/** O estado padrão de um card recém-montado: nada buscado, nada em voo. */
function fresh(overrides = {}) {
    return {
        key: 'vpd|24h',
        seriesKey: '',
        seriesAt: 0,
        loadingKey: null,
        failedAt: 0,
        now: 1_000_000,
        ...overrides,
    };
}

test('o card define a política de busca no escopo do módulo', () => {
    assert.equal(typeof card.shouldFetchSeries, 'function');
});

test('um card sem histórico nenhum vai buscar', () => {
    assert.equal(card.shouldFetchSeries(fresh()), true);
});

test('uma série recente para a mesma chave dispensa nova busca', () => {
    assert.equal(card.shouldFetchSeries(fresh({
        seriesKey: 'vpd|24h',
        seriesAt: 1_000_000 - 60_000,  // um minuto atrás
    })), false);
});

test('uma série velha demais é buscada de novo', () => {
    assert.equal(card.shouldFetchSeries(fresh({
        seriesKey: 'vpd|24h',
        seriesAt: 1_000_000 - 600_000,  // dez minutos atrás
    })), true);
});

test('trocar de sala invalida a série que estava em mãos', () => {
    assert.equal(card.shouldFetchSeries(fresh({
        key: 'vpd|sala-2',
        seriesKey: 'vpd|24h',
        seriesAt: 1_000_000 - 1_000,
    })), true);
});

test('uma busca em andamento para a mesma chave não vira uma segunda', () => {
    // Este é o defeito que apagou o gráfico do VPD na 1.4.1: o Home Assistant
    // empurra `hass` a cada mudança de estado da instância, então cada render
    // começava outra busca e cancelava a anterior — e nenhuma terminava.
    assert.equal(card.shouldFetchSeries(fresh({loadingKey: 'vpd|24h'})), false);
});

test('mas uma busca em andamento de OUTRA chave não bloqueia esta', () => {
    assert.equal(card.shouldFetchSeries(fresh({loadingKey: 'vpd|sala-2'})), true);
});

test('uma falha recente não é tentada de novo a cada render', () => {
    assert.equal(card.shouldFetchSeries(fresh({
        failedAt: 1_000_000 - 5_000,  // falhou há cinco segundos
    })), false);
});

test('passado o intervalo, a falha é tentada de novo', () => {
    assert.equal(card.shouldFetchSeries(fresh({
        failedAt: 1_000_000 - 60_000,  // falhou há um minuto
    })), true);
});

test('a psicrometria do card bate com a do backend', () => {
    // 24 °C, 60% — os mesmos números do test_readings.py do lado Python.
    assert.ok(Math.abs(card.dewPoint(24, 60) - 15.76) < 0.05);
    assert.ok(Math.abs(card.vapourPressureDeficit(22, 24, 60) - 0.854) < 0.005);
});

// --------------------------------------------------------------------------
// A grade de amostragem: uma marca a cada N minutos, no relógio.
// --------------------------------------------------------------------------

const MIN = 60_000;

/* Arrays criados dentro do `vm` têm outro `Array.prototype`, e o `deepEqual`
   estrito recusa isso mesmo com os valores iguais. `Array.from` traz o
   resultado para o realm do teste antes de comparar. */
const plain = (list, fn) => Array.from(list, fn);

/** Uma série a partir de pares [minuto, valor]. */
function series(pairs, base = 0) {
    return pairs.map(([minute, value]) => ({time: base + minute * MIN, value}));
}

test('as marcas caem no relógio, não onde a janela começou', () => {
    // Janela abrindo às 00:03 — a primeira marca é 00:05, não 00:03.
    const out = card.resampleSeries(
        series([[0, 1.0], [4, 1.1], [9, 1.2], [14, 1.3]]),
        3 * MIN, 17 * MIN, 5 * MIN,
    );
    assert.deepEqual(plain(out, p => p.time / MIN), [5, 10, 15]);
});

test('cada marca leva a última leitura até ali, não a mais próxima', () => {
    // Marcas em 00:00, 00:05 e 00:10. Em 00:05 a última leitura é a de 00:04;
    // a de 00:09 ainda não aconteceu e por isso não entra ali.
    const out = card.resampleSeries(
        series([[0, 1.0], [4, 1.1], [9, 1.2]]),
        0, 12 * MIN, 5 * MIN,
    );
    assert.deepEqual(plain(out, p => p.value), [1.0, 1.1, 1.2]);
});

test('marcas anteriores à primeira leitura ficam de fora', () => {
    // A sala só começou a reportar aos 12 min: nada é inventado antes disso.
    const out = card.resampleSeries(series([[12, 1.4]]), 0, 20 * MIN, 5 * MIN);
    assert.deepEqual(plain(out, p => p.time / MIN), [15]);
});

test('a grade não passa de `now`, para o ponto de agora não colidir', () => {
    const out = card.resampleSeries(
        series([[0, 1.0], [5, 1.1], [10, 1.2]]),
        0, 10 * MIN, 5 * MIN,
    );
    assert.ok(out.every(p => p.time < 10 * MIN));
});

test('cada ponto carrega os extremos da fatia dele', () => {
    // Entre 00:00 e 00:05 a sala foi de 1,0 a 1,9 e voltou para 1,2.
    const out = card.resampleSeries(
        series([[1, 1.0], [2, 1.9], [4, 1.2]]),
        0, 7 * MIN, 5 * MIN,
    );
    assert.equal(out[0].value, 1.2);   // o valor é o último até a marca
    assert.equal(out[0].low, 1.0);     // mas o pico da fatia não se perde
    assert.equal(out[0].high, 1.9);
});

test('uma fatia sem leitura nova segura a anterior, sem inventar extremos', () => {
    const out = card.resampleSeries(series([[1, 1.0]]), 0, 12 * MIN, 5 * MIN);
    assert.deepEqual(plain(out, p => [p.value, p.low, p.high].join()), ['1,1,1', '1,1,1']);
});

test('vinte e quatro horas em passos de cinco minutos dão 288 pontos', () => {
    const day = 24 * 60;
    const raw = Array.from({length: day}, (_, i) => ({time: i * MIN, value: 1}));
    assert.equal(card.resampleSeries(raw, 0, day * MIN, 5 * MIN).length, 288);
});

test('série vazia ou passo inválido não produzem pontos', () => {
    assert.equal(card.resampleSeries([], 0, MIN, 5 * MIN).length, 0);
    assert.equal(card.resampleSeries(series([[0, 1]]), 0, MIN, 0).length, 0);
});
