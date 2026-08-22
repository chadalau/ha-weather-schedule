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
