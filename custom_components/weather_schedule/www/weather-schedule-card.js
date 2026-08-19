/**
 * Weather Schedule card.
 *
 * One room, one card: the VPD reading, the phase it is being judged against,
 * a tile per climate figure with its target window, the last hours of VPD and
 * the fans you reach for when something is off.
 *
 * Ships inside the integration, which serves this file and loads it into the
 * frontend, so there is no Lovelace resource to register by hand.
 */

const VERSION = '1.0.6';
const SVG_NS = 'http://www.w3.org/2000/svg';
const SPEED_STEPS = [25, 50, 75, 100];
const HISTORY_MAX_AGE = 300000;
const HISTORY_RANGES = [6, 24, 72, 168];
const CHART_MAX_POINTS = 1500;

/** Fixed VPD bands, drawn behind the trend so a value reads without a legend. */
const VPD_BANDS = [
    {from: 0, to: 0.4, color: '#1a6c9c', key: 'under'},
    {from: 0.4, to: 0.8, color: '#22ab9c', key: 'veg_early'},
    {from: 0.8, to: 1.2, color: '#9cc55b', key: 'veg_late'},
    {from: 1.2, to: 1.6, color: '#e7c12b', key: 'flower'},
    {from: 1.6, to: 2.0, color: '#ce4234', key: 'over'},
];

const TEXT = {
    en: {
        band: {under: 'Under transpiration', veg_early: 'Early vegetative', veg_late: 'Late vegetative', flower: 'Flower', over: 'Over range'},
        phase: {propagation: 'Propagation', veg_early: 'Early vegetative', veg_late: 'Late vegetative', flower_early: 'Early flower', flower_late: 'Late flower', dry: 'Drying'},
        status: {on_target: 'On target', vpd_low: 'VPD low', vpd_high: 'VPD high', too_cold: 'Too cold', too_warm: 'Too warm', too_dry: 'Too dry', too_humid: 'Too humid'},
        temperature: 'Temperature', humidity: 'Humidity', co2: 'CO₂', dewPoint: 'Dew point',
        dewPointShort: 'Dew point',
        fans: 'Fans', on: 'On', off: 'Off', unavailable: 'Unavailable',
        target: 'target', margin: 'margin', noHistory: 'No history yet', noRooms: 'Add a room to this card',
        settings: 'Room settings', sensorsGroup: 'Sensors', paramsGroup: 'Parameters',
        leafSensor: 'Leaf (infrared)', leafDrop: 'Leaf colder than air', tripMinutes: 'Off target before alerting',
        clearMinutes: 'On target before clearing', ambientCo2: 'Room is not CO₂ enriched',
        none: '— none —', save: 'Save', cancel: 'Cancel', saving: 'Saving…', saved: 'Saved',
        saveFailed: 'Could not save', noEntry: 'Name a status sensor of the integration to edit settings here.',
        now: 'now', lowest: 'low', highest: 'high',
        addFan: 'Add fan', fanName: 'Name', fanSearch: 'Search entity…', removeFan: 'Remove',
        duplicateFan: 'The same fan is listed twice.',
        power: 'Power', powerSearch: 'Power sensor (optional)',
        openHistory: 'Open history', close: 'Close',
        cyclePattern: [' cycle: ', ' min on, ', ' min off'], paused: 'timer paused',
        turnsOnIn: 'on in', turnsOffIn: 'off in',
        insideTarget: 'inside the target', belowTarget: 'under the target', aboveTarget: 'over the target',
    },
    pt: {
        band: {under: 'Baixa transpiração', veg_early: 'Vegetativo inicial', veg_late: 'Vegetativo tardio', flower: 'Floração', over: 'Acima da faixa'},
        phase: {propagation: 'Propagação', veg_early: 'Vegetativo inicial', veg_late: 'Vegetativo tardio', flower_early: 'Floração inicial', flower_late: 'Floração tardia', dry: 'Secagem'},
        status: {on_target: 'Na faixa', vpd_low: 'VPD baixo', vpd_high: 'VPD alto', too_cold: 'Frio demais', too_warm: 'Quente demais', too_dry: 'Seco demais', too_humid: 'Úmido demais'},
        temperature: 'Temperatura', humidity: 'Umidade', co2: 'CO₂', dewPoint: 'Ponto de orvalho',
        dewPointShort: 'P. de orvalho',
        fans: 'Ventiladores', on: 'Ligado', off: 'Desligado', unavailable: 'Indisponível',
        target: 'alvo', margin: 'margem', noHistory: 'Ainda sem histórico', noRooms: 'Adicione uma sala a este card',
        settings: 'Ajustes da sala', sensorsGroup: 'Sensores', paramsGroup: 'Parâmetros',
        leafSensor: 'Folha (infravermelho)', leafDrop: 'Folha mais fria que o ar', tripMinutes: 'Fora da faixa antes de alertar',
        clearMinutes: 'Na faixa antes de desligar', ambientCo2: 'Sala sem enriquecimento de CO₂',
        none: '— nenhum —', save: 'Salvar', cancel: 'Cancelar', saving: 'Salvando…', saved: 'Salvo',
        saveFailed: 'Não consegui salvar', noEntry: 'Informe um sensor de status da integração para ajustar por aqui.',
        now: 'agora', lowest: 'mín', highest: 'máx',
        addFan: 'Adicionar ventilador', fanName: 'Nome', fanSearch: 'Buscar entidade…', removeFan: 'Remover',
        duplicateFan: 'O mesmo ventilador aparece duas vezes.',
        power: 'Potência', powerSearch: 'Sensor de potência (opcional)',
        openHistory: 'Abrir histórico', close: 'Fechar',
        cyclePattern: [' ciclo: ', ' min ligado, ', ' min desligado'], paused: 'timer pausado',
        turnsOnIn: 'liga em', turnsOffIn: 'desliga em',
        insideTarget: 'dentro do alvo', belowTarget: 'abaixo do alvo', aboveTarget: 'acima do alvo',
    },
};

/* Arden Buck, the same curve the integration uses, for rooms configured with
   raw sensors instead of the integration entities. */
const buckGamma = t => (18.678 - t / 234.5) * (t / (257.14 + t));
const saturationPressure = t => 0.61121 * Math.exp(buckGamma(t));
const vapourPressureDeficit = (leaf, air, rh) => saturationPressure(leaf) - saturationPressure(air) * rh / 100;
const dewPoint = (air, rh) => {
    /* Inversao exata: manter o termo t/234.5 vira uma quadratica, e a raiz
       menor e a fisica. A forma fechada usual erra ~0,1 grau. */
    const gamma = Math.log(Math.max(rh, 1e-6) / 100) + buckGamma(air);
    const linear = 234.5 * (18.678 - gamma);
    const discriminant = linear * linear - 4 * 234.5 * 257.14 * gamma;
    return (linear - Math.sqrt(Math.max(discriminant, 0))) / 2;
};

const STYLE = `
:host { display: block;
  --ws-teal: var(--primary-color, #22ab9c);
  --ws-amber: var(--warning-color, #e7c12b);
  --ws-amber-line: rgba(231, 193, 43, .5);
  --ws-teal-line: rgba(34, 171, 156, .45);
  --ws-teal-wash: rgba(34, 171, 156, .10);
  --ws-teal-faint: rgba(34, 171, 156, .06);
  --ws-teal-glow: rgba(34, 171, 156, .55);
  --ws-green: #76d84b;
}
ha-card { padding: 14px 16px 16px; display: flex; flex-direction: column; gap: 14px;
  container-type: inline-size; }
[hidden] { display: none !important; }
button { font: inherit; cursor: pointer; }
button:focus-visible, select:focus-visible { outline: 2px solid var(--primary-color); outline-offset: 2px; }

/* Tudo que é controle no topo usa a mesma pastilha: mesma altura, mesmo
   raio, mesma borda. É o que faz a linha parecer uma linha só. */
.header { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
.header-right { display: flex; align-items: center; gap: 6px; flex: 0 0 auto; }
.chip { height: 30px; box-sizing: border-box; padding: 0 12px; display: inline-flex; align-items: center;
  gap: 6px; border: 1px solid var(--divider-color); border-radius: 15px; background: transparent;
  color: var(--primary-text-color); font-size: 13px; white-space: nowrap; }

.rooms { display: flex; gap: 6px; overflow-x: auto; scrollbar-width: thin; min-width: 0; }
.rooms button { flex: 0 0 auto; appearance: none; }
.rooms button.on { border-color: var(--ws-teal); background: var(--ws-teal);
  color: var(--text-primary-color, #fff); }

.status { gap: 7px; }
.status .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ws-green); flex: 0 0 auto; }
.status.drift { border-color: var(--ws-amber-line); color: var(--ws-amber); }
.status.drift .dot { background: var(--ws-amber); }

.phase { padding-right: 8px; }
.phase select { appearance: none; border: 0; background: transparent; color: inherit; font: inherit;
  cursor: pointer; padding-right: 2px; }
.phase .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ws-teal); flex: 0 0 auto; }

.gear { width: 30px; padding: 0; justify-content: center; color: var(--secondary-text-color);
  --mdc-icon-size: 17px; cursor: pointer; }
.gear:hover { color: var(--ws-teal); border-color: var(--ws-teal); }

/* A leitura é texto do próprio SVG: encolhe junto com o gráfico, então nunca
   briga com os rótulos das bandas, em nenhuma largura de card. */
.reading-value { fill: var(--primary-text-color); font-size: 24px; font-weight: 500; letter-spacing: -.02em; }
.reading-label { fill: var(--secondary-text-color); font-size: 14px; font-weight: 500; letter-spacing: .04em; }
.reading-unit { fill: var(--secondary-text-color); font-size: 13px; font-weight: 400; }

.tiles { display: grid; grid-template-columns: repeat(var(--tile-columns, 4), minmax(0, 1fr)); gap: 10px; }
.tile { display: flex; flex-direction: column; gap: 7px; min-width: 0; border: 1px solid var(--divider-color);
  border-radius: 10px; padding: 10px 11px 12px; }
.tile .label { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; line-height: 1.25;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  color: var(--secondary-text-color); }
/* "P. DE ORVALHO" é o único rótulo que não cabe numa coluna de 110px: só ele
   cede fonte e espaçamento, e só enquanto a coluna for estreita. */
.tile[data-key="dew"] .label { font-size: clamp(9.4px, 2.05cqw, 11px); letter-spacing: .03em; }

@container (max-width: 430px) {
  .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  /* Em duas colunas sobra largura: o rótulo do orvalho volta ao tamanho dos outros. */
  .tile[data-key="dew"] .label { font-size: 11px; letter-spacing: .06em; }
}
.tile .value { display: flex; align-items: baseline; gap: 4px; font-size: 21px; font-weight: 500;
  font-variant-numeric: tabular-nums; color: var(--primary-text-color); }
.tile .value .unit { font-size: 12px; font-weight: 400; color: var(--secondary-text-color); }
.tile.drift .value { color: var(--error-color, #ce4234); }
.track { position: relative; height: 6px; border-radius: 3px; background: var(--secondary-background-color); }
.zone { position: absolute; top: 0; bottom: 0; border-radius: 3px; background: var(--primary-color); opacity: .32; }
.pin { position: absolute; top: -3px; width: 3px; height: 12px; border-radius: 2px;
  background: var(--primary-text-color); transform: translateX(-1.5px); }
.tile.drift .pin { background: var(--error-color, #ce4234); }
.tile .window { font-size: 11.5px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
/* O VPD ocupa a fileira inteira numa linha só: rótulo, leitura, a barra
   esticando no espaço que sobra e a faixa-alvo fechando à direita. */
.tile.banner { grid-column: 1 / -1; display: grid; align-items: center; gap: 0;
  grid-template-columns: auto auto minmax(48px, 1fr) auto; column-gap: 12px;
  padding: 7px 12px; }
.tile.banner .label { grid-row: 1; }
.tile.banner .value { grid-row: 1; font-size: 22px; line-height: 1.15; }
.tile.banner .track { grid-row: 1; height: 6px; }
.tile.banner .pin { top: -3px; height: 12px; }
.tile.banner .window { grid-row: 1; white-space: nowrap; }

@container (max-width: 430px) {
  /* Sem largura para tudo, a faixa-alvo sai: ela continua no title do box. */
  .tile.banner { grid-template-columns: auto auto minmax(36px, 1fr); column-gap: 10px; }
  .tile.banner .window { display: none; }
}

.tile.pick { cursor: pointer; }
.tile.pick:hover { border-color: var(--ws-teal-line); }

/* A leitura mora dentro do grafico, sobre a faixa de cima, com um fundo
   discreto para continuar legivel em cima de qualquer banda. */
/* Como no card de VPD original: a leitura ocupa a faixa livre no topo do
   gráfico, encostada à direita, sem caixa por trás — as bandas começam
   abaixo dela, não atrás dela. */
.axis-value { fill: var(--secondary-text-color); font-size: 10.5px; }

.chart-wrap { position: relative; }
.history-wrap { position: relative; }

dialog.history { border: 1px solid var(--divider-color); border-radius: 14px; padding: 0;
  width: min(760px, 94vw); background: var(--card-background-color); color: var(--primary-text-color); }
dialog.history::backdrop { background: rgba(0, 0, 0, .55); }
.history-body { display: flex; flex-direction: column; gap: 10px; padding: 16px; }
.history-head { display: flex; align-items: center; gap: 10px; }
.history-head h3 { margin: 0; font-size: 16px; font-weight: 600; flex: 1 1 auto; }
.range { display: flex; gap: 4px; }
.range button { appearance: none; border: 1px solid var(--divider-color); border-radius: 12px; padding: 3px 10px;
  background: transparent; color: var(--secondary-text-color); font-size: 12px; }
.range button.on { border-color: var(--ws-teal); color: var(--ws-teal); background: var(--ws-teal-faint); }
.history .close { appearance: none; border: 0; background: transparent; color: var(--secondary-text-color);
  --mdc-icon-size: 20px; display: grid; place-items: center; }
.history-chart { display: block; width: 100%; height: auto; }
.spot { fill: var(--ws-teal); opacity: .8; }
.spot-hit { fill: transparent; stroke: transparent; pointer-events: all; cursor: crosshair; }
.spot-hit:focus { outline: none; stroke: var(--ws-teal); stroke-width: 2; }
.tip { position: absolute; z-index: 3; display: none; transform: translate(-50%, calc(-100% - 12px));
  box-sizing: border-box; width: max-content; max-width: min(240px, calc(100% - 12px)); padding: 7px 9px;
  border: 1px solid var(--divider-color); border-radius: 8px; background: var(--card-background-color);
  color: var(--primary-text-color); box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0, 0, 0, .3));
  pointer-events: none; font-size: 12px; line-height: 1.35; }
.tip.show { display: grid; gap: 2px; }
.tip.below { transform: translate(-50%, 12px); }
.tip strong { font-weight: 600; font-variant-numeric: tabular-nums; }
.hover-catch { fill: transparent; pointer-events: all; cursor: crosshair; }
.cursor-line { stroke: var(--primary-text-color); stroke-width: 1; opacity: .35; pointer-events: none; }
.cursor-dot { fill: var(--ws-teal); stroke: var(--card-background-color); stroke-width: 2; pointer-events: none; }

.fan-rows { display: flex; flex-direction: column; gap: 6px; }
.fan-row-edit { display: grid; grid-template-columns: minmax(0, .9fr) minmax(0, 1.2fr) minmax(0, 1fr) auto;
  gap: 6px; align-items: center; }
.fan-row-edit input { font: inherit; min-width: 0; padding: 6px 8px; border-radius: 8px;
  border: 1px solid var(--divider-color); background: var(--secondary-background-color);
  color: var(--primary-text-color); }
.row-drop { appearance: none; border: 1px solid var(--divider-color); border-radius: 8px; background: transparent;
  color: var(--secondary-text-color); padding: 4px 8px; --mdc-icon-size: 16px; }
.row-drop:hover { color: var(--error-color, #ce4234); border-color: var(--error-color, #ce4234); }
.fan-block { display: flex; flex-direction: column; gap: 4px; padding-bottom: 6px;
  border-bottom: 1px solid var(--divider-color); }
.fan-block:last-of-type { border-bottom: 0; }
.fan-cycle { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--secondary-text-color); }
.fan-cycle input[type="number"] { width: 58px; font: inherit; padding: 4px 6px; border-radius: 8px;
  border: 1px solid var(--divider-color); background: var(--secondary-background-color);
  color: var(--primary-text-color); }
.fan-cycle input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--primary-color); }

.add-fan { appearance: none; align-self: flex-start; display: inline-flex; align-items: center; gap: 6px;
  border: 1px dashed var(--divider-color); border-radius: 10px; padding: 6px 10px; background: transparent;
  color: var(--secondary-text-color); --mdc-icon-size: 16px; }
.add-fan:hover { border-color: var(--ws-teal); color: var(--ws-teal); }
.tip span { color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
.target-band { fill: var(--ws-teal); opacity: .16; }
.target-edge { stroke: var(--ws-teal); stroke-width: 1; stroke-dasharray: 5 4; opacity: .7; }

svg.chart { display: block; width: 100%; height: auto; border-radius: 10px; }
.grid { stroke: var(--divider-color); stroke-width: 1; }
.tick { fill: var(--secondary-text-color); font-size: 11px; }
.band-label { fill: var(--primary-text-color); font-size: 12px; font-weight: 500; }
.trend { fill: none; stroke: var(--primary-color); stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
.edge { stroke: var(--primary-text-color); stroke-width: 1; stroke-dasharray: 5 4; opacity: .55; }
.head { fill: var(--primary-color); stroke: var(--card-background-color); stroke-width: 3; }
.head-label { fill: var(--primary-text-color); font-size: 12px; font-weight: 500; }
.empty { padding: 20px 0; text-align: center; color: var(--secondary-text-color); }

/* Same geometry as the light tiles of the Light Scheduler card — 52px tall,
   two per row, icon plus copy on the left and a pill on the right. Only the
   palette changes: teal for a running fan instead of amber for a lit lamp. */
.fans { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--divider-color); padding-top: 12px; }
.fans .title { font-size: 11px; letter-spacing: .08em; text-transform: uppercase; color: var(--secondary-text-color); }
.fan-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }

.fan { min-width: 0; height: 52px; padding: 6px 7px; display: grid;
  grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 6px; text-align: left;
  border: 1px solid rgba(127, 127, 127, .22); border-radius: 7px; background: rgba(127, 127, 127, .045); }
.fan:hover { background: rgba(127, 127, 127, .1); }
.fan.on { border-color: var(--ws-teal-line);
  background: linear-gradient(90deg, var(--ws-teal-wash), rgba(127, 127, 127, .035)); }

.fan-main { min-width: 0; height: 100%; padding: 0; display: grid; grid-template-columns: 30px minmax(0, 1fr);
  align-items: center; gap: 6px; text-align: left; border: 0; background: transparent; cursor: pointer; }
.fan-main:disabled { cursor: default; }
.fan .blade { --mdc-icon-size: 29px; color: #686a6b; filter: grayscale(1); }
.fan.on .blade { color: var(--ws-teal); filter: drop-shadow(0 0 6px var(--ws-teal-glow)); }

.fan-copy { min-width: 0; }
.fan-copy strong, .fan-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fan-copy strong { font-size: 11px; line-height: 1.25; color: var(--primary-text-color); }
.fan-copy small { margin-top: 2px; color: var(--secondary-text-color); font-size: 9px; }
.fan.on .fan-copy small { color: var(--ws-green); }
.fan.gone .fan-main { opacity: .55; }

.speed-pill { height: 25px; padding: 0 6px; display: inline-flex; align-items: center; gap: 3px;
  white-space: nowrap; border: 1px solid rgba(127, 127, 127, .35); border-radius: 6px;
  color: var(--secondary-text-color); background: transparent; font-size: 9px; cursor: pointer;
  font-variant-numeric: tabular-nums; }
.speed-pill ha-icon { --mdc-icon-size: 12px; }
.speed-pill:hover:not(:disabled) { background: var(--ws-teal-wash); border-color: var(--ws-teal); }
.speed-pill:disabled { opacity: .5; cursor: default; }
.fan.on .speed-pill { border-color: var(--ws-teal-line); color: var(--ws-teal); background: var(--ws-teal-faint); }
.power-pill { height: 25px; padding: 0 6px; display: inline-flex; align-items: center; gap: 3px; white-space: nowrap;
  border: 1px solid rgba(127, 127, 127, .35); border-radius: 6px; color: var(--secondary-text-color);
  background: transparent; font-size: 9px; cursor: pointer; font-variant-numeric: tabular-nums;
  --mdc-icon-size: 12px; }
.power-pill:hover { border-color: var(--ws-teal); color: var(--ws-teal); background: var(--ws-teal-wash); }
.fan.on .power-pill { border-color: var(--ws-teal-line); color: var(--ws-teal); background: var(--ws-teal-faint); }

@media (prefers-reduced-motion: no-preference) {
  .fan.on .blade { animation: spin 2.6s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
}

@media (max-width: 420px) {
  .fan-grid { grid-template-columns: 1fr; }
}

/* gear and the settings sheet */
.gear { appearance: none; border: 1px solid var(--divider-color); border-radius: 16px; background: transparent;
  color: var(--secondary-text-color); padding: 5px 9px; display: inline-grid; place-items: center;
  --mdc-icon-size: 18px; }
.gear:hover { color: var(--primary-color); border-color: var(--primary-color); }

dialog.sheet { border: 1px solid var(--divider-color); border-radius: 14px; padding: 0; width: min(440px, 92vw);
  background: var(--card-background-color); color: var(--primary-text-color); }
dialog.sheet::backdrop { background: rgba(0, 0, 0, .55); }
.sheet-body { display: flex; flex-direction: column; gap: 14px; padding: 18px; }
.sheet h3 { margin: 0; font-size: 16px; font-weight: 600; }
.sheet .group { display: flex; flex-direction: column; gap: 9px; }
.sheet .group-title { font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--secondary-text-color); }
.field { display: grid; grid-template-columns: 1fr minmax(0, 190px); align-items: center; gap: 10px; font-size: 14px; }
.field select, .field input[type="number"] { font: inherit; width: 100%; box-sizing: border-box; padding: 6px 8px;
  border-radius: 8px; border: 1px solid var(--divider-color); background: var(--secondary-background-color);
  color: var(--primary-text-color); }
.field input[type="checkbox"] { justify-self: start; width: 18px; height: 18px; accent-color: var(--primary-color); }
.sheet-actions { display: flex; justify-content: flex-end; align-items: center; gap: 8px; }
.sheet-note { margin-right: auto; font-size: 12.5px; color: var(--secondary-text-color); }
.sheet-note.bad { color: var(--error-color, #ce4234); }
.sheet-actions button { appearance: none; border-radius: 16px; padding: 6px 14px; border: 1px solid var(--divider-color);
  background: transparent; color: var(--primary-text-color); }
.sheet-actions button.save { border-color: var(--primary-color); background: var(--primary-color);
  color: var(--text-primary-color, #fff); }
.sheet-actions button[disabled] { opacity: .6; cursor: default; }

@media (max-width: 420px) {
  .tiles { grid-template-columns: repeat(2, 1fr); }
  .reading .value { font-size: 26px; }
}
`;

class WeatherScheduleCard extends HTMLElement {
    static listId = 0;

    #hass = null;
    #config = null;
    #room = 0;
    #built = false;
    #dirty = false;
    #series = [];
    #seriesKey = '';
    #seriesAt = 0;
    #plots = new WeakMap();
    #ticker = null;
    #historySpec = null;
    #historyHours = 24;
    #request = 0;
    #node = {};

    static getStubConfig() {
        return {rooms: [{name: 'Room'}]};
    }

    setConfig(config) {
        if (!config || !Array.isArray(config.rooms) || !config.rooms.length) {
            throw new Error('weather-schedule-card: define at least one room');
        }
        this.#config = config;
        this.#room = 0;
        this.#seriesKey = '';
        this.#request++;
        this.#built = false;
        this.#node = {};
        if (this.shadowRoot) this.shadowRoot.replaceChildren();
        this.#schedule();
    }

    connectedCallback() {
        // A contagem regressiva precisa andar mesmo quando nada mais muda.
        clearInterval(this.#ticker);
        this.#ticker = setInterval(() => this.#schedule(), 30000);
    }

    disconnectedCallback() {
        clearInterval(this.#ticker);
        this.#ticker = null;
        // Respostas pendentes não devem pintar um card que saiu da tela.
        this.#request++;
    }

    set hass(hass) {
        this.#hass = hass;
        this.#schedule();
    }

    getCardSize() {
        return 12;
    }

    getGridOptions() {
        return {columns: 12, min_columns: 6, rows: 10, min_rows: 8};
    }

    /* Home Assistant pushes hass several times per frame; coalesce without
       requestAnimationFrame, which never fires while the tab is in the back. */
    #schedule() {
        if (this.#dirty || !this.#config || !this.#hass) return;
        this.#dirty = true;
        setTimeout(() => {
            this.#dirty = false;
            try {
                this.#render();
            } catch (error) {
                console.error('weather-schedule-card', error);
            }
        }, 0);
    }

    /* O card fala português do Brasil por padrão, mesmo num Home Assistant em
       inglês; `language: en` no YAML troca para inglês. */
    get #text() {
        const chosen = String(this.#config?.language || '').toLowerCase();
        if (chosen.startsWith('en')) return TEXT.en;
        return TEXT.pt;
    }

    #locale() {
        const chosen = String(this.#config?.language || '').toLowerCase();
        if (chosen.startsWith('en')) return 'en';
        return 'pt-BR';
    }

    #number(value, digits = 1) {
        if (!Number.isFinite(value)) return '--';
        return new Intl.NumberFormat(this.#locale(), {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits,
        }).format(value);
    }

    #state(entityId) {
        return entityId ? this.#hass.states[entityId] : undefined;
    }

    #value(entityId) {
        const parsed = Number.parseFloat(this.#state(entityId)?.state);
        return Number.isFinite(parsed) ? parsed : Number.NaN;
    }

    /* O backend converte a temperatura antes de calcular; o card lê o sensor
       cru e precisa fazer o mesmo, senão °F entra na fórmula como se fosse °C. */
    #celsius(entityId) {
        const value = this.#value(entityId);
        if (!Number.isFinite(value)) return Number.NaN;
        const unit = this.#state(entityId)?.attributes?.unit_of_measurement;
        if (unit === '\u00b0F') return (value - 32) * 5 / 9;
        if (unit === 'K') return value - 273.15;
        return value;
    }

    /* A room may name its entities one by one, or name only the status sensor
       and let the card find its siblings on the same device.

       Matching goes by translation key, never by the entity_id: Home Assistant
       builds ids in the language of the instance, so the dew point of this very
       room is sensor.<room>_ponto_de_orvalho on a Portuguese install. */
    #resolve(room) {
        const resolved = {...room};
        const registry = this.#hass.entities;
        const anchor = room.status && registry?.[room.status];
        if (anchor?.device_id) {
            const family = Object.entries(registry)
                .filter(([, entry]) => entry.device_id === anchor.device_id);
            const byKey = key => family.find(([, entry]) => entry.translation_key === key)?.[0];
            const bySuffix = suffix => family.find(([entityId]) => entityId.endsWith(suffix))?.[0];
            resolved.vpd ??= byKey('vpd') || bySuffix('_vpd');
            resolved.dew_point ??= byKey('dew_point') || bySuffix('_dew_point');
            resolved.phase ??= byKey('phase')
                || family.find(([entityId]) => entityId.startsWith('select.'))?.[0];
            resolved.leaf_number ??= byKey('leaf_drop');
        }

        // The status sensor also publishes which entities feed the room, so the
        // raw sensors never have to be repeated in the card configuration.
        const sources = this.#state(room.status)?.attributes?.sources || {};
        resolved.temperature ??= sources.air_temperature;
        resolved.humidity ??= sources.relative_humidity;
        resolved.co2 ??= sources.carbon_dioxide;
        return resolved;
    }

    #entryId(room) {
        const anchor = this.#hass.entities?.[room.status];
        const device = anchor?.device_id ? this.#hass.devices?.[anchor.device_id] : null;
        return device?.config_entries?.[0] || device?.primary_config_entry || device?.config_entry_id;
    }

    /* Candidate sensors for one field, skipping this integration's own output
       so a room can never be pointed at the numbers it produces. */
    #entityChoices(deviceClass) {
        const registry = this.#hass.entities || {};
        return Object.entries(this.#hass.states)
            .filter(([entityId, state]) => entityId.startsWith('sensor.')
                && state.attributes.device_class === deviceClass
                && registry[entityId]?.platform !== 'weather_schedule')
            .map(([entityId, state]) => ({entityId, name: state.attributes.friendly_name || entityId}))
            .sort((a, b) => a.name.localeCompare(b.name, this.#locale()));
    }

    #groupTitle(label) {
        const node = document.createElement('div');
        node.className = 'group-title';
        node.textContent = label;
        return node;
    }

    #field(label) {
        const row = document.createElement('label');
        row.className = 'field';
        const caption = document.createElement('span');
        caption.textContent = label;
        row.appendChild(caption);
        return row;
    }

    #selectField(field, label, deviceClass, current, required) {
        const row = this.#field(label);
        const select = document.createElement('select');
        select.dataset.field = field;
        if (!required) {
            const blank = document.createElement('option');
            blank.value = '';
            blank.textContent = this.#text.none;
            select.appendChild(blank);
        }
        for (const choice of this.#entityChoices(deviceClass)) {
            const option = document.createElement('option');
            option.value = choice.entityId;
            option.textContent = choice.name;
            select.appendChild(option);
        }
        // An entity that no longer exists still deserves to be shown as chosen.
        if (current && ![...select.options].some(option => option.value === current)) {
            const orphan = document.createElement('option');
            orphan.value = current;
            orphan.textContent = current;
            select.appendChild(orphan);
        }
        select.value = current || '';
        row.appendChild(select);
        return row;
    }

    #numberField(field, label, current, min, max, step) {
        const row = this.#field(label);
        const input = document.createElement('input');
        input.type = 'number';
        input.dataset.field = field;
        input.min = String(min);
        input.max = String(max);
        input.step = String(step);
        input.value = String(current);
        row.appendChild(input);
        return row;
    }

    #checkField(field, label, current) {
        const row = this.#field(label);
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.field = field;
        input.checked = current;
        row.appendChild(input);
        return row;
    }

    #openSheet() {
        const room = this.#resolve(this.#config.rooms[this.#room] || {});
        const text = this.#text;
        const attributes = this.#state(room.status)?.attributes || {};
        const sources = attributes.sources || {};
        const settings = attributes.settings || {};

        this.#node.sheetTitle.textContent = room.name ? `${text.settings} · ${room.name}` : text.settings;
        this.#node.sheetSave.textContent = text.save;
        this.#node.sheetCancel.textContent = text.cancel;
        this.#node.sheetNote.textContent = '';
        this.#node.sheetNote.classList.remove('bad');

        const entry = this.#entryId(room);
        this.#node.sheetSave.disabled = !entry;
        if (!entry) {
            this.#node.sheetNote.textContent = text.noEntry;
            this.#node.sheetNote.classList.add('bad');
        }

        this.#node.sheetSensors.replaceChildren(
            this.#groupTitle(text.sensorsGroup),
            this.#selectField('air_temperature', text.temperature, 'temperature', sources.air_temperature, true),
            this.#selectField('relative_humidity', text.humidity, 'humidity', sources.relative_humidity, true),
            this.#selectField('carbon_dioxide', text.co2, 'carbon_dioxide', sources.carbon_dioxide, false),
            this.#selectField('leaf_sensor', text.leafSensor, 'temperature', sources.leaf_sensor, false),
        );
        this.#node.sheetFans.replaceChildren(this.#groupTitle(text.fans));
        const rows = document.createElement('div');
        rows.className = 'fan-rows';
        for (const fan of this.#roomFans(room)) rows.appendChild(this.#fanRow(fan));
        this.#node.sheetFans.appendChild(rows);
        const add = document.createElement('button');
        add.type = 'button';
        add.className = 'add-fan';
        add.innerHTML = `<ha-icon icon="mdi:plus"></ha-icon><span></span>`;
        add.querySelector('span').textContent = text.addFan;
        add.addEventListener('click', () => {
            rows.appendChild(this.#fanRow({}));
            rows.lastElementChild.querySelector('input').focus();
        });
        this.#node.sheetFans.appendChild(add);

        this.#node.sheetParams.replaceChildren(
            this.#groupTitle(text.paramsGroup),
            this.#numberField('leaf_drop', text.leafDrop, settings.leaf_drop ?? 2, 0, 6, 0.1),
            this.#numberField('trip_minutes', text.tripMinutes, settings.trip_minutes ?? 15, 1, 240, 1),
            this.#numberField('clear_minutes', text.clearMinutes, settings.clear_minutes ?? 5, 1, 240, 1),
            this.#checkField('ambient_co2', text.ambientCo2, Boolean(settings.ambient_co2)),
        );
        this.#node.sheet.showModal();
    }

    #fanRow(fan = {}) {
        const row = document.createElement('div');
        row.className = 'fan-row-edit';
        const state = fan.entity ? this.#state(fan.entity) : null;

        const name = document.createElement('input');
        name.type = 'text';
        name.dataset.fanName = '';
        name.placeholder = this.#text.fanName;
        name.value = fan.name || state?.attributes?.friendly_name || '';

        const picker = document.createElement('input');
        picker.type = 'search';
        picker.dataset.fanEntity = '';
        picker.setAttribute('list', `ws-fan-list-${++WeatherScheduleCard.listId}`);
        picker.placeholder = this.#text.fanSearch;
        picker.value = fan.entity || '';

        const list = document.createElement('datalist');
        list.id = picker.getAttribute('list');
        for (const choice of this.#fanChoices()) {
            const option = document.createElement('option');
            option.value = choice.entityId;
            option.label = choice.name;
            list.appendChild(option);
        }
        // Escolher pelo nome preenche o campo de nome quando ele ainda está vazio.
        picker.addEventListener('change', () => {
            const picked = this.#state(picker.value)?.attributes?.friendly_name;
            if (picked && !name.value.trim()) name.value = picked;
        });

        const power = document.createElement('input');
        power.type = 'search';
        power.dataset.fanPower = '';
        power.setAttribute('list', `ws-power-list-${++WeatherScheduleCard.listId}`);
        power.placeholder = this.#text.powerSearch;
        power.value = fan.power || '';

        const powerList = document.createElement('datalist');
        powerList.id = power.getAttribute('list');
        for (const choice of this.#powerChoices()) {
            const option = document.createElement('option');
            option.value = choice.entityId;
            option.label = choice.name;
            powerList.appendChild(option);
        }

        const drop = document.createElement('button');
        drop.type = 'button';
        drop.className = 'row-drop';
        drop.innerHTML = '<ha-icon icon="mdi:delete-outline"></ha-icon>';
        drop.setAttribute('aria-label', this.#text.removeFan);
        drop.addEventListener('click', () => row.remove());

        row.append(name, picker, list, power, powerList, drop);

        const cycle = fan.cycle || {};
        const line = document.createElement('label');
        line.className = 'fan-cycle';
        const enabled = document.createElement('input');
        enabled.type = 'checkbox';
        enabled.dataset.cycleEnabled = '';
        enabled.checked = Boolean(cycle.enabled);
        const on = document.createElement('input');
        on.type = 'number';
        on.min = '1';
        on.dataset.cycleOn = '';
        on.value = cycle.on || 15;
        const off = document.createElement('input');
        off.type = 'number';
        off.min = '1';
        off.dataset.cycleOff = '';
        off.value = cycle.off || 45;
        const [before, middle, after] = this.#text.cyclePattern;
        line.append(enabled, document.createTextNode(before), on,
            document.createTextNode(middle), off, document.createTextNode(after));

        const block = document.createElement('div');
        block.className = 'fan-block';
        block.append(row, line);
        return block;
    }

    #powerChoices() {
        return Object.entries(this.#hass.states)
            .filter(([entityId, state]) => entityId.startsWith('sensor.')
                && (state.attributes.device_class === 'power'
                    || ['W', 'kW'].includes(state.attributes.unit_of_measurement)))
            .map(([entityId, state]) => ({entityId, name: state.attributes.friendly_name || entityId}))
            .sort((a, b) => a.name.localeCompare(b.name, this.#locale()));
    }

    #fanChoices() {
        return Object.entries(this.#hass.states)
            .filter(([entityId]) => entityId.startsWith('fan.') || entityId.startsWith('switch.'))
            .map(([entityId, state]) => ({entityId, name: state.attributes.friendly_name || entityId}))
            .sort((a, b) => a.name.localeCompare(b.name, this.#locale()));
    }

    async #saveSheet() {
        const text = this.#text;
        const room = this.#resolve(this.#config.rooms[this.#room] || {});
        const entry = this.#entryId(room);
        if (!entry) return;

        const field = name => this.#node.sheet.querySelector(`[data-field="${name}"]`);
        const sensors = {
            air_temperature: field('air_temperature').value,
            relative_humidity: field('relative_humidity').value,
            leaf_drop: Number(field('leaf_drop').value),
        };
        if (field('carbon_dioxide').value) sensors.carbon_dioxide = field('carbon_dioxide').value;
        if (field('leaf_sensor').value) sensors.leaf_sensor = field('leaf_sensor').value;

        const alert = {
            trip_minutes: Number(field('trip_minutes').value),
            clear_minutes: Number(field('clear_minutes').value),
            ambient_co2: field('ambient_co2').checked,
        };

        const fans = this.#collectFans();
        if (new Set(fans.map(fan => fan.entity_id)).size !== fans.length) {
            this.#node.sheetNote.textContent = text.duplicateFan;
            this.#node.sheetNote.classList.add('bad');
            return;
        }

        this.#node.sheetSave.disabled = true;
        this.#node.sheetNote.classList.remove('bad');
        this.#node.sheetNote.textContent = text.saving;
        try {
            await this.#submitOptions(entry, 'sensors', sensors);
            await this.#submitOptions(entry, 'alert', alert);
            await this.#submitOptions(entry, 'fans', {
                fans: fans.map(fan => fan.entity_id),
                fan_names: Object.fromEntries(fans.map(fan => [fan.entity_id, fan.name])),
                fan_powers: Object.fromEntries(fans.map(fan => [fan.entity_id, fan.power])),
                fan_cycles: Object.fromEntries(fans.map(fan => [fan.entity_id, fan.cycle])),
            });
            // The leaf drop also lives as a number entity, which restores its own
            // value after the reload; set it too or it would win over the form.
            if (room.leaf_number) {
                await this.#hass.callService('number', 'set_value', {
                    entity_id: room.leaf_number,
                    value: sensors.leaf_drop,
                });
            }
            this.#seriesKey = '';
            this.#node.sheetNote.textContent = text.saved;
            setTimeout(() => this.#node.sheet.close(), 700);
        } catch (error) {
            console.error('weather-schedule-card', error);
            this.#node.sheetNote.textContent = `${text.saveFailed}: ${this.#reason(error)}`;
            this.#node.sheetNote.classList.add('bad');
        } finally {
            this.#node.sheetSave.disabled = false;
        }
    }

    /* Home Assistant answers a rejected step with an object, and printing it
       raw gives the useless "[object Object]". Dig out something readable. */
    #reason(thing) {
        if (!thing) return 'erro';
        if (typeof thing === 'string') return thing;
        const errors = thing.errors || thing.body?.errors;
        if (errors) {
            return Object.entries(errors).map(([field, detail]) =>
                `${field}: ${Array.isArray(detail) ? detail.join(', ') : detail}`).join(' | ');
        }
        return thing.message || thing.body?.message || thing.type || JSON.stringify(thing);
    }

    #collectFans() {
        return [...this.#node.sheetFans.querySelectorAll('.fan-block')]
            .map(block => ({
                entity_id: block.querySelector('[data-fan-entity]').value.trim(),
                name: block.querySelector('[data-fan-name]').value.trim(),
                power: block.querySelector('[data-fan-power]').value.trim(),
                cycle: {
                    enabled: block.querySelector('[data-cycle-enabled]').checked,
                    on: Number(block.querySelector('[data-cycle-on]').value) || 0,
                    off: Number(block.querySelector('[data-cycle-off]').value) || 0,
                },
            }))
            .filter(fan => fan.entity_id);
    }

    /* Drives the integration's own options flow, so the card never invents a
       second place where a room's settings live. */
    async #submitOptions(entry, step, payload) {
        const flow = await this.#hass.callApi('POST', 'config/config_entries/options/flow', {handler: entry});
        await this.#hass.callApi('POST', `config/config_entries/options/flow/${flow.flow_id}`, {next_step_id: step});
        const result = await this.#hass.callApi('POST', `config/config_entries/options/flow/${flow.flow_id}`, payload);
        if (result.type !== 'create_entry') {
            throw new Error(this.#reason(result));
        }
    }

    #bounds(room) {
        const attributes = this.#state(room.status)?.attributes || {};
        const bounds = {};
        for (const key of ['vpd_min', 'vpd_max', 'temp_min', 'temp_max', 'rh_min', 'rh_max', 'co2_min', 'co2_max']) {
            const parsed = Number.parseFloat(attributes[key]);
            if (Number.isFinite(parsed)) bounds[key] = parsed;
        }
        return bounds;
    }

    #climate(room) {
        const temperature = this.#celsius(room.temperature);
        const humidity = this.#value(room.humidity);
        let vpd = this.#value(room.vpd);
        if (!Number.isFinite(vpd) && Number.isFinite(temperature) && Number.isFinite(humidity)) {
            const drop = Number.isFinite(Number(room.leaf_drop)) ? Number(room.leaf_drop) : 2;
            vpd = vapourPressureDeficit(temperature - drop, temperature, humidity);
        }
        let dew = this.#value(room.dew_point);
        if (!Number.isFinite(dew) && Number.isFinite(temperature) && Number.isFinite(humidity)) {
            dew = dewPoint(temperature, humidity);
        }
        return {temperature, humidity, vpd, dew, co2: this.#value(room.co2)};
    }

    #render() {
        if (!this.#built) this.#build();
        const room = this.#resolve(this.#config.rooms[this.#room] || {});
        const climate = this.#climate(room);
        const bounds = this.#bounds(room);

        this.#renderRooms();
        this.#renderPhase(room, climate);
        this.#renderReading(room, climate);
        this.#renderTiles(room, climate, bounds);
        this.#renderFans(room);
        this.#loadSeries(room, climate, bounds);
    }

    #build() {
        this.#built = true;
        const root = this.shadowRoot || this.attachShadow({mode: 'open'});
        const style = document.createElement('style');
        style.textContent = STYLE;
        const card = document.createElement('ha-card');
        card.innerHTML = `
            <div class="header">
                <div class="rooms" role="group"></div>
                <div class="header-right">
                    <span class="chip status" hidden><span class="dot"></span><span class="status-text"></span></span>
                    <label class="chip phase" hidden><span class="dot"></span><select></select></label>
                    <button type="button" class="chip gear" title="${this.#text.settings}"
                            aria-label="${this.#text.settings}"><ha-icon icon="mdi:cog"></ha-icon></button>
                </div>
            </div>
            <div class="tiles"></div>
            <div class="chart-wrap">
                <svg class="chart" viewBox="0 0 720 360" role="img"></svg>
                <div class="tip" role="status"></div>
            </div>
            <div class="empty" hidden></div>
            <div class="fans" hidden>
                <div class="title"></div>
                <div class="fan-grid"></div>
            </div>
            <dialog class="history">
                <div class="history-body">
                    <div class="history-head">
                        <h3></h3>
                        <div class="range"></div>
                        <button type="button" class="close" aria-label="${this.#text.close}"><ha-icon icon="mdi:close"></ha-icon></button>
                    </div>
                    <div class="history-wrap">
                        <svg class="history-chart" viewBox="0 0 720 300" role="img"></svg>
                        <div class="tip" role="status"></div>
                    </div>
                    <div class="empty" hidden></div>
                </div>
            </dialog>
            <dialog class="sheet">
                <div class="sheet-body">
                    <h3></h3>
                    <div class="group sensors">
                        <div class="group-title"></div>
                    </div>
                    <div class="group fans-group">
                        <div class="group-title"></div>
                    </div>
                    <div class="group params">
                        <div class="group-title"></div>
                    </div>
                    <div class="sheet-actions">
                        <span class="sheet-note"></span>
                        <button type="button" class="cancel"></button>
                        <button type="button" class="save"></button>
                    </div>
                </div>
            </dialog>`;
        root.replaceChildren(style, card);

        this.#node = {
            rooms: card.querySelector('.rooms'),
            phase: card.querySelector('.phase'),
            phaseSelect: card.querySelector('.phase select'),
            phaseDot: card.querySelector('.phase .dot'),
            gear: card.querySelector('.gear'),
            tiles: card.querySelector('.tiles'),
            chartWrap: card.querySelector('.chart-wrap'),
            status: card.querySelector('.chip.status'),
            statusText: card.querySelector('.status-text'),
            chart: card.querySelector('svg.chart'),
            tip: card.querySelector('.tip'),
            empty: card.querySelector('.empty'),
            fans: card.querySelector('.fans'),
            fansTitle: card.querySelector('.fans .title'),
            fanGrid: card.querySelector('.fan-grid'),
            history: card.querySelector('dialog.history'),
            historyTitle: card.querySelector('.history h3'),
            historyRange: card.querySelector('.history .range'),
            historyWrap: card.querySelector('.history-wrap'),
            historyChart: card.querySelector('.history-chart'),
            historyTip: card.querySelector('.history .tip'),
            historyEmpty: card.querySelector('.history .empty'),
            sheet: card.querySelector('dialog.sheet'),
            sheetTitle: card.querySelector('.sheet h3'),
            sheetSensors: card.querySelector('.group.sensors'),
            sheetFans: card.querySelector('.group.fans-group'),
            sheetParams: card.querySelector('.group.params'),
            sheetNote: card.querySelector('.sheet-note'),
            sheetSave: card.querySelector('.sheet-actions .save'),
            sheetCancel: card.querySelector('.sheet-actions .cancel'),
        };

        this.#node.gear.addEventListener('click', () => this.#openSheet());
        card.querySelector('.history .close').addEventListener('click', () => this.#node.history.close());
        for (const hours of HISTORY_RANGES) {
            const chip = document.createElement('button');
            chip.type = 'button';
            chip.dataset.hours = String(hours);
            chip.textContent = hours < 48 ? `${hours} h` : `${Math.round(hours / 24)} d`;
            chip.addEventListener('click', () => {
                this.#historyHours = hours;
                this.#drawHistory();
            });
            this.#node.historyRange.appendChild(chip);
        }
        this.#node.sheetCancel.addEventListener('click', () => this.#node.sheet.close());
        this.#node.sheetSave.addEventListener('click', () => this.#saveSheet());

        this.#node.phaseSelect.addEventListener('change', event => {
            const room = this.#resolve(this.#config.rooms[this.#room] || {});
            if (room.phase) {
                this.#hass.callService('select', 'select_option', {
                    entity_id: room.phase,
                    option: event.target.value,
                });
            }
        });
    }

    #renderRooms() {
        const container = this.#node.rooms;
        const rooms = this.#config.rooms;
        const print = rooms.map((room, index) => room.name || `Room ${index + 1}`).join('|');
        if (container.dataset.print !== print) {
            container.dataset.print = print;
            container.replaceChildren();
            rooms.forEach((room, index) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'chip';
                button.textContent = room.name || `Room ${index + 1}`;
                button.addEventListener('click', () => {
                    this.#room = index;
                    this.#seriesKey = '';
                    this.#request++;
                    this.#render();
                });
                container.appendChild(button);
            });
        }
        [...container.children].forEach((button, index) => {
            const active = index === this.#room;
            button.classList.toggle('on', active);
            button.setAttribute('aria-pressed', String(active));
        });
        container.hidden = rooms.length < 2;
    }

    #renderPhase(room, climate) {
        const state = this.#state(room.phase);
        this.#node.phase.hidden = !state;
        if (!state) return;

        const options = state.attributes.options || [];
        const select = this.#node.phaseSelect;
        if (select.dataset.print !== options.join('|')) {
            select.dataset.print = options.join('|');
            select.replaceChildren();
            for (const option of options) {
                const node = document.createElement('option');
                node.value = option;
                node.textContent = this.#text.phase[option] || option;
                select.appendChild(node);
            }
        }
        select.value = state.state;
        select.disabled = state.state === 'unavailable';
        this.#node.phaseDot.style.background = this.#bandColor(climate.vpd);
    }

    #bandColor(vpd) {
        if (!Number.isFinite(vpd)) return 'var(--primary-color)';
        return (VPD_BANDS.find(band => vpd >= band.from && vpd < band.to) || VPD_BANDS.at(-1)).color;
    }

    #renderReading(room, climate) {
        const status = this.#state(room.status);
        const known = status && !['unknown', 'unavailable'].includes(status.state);
        const chip = this.#node.status;
        chip.hidden = !known;
        if (!known) return;
        chip.classList.toggle('drift', status.state !== 'on_target');
        this.#node.statusText.textContent = this.#text.status[status.state] || status.state;
    }

    #renderTiles(room, climate, bounds) {
        const text = this.#text;
        const vpd = {
            key: 'vpd', label: 'VPD', value: climate.vpd, unit: 'kPa', digits: 2,
            min: bounds.vpd_min, max: bounds.vpd_max, scale: [0, 2], entity: room.vpd,
        };
        const tiles = [
            {
                key: 'temperature', label: text.temperature, value: climate.temperature, unit: '°C', digits: 1,
                min: bounds.temp_min, max: bounds.temp_max, scale: [15, 35], entity: room.temperature,
            },
            {
                key: 'humidity', label: text.humidity, value: climate.humidity, unit: '%', digits: 0,
                min: bounds.rh_min, max: bounds.rh_max, scale: [20, 90], entity: room.humidity,
            },
        ];
        if (Number.isFinite(climate.co2)) {
            tiles.push({
                key: 'co2', label: text.co2, value: climate.co2, unit: 'ppm', digits: 0,
                min: bounds.co2_min, max: bounds.co2_max, scale: [400, 1600], entity: room.co2,
            });
        }
        if (Number.isFinite(climate.dew)) {
            tiles.push({
                key: 'dew', label: text.dewPointShort, value: climate.dew, unit: '°C', digits: 1,
                entity: room.dew_point,
                // Condensation shows up first on the coldest surface, which the
                // air temperature stands in for; keep a couple of degrees of air.
                max: Number.isFinite(climate.temperature) ? climate.temperature - 2 : undefined,
                scale: [0, 30],
                note: Number.isFinite(climate.temperature)
                    ? `${text.margin} ${this.#number(climate.temperature - climate.dew, 1)} °C`
                    : '',
            });
        }

        // O VPD fecha a lista: assim a faixa dele encosta no gráfico, que é
        // justamente o que o gráfico desenha.
        tiles.push(vpd);

        const container = this.#node.tiles;
        // O banner do VPD atravessa a fileira; as colunas contam só as demais.
        const columns = Math.max(1, tiles.filter(tile => tile.key !== 'vpd').length);
        container.style.setProperty('--tile-columns', String(columns));
        const print = tiles.map(tile => tile.key).join('|');
        if (container.dataset.print !== print) {
            container.dataset.print = print;
            container.replaceChildren();
            for (const tile of tiles) {
                const node = document.createElement('div');
                node.className = tile.key === 'vpd' ? 'tile banner' : 'tile';
                node.dataset.key = tile.key;
                node.innerHTML = `<div class="label"></div>
                    <div class="value"><span class="number"></span><span class="unit"></span></div>
                    <div class="track"><div class="zone"></div><div class="pin"></div></div>
                    <div class="window"></div>`;
                // Tapping a tile charts that reading below, and tapping it again
                // hands the chart back to the VPD.
                node.addEventListener('click', () => {
                    if (node.dataset.entity) this.#openHistory(tile.key);
                });
                node.addEventListener('keydown', event => {
                    if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        node.click();
                    }
                });
                container.appendChild(node);
            }
        }

        for (const tile of tiles) {
            const node = container.querySelector(`[data-key="${tile.key}"]`);
            const openable = Boolean(tile.entity);
            node.dataset.entity = tile.entity || '';
            node.classList.toggle('pick', openable);
            node.tabIndex = openable ? 0 : -1;
            node.setAttribute('role', openable ? 'button' : 'presentation');
            // O more-info do HA nao aceita a faixa-alvo desenhada, entao ela
            // fica ao alcance do mouse aqui, junto do convite para abrir.
            const janela = node.querySelector('.window').textContent;
            node.title = openable
                ? [this.#text.openHistory, janela].filter(Boolean).join(' · ')
                : '';
            const [floor, ceiling] = tile.scale;
            const at = value => Math.max(0, Math.min(100, ((value - floor) / (ceiling - floor)) * 100));
            const bounded = Number.isFinite(tile.min) || Number.isFinite(tile.max);
            const low = Number.isFinite(tile.min) ? tile.min : floor;
            const high = Number.isFinite(tile.max) ? tile.max : ceiling;
            const has = Number.isFinite(tile.value);
            const drift = has && bounded && (tile.value < low || tile.value > high);

            node.classList.toggle('drift', drift);
            node.querySelector('.label').textContent = tile.label;
            node.querySelector('.number').textContent = this.#number(tile.value, tile.digits);
            node.querySelector('.unit').textContent = tile.unit;

            const zone = node.querySelector('.zone');
            zone.hidden = !bounded;
            zone.style.left = `${at(low)}%`;
            zone.style.width = `${Math.max(0, at(high) - at(low))}%`;
            const pin = node.querySelector('.pin');
            pin.hidden = !has;
            pin.style.left = `${has ? at(tile.value) : 0}%`;

            const window = node.querySelector('.window');
            if (tile.note) {
                window.textContent = tile.note;
            } else if (!bounded) {
                window.textContent = '';
            } else if (!Number.isFinite(tile.min)) {
                window.textContent = `${this.#text.target} ≤ ${this.#number(high, tile.digits)}`;
            } else {
                window.textContent = `${this.#text.target} ${this.#number(low, tile.digits)} – ${this.#number(high, tile.digits)}`;
            }
        }
    }

    #roomFans(room) {
        if (Array.isArray(room.fans) && room.fans.length) return room.fans;
        const stored = this.#state(room.status)?.attributes?.fans;
        if (!Array.isArray(stored)) return [];
        return stored
            .filter(item => item && item.entity_id)
            .map(item => ({
                entity: item.entity_id,
                name: item.name || '',
                power: item.power || '',
                cycle: item.cycle || {},
            }));
    }

    #renderFans(room) {
        const fans = this.#roomFans(room);
        this.#node.fans.hidden = !fans.length;
        if (!fans.length) return;

        this.#node.fansTitle.textContent = this.#text.fans;
        const grid = this.#node.fanGrid;
        const print = fans.map(fan => fan.entity).join('|');
        if (grid.dataset.print !== print) {
            grid.dataset.print = print;
            grid.replaceChildren(...fans.map(fan => this.#buildFan(fan)));
        }
        const attributes = this.#state(room.status)?.attributes || {};
        const cycles = attributes.cycles || {};
        const paused = attributes.timers_enabled === false;
        for (const fan of fans) {
            const cycle = cycles[fan.entity];
            const countdown = !cycle ? '' : paused ? this.#text.paused : this.#countdown(cycle);
            this.#updateFan(grid.querySelector(`[data-entity="${fan.entity}"]`), {...fan, countdown});
        }
    }

    /* One tile per fan, two per row: icon, name and state on the left, and the
       speed as a chip on the right that steps through 25 / 50 / 75 / 100. */
    /* Não basta dizer quanto falta: tem que dizer o que vai acontecer. Um
       "9 min" sozinho não diz se o ventilador vai ligar ou desligar. */
    #countdown(cycle) {
        if (!cycle.next) return '';
        const left = Math.max(0, Math.round((new Date(cycle.next).getTime() - Date.now()) / 60000));
        const label = cycle.running ? this.#text.turnsOffIn : this.#text.turnsOnIn;
        return `${label} ${left} min`;
    }

    #buildFan(fan) {
        const tile = document.createElement('div');
        tile.className = 'fan';
        tile.dataset.entity = fan.entity;
        tile.innerHTML = `
            <button type="button" class="fan-main">
                <ha-icon class="blade" icon="mdi:fan"></ha-icon>
                <span class="fan-copy"><strong></strong><small></small></span>
            </button>
            <button type="button" class="speed-pill"><ha-icon icon="mdi:speedometer"></ha-icon><span class="speed"></span></button>
            <button type="button" class="power-pill" hidden><ha-icon icon="mdi:flash"></ha-icon><span class="watts"></span></button>`;

        tile.querySelector('.fan-main').addEventListener('click', () => {
            this.#hass.callService(fan.entity.split('.')[0], 'toggle', {entity_id: fan.entity});
        });
        // Clicar na potencia joga o consumo desse ventilador no grafico do card,
        // que e o mesmo que a janela de historico do Light Scheduler faz.
        tile.querySelector('.power-pill').addEventListener('click', () => {
            const power = this.#roomFans(this.#resolve(this.#config.rooms[this.#room] || {}))
                .find(item => item.entity === fan.entity)?.power;
            if (power) this.#moreInfo(power);
        });
        tile.querySelector('.speed-pill').addEventListener('click', () => {
            const percentage = Number.parseFloat(this.#state(fan.entity)?.attributes?.percentage);
            if (!Number.isFinite(percentage)) return;
            const current = Math.round(percentage / 25) * 25;
            const next = SPEED_STEPS[(SPEED_STEPS.indexOf(current) + 1) % SPEED_STEPS.length] ?? SPEED_STEPS[0];
            this.#hass.callService('fan', 'set_percentage', {entity_id: fan.entity, percentage: next});
        });
        return tile;
    }

    #powerLabel(fan) {
        const name = fan.name || this.#state(fan.entity)?.attributes?.friendly_name || fan.entity;
        return `${this.#text.power} · ${name}`;
    }

    #updateFan(tile, fan) {
        if (!tile) return;
        const text = this.#text;
        const state = this.#state(fan.entity);
        const gone = !state || ['unavailable', 'unknown'].includes(state.state);
        const on = state?.state === 'on';
        const percentage = Number.parseFloat(state?.attributes?.percentage);
        const adjustable = fan.entity.startsWith('fan.') && Number.isFinite(percentage);
        const name = fan.name || state?.attributes?.friendly_name || fan.entity;

        tile.classList.toggle('gone', gone);
        tile.classList.toggle('on', on && !gone);
        const main = tile.querySelector('.fan-main');
        main.disabled = gone;
        main.setAttribute('aria-pressed', String(on));
        main.setAttribute('aria-label', name);
        const copy = tile.querySelector('.fan-copy');
        copy.querySelector('strong').textContent = name;
        copy.querySelector('strong').title = name;
        const reading = gone ? text.unavailable : (on ? text.on : text.off);
        copy.querySelector('small').textContent = fan.countdown
            ? `${reading} · ${fan.countdown}`
            : reading;

        const pill = tile.querySelector('.speed-pill');
        pill.querySelector('.speed').textContent = adjustable && on ? `${Math.round(percentage)}%` : '—';
        pill.disabled = gone || !adjustable;
        pill.hidden = !adjustable && Boolean(fan.power);

        const watts = tile.querySelector('.power-pill');
        watts.hidden = !fan.power;
        if (fan.power) {
            const reading = Number.parseFloat(this.#state(fan.power)?.state);
            const unit = this.#state(fan.power)?.attributes?.unit_of_measurement || 'W';
            watts.querySelector('.watts').textContent = Number.isFinite(reading)
                ? `${this.#number(reading, unit === 'kW' ? 2 : 1)} ${unit}`
                : '—';
            watts.title = this.#powerLabel(fan);
        }
        pill.title = adjustable ? `${text.on} 25 / 50 / 75 / 100%` : '';
    }

    /* Abre o dialogo de historico do proprio Home Assistant. */
    #moreInfo(entityId) {
        this.dispatchEvent(new CustomEvent('hass-more-info', {
            detail: {entityId},
            bubbles: true,
            composed: true,
        }));
    }

    #cardChart() {
        return {
            svg: this.#node.chart,
            tip: this.#node.tip,
            empty: this.#node.empty,
            wrap: this.#node.chartWrap,
            height: 360,
            // Sem mostrador dentro do gráfico: o VPD tem o box dele na fileira.
            headroom: 14,
        };
    }

    #dialogChart() {
        return {
            svg: this.#node.historyChart,
            tip: this.#node.historyTip,
            empty: this.#node.historyEmpty,
            wrap: this.#node.historyWrap,
            headroom: 16,
        };
    }

    /* A leitura de um tile, montada para o diálogo: unidade, casas e a janela
       da fase atual, que é justamente o que o histórico nativo não desenha. */
    #readingSpec(key, room, climate, bounds) {
        const text = this.#text;
        switch (key) {
            case 'vpd':
                return {key, entity: room.vpd, label: 'VPD', unit: 'kPa', digits: 2, isVpd: true,
                    value: climate.vpd, low: bounds.vpd_min, high: bounds.vpd_max,
                    leafDrop: this.#leafDrop(room)};
            case 'temperature':
                return {key, entity: room.temperature, label: text.temperature, unit: '\u00b0C', digits: 1,
                    value: climate.temperature, low: bounds.temp_min, high: bounds.temp_max};
            case 'humidity':
                return {key, entity: room.humidity, label: text.humidity, unit: '%', digits: 0,
                    value: climate.humidity, low: bounds.rh_min, high: bounds.rh_max};
            case 'co2':
                return {key, entity: room.co2, label: text.co2, unit: 'ppm', digits: 0,
                    value: climate.co2, low: bounds.co2_min, high: bounds.co2_max};
            default:
                return {key: 'dew', entity: room.dew_point, label: text.dewPoint, unit: '\u00b0C', digits: 1,
                    value: climate.dew, leafDrop: this.#leafDrop(room),
                    high: Number.isFinite(climate.temperature) ? climate.temperature - 2 : undefined};
        }
    }

    async #openHistory(key) {
        const room = this.#resolve(this.#config.rooms[this.#room] || {});
        const spec = this.#readingSpec(key, room, this.#climate(room), this.#bounds(room));
        if (!spec.entity) return;
        this.#historySpec = spec;
        this.#node.historyTitle.textContent = spec.label;
        this.#node.history.showModal();
        await this.#drawHistory();
    }

    async #drawHistory() {
        const spec = this.#historySpec;
        if (!spec) return;
        const room = this.#resolve(this.#config.rooms[this.#room] || {});
        const hours = this.#historyHours;
        for (const chip of this.#node.historyRange.children) {
            chip.classList.toggle('on', Number(chip.dataset.hours) === hours);
        }
        this.#node.historyEmpty.hidden = true;
        this.#node.historyChart.replaceChildren();
        const token = ++this.#request;
        let series = [];
        try {
            series = await this.#fetchSeries(room, spec, hours);
        } catch (error) {
            console.warn('weather-schedule-card: history unavailable', error);
        }
        if (token !== this.#request) return;
        this.#paint(this.#dialogChart(), spec, series, hours);
    }

    #leafDrop(room) {
        const settings = this.#state(room.status)?.attributes?.settings;
        const stored = Number.parseFloat(settings?.leaf_drop);
        return Number.isFinite(stored) ? stored : Number.parseFloat(room.leaf_drop);
    }

    /* O card desenha uma coisa so: o VPD, com as bandas de fase e a janela
       da fase atual. As outras leituras abrem o historico do proprio Home
       Assistant, que ja sabe fazer isso melhor do que eu faria aqui. */
    #vpdSpec(room, climate, bounds) {
        return {
            key: 'vpd', entity: room.vpd, label: 'VPD', unit: 'kPa', digits: 2, isVpd: true,
            value: climate.vpd, low: bounds.vpd_min, high: bounds.vpd_max,
            leafDrop: this.#leafDrop(room),
        };
    }

    async #loadSeries(room, climate, bounds) {
        const hours = Number(this.#config.hours) > 0 ? Number(this.#config.hours) : 24;
        const spec = this.#vpdSpec(room, climate, bounds);

        const computable = room.temperature && room.humidity;
        const key = JSON.stringify([this.#room, spec.entity, room.temperature, room.humidity, hours]);
        const fresh = key === this.#seriesKey && Date.now() - this.#seriesAt < HISTORY_MAX_AGE;

        if (!fresh && this.#hass.callWS && (spec.entity || computable)) {
            this.#seriesKey = key;
            this.#seriesAt = Date.now();
            // Trocar de sala durante o await deixaria a resposta antiga pintar
            // o gráfico da sala nova.
            const token = ++this.#request;
            let series = [];
            try {
                series = await this.#fetchSeries(room, spec, hours);
            } catch (error) {
                console.warn('weather-schedule-card: history unavailable', error);
            }
            if (token !== this.#request) return;
            this.#series = series;
        }
        this.#paint(this.#cardChart(), spec, this.#series, hours);
    }

    async #fetchSeries(room, spec, hours) {
        const end = new Date();
        const start = new Date(end.getTime() - hours * 3600000);
        const ask = async entityId => {
            const answer = await this.#hass.callWS({
                type: 'history/history_during_period',
                start_time: start.toISOString(),
                end_time: end.toISOString(),
                entity_ids: [entityId],
                minimal_response: true,
                no_attributes: true,
                significant_changes_only: true,
            });
            return (answer?.[entityId] || []).map(point => ({
                time: (point.lu ?? point.last_updated ?? 0) * 1000,
                value: Number.parseFloat(point.s ?? point.state),
            })).filter(point => Number.isFinite(point.time) && Number.isFinite(point.value));
        };

        const recorded = spec.entity ? await ask(spec.entity) : [];

        // A room set up today has no VPD or dew point before the integration
        // existed, while its thermometer has months of history. Anything the
        // entity cannot cover is rebuilt from the raw pair, so the chart starts
        // where the sensors start, not where the integration does.
        const derivable = (spec.isVpd || spec.key === 'dew') && room.temperature && room.humidity;
        const firstRecorded = recorded.length ? recorded[0].time : Infinity;
        if (!derivable || firstRecorded <= start.getTime() + 300000) return recorded;

        const [temperatures, humidities] = await Promise.all([ask(room.temperature), ask(room.humidity)]);
        if (!temperatures.length || !humidities.length) return recorded;
        // O histórico bruto vem na unidade do sensor: converter antes da conta.
        const unit = this.#state(room.temperature)?.attributes?.unit_of_measurement;
        const toCelsius = unit === '\u00b0F' ? value => (value - 32) * 5 / 9
            : unit === 'K' ? value => value - 273.15
            : value => value;

        const drop = Number.isFinite(Number(spec.leafDrop)) ? Number(spec.leafDrop)
            : Number.isFinite(Number(room.leaf_drop)) ? Number(room.leaf_drop) : 2;
        let cursor = 0;
        const rebuilt = [];
        for (const point of temperatures) {
            if (point.time >= firstRecorded) break;
            while (cursor + 1 < humidities.length && humidities[cursor + 1].time <= point.time) cursor++;
            const humidity = humidities[cursor].value;
            const air = toCelsius(point.value);
            rebuilt.push({
                time: point.time,
                value: spec.isVpd
                    ? vapourPressureDeficit(air - drop, air, humidity)
                    : dewPoint(air, humidity),
                rebuilt: true,
            });
        }
        return [...rebuilt, ...recorded];
    }

    /* O número de amostras devolvidas cresce junto com o histórico gravado no
       recorder; sem um teto, a linha vira um SVG com dezenas de milhares de
       pontos e o navegador leva segundos para desenhá-lo. Mantém um número
       fixo de amostras espaçadas de forma uniforme, preservando a forma. */
    #downsample(points, limit) {
        if (points.length <= limit) return points;
        const kept = new Array(limit);
        const step = (points.length - 1) / (limit - 1);
        for (let i = 0; i < limit; i++) kept[i] = points[Math.round(i * step)];
        kept[limit - 1] = points[points.length - 1];
        return kept;
    }

    /* O mesmo motor desenha o gráfico do card e o do diálogo. O alvo diz onde
       pintar; o resto — bandas, faixa, pontos por hora, hover — é igual nos dois. */
    #paint(target, spec, series, hours) {
        const svg = target.svg;
        const now = Date.now();
        const start = now - hours * 3600000;
        let points = (series || []).filter(point => point.time >= start).sort((a, b) => a.time - b.time);
        points = this.#downsample(points, CHART_MAX_POINTS);
        if (Number.isFinite(spec.value)) points.push({time: now, value: spec.value});

        svg.replaceChildren();
        target.empty.hidden = points.length > 0;
        target.empty.textContent = this.#text.noHistory;
        svg.hidden = points.length === 0;
        if (!points.length) return;

        const width = 720;
        const height = target.height ?? 300;
        const pad = {left: 8, right: 8, top: target.headroom ?? 16, bottom: 34};
        const plotWidth = width - pad.left - pad.right;
        const plotHeight = height - pad.top - pad.bottom;
        const values = points.map(point => point.value);
        const make = (tag, attributes) => {
            const node = document.createElementNS(SVG_NS, tag);
            for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
            return node;
        };
        const x = time => pad.left + ((time - start) / (now - start)) * plotWidth;

        let floor = 0;
        let ceiling = Math.max(2, Math.ceil((Math.max(...values) + 0.2) * 5) / 5);
        if (spec.isVpd && this.#config.scale !== 'full') {
            // Uma sala estável mora numa faixa estreita: mostrada em 0–2 kPa
            // ela vira uma linha reta. O eixo então fecha em volta do que a
            // sala fez, sempre com a janela-alvo dentro do quadro, para o zoom
            // não esconder justamente a referência.
            const seen = [...values, spec.low, spec.high].filter(Number.isFinite);
            const lowest = Math.min(...seen);
            const highest = Math.max(...seen);
            const air = Math.max((highest - lowest) * 0.25, 0.08);
            const near = Math.max(0, Math.floor((lowest - air) * 10) / 10);
            const far = Math.min(ceiling, Math.ceil((highest + air) * 10) / 10);
            // Abaixo de meio kPa de amplitude o desenho vira ruído ampliado;
            // acima de 9/10 da escala não sobra o que ampliar.
            if (far - near >= 0.4 && far - near < (ceiling - floor) * 0.9) {
                floor = near;
                ceiling = far;
            }
        }
        const zoomed = spec.isVpd && floor > 0;
        if (!spec.isVpd) {
            const candidates = [...values, spec.low, spec.high].filter(Number.isFinite);
            const low = Math.min(...candidates);
            const high = Math.max(...candidates);
            const air = Math.max((high - low) * 0.15, spec.digits ? 0.5 : 5);
            floor = low - air;
            ceiling = high + air;
        }
        const y = value => pad.top + plotHeight
            - ((Math.min(Math.max(value, floor), ceiling) - floor) / (ceiling - floor)) * plotHeight;

        if (spec.isVpd) {
            for (const band of VPD_BANDS) {
                const top = y(Math.min(band.to, ceiling));
                const bottom = y(Math.min(band.from, ceiling));
                if (bottom - top <= 0) continue;
                svg.appendChild(make('rect', {
                    x: 0, y: top, width, height: bottom - top, fill: band.color, opacity: 0.24,
                }));
                if (bottom - top >= 22) {
                    const label = make('text', {x: pad.left + 8, y: top + 16, class: 'band-label'});
                    label.textContent = this.#text.band[band.key];
                    svg.appendChild(label);
                }
            }
        } else if (Number.isFinite(spec.low) || Number.isFinite(spec.high)) {
            const top = y(Number.isFinite(spec.high) ? spec.high : ceiling);
            const bottom = y(Number.isFinite(spec.low) ? spec.low : floor);
            svg.appendChild(make('rect', {
                x: 0, y: top, width, height: Math.max(0, bottom - top), class: 'target-band',
            }));
            for (const edge of [spec.low, spec.high]) {
                if (!Number.isFinite(edge)) continue;
                svg.appendChild(make('line', {
                    x1: pad.left, y1: y(edge), x2: width - pad.right, y2: y(edge), class: 'target-edge',
                }));
            }
        }

        for (let index = 0; index <= 5; index++) {
            const value = floor + (ceiling - floor) * index / 5;
            svg.appendChild(make('line', {
                x1: pad.left, y1: y(value), x2: width - pad.right, y2: y(value), class: 'grid',
            }));
            if ((spec.isVpd && !zoomed) || index === 0 || index === 5) continue;
            // No gráfico de VPD a esquerda é dos rótulos das bandas; a escala
            // vai para a direita para as duas não se atropelarem.
            const label = make('text', zoomed
                ? {x: width - pad.right - 6, y: y(value) - 4, class: 'axis-value', 'text-anchor': 'end'}
                : {x: pad.left + 6, y: y(value) - 4, class: 'axis-value'});
            label.textContent = `${this.#number(value, spec.digits)} ${spec.unit}`;
            svg.appendChild(label);
        }

        if (spec.isVpd) {
            for (const edge of [spec.low, spec.high]) {
                if (!Number.isFinite(edge) || edge > ceiling || edge < floor) continue;
                svg.appendChild(make('line', {
                    x1: pad.left, y1: y(edge), x2: width - pad.right, y2: y(edge), class: 'edge',
                }));
            }
        }

        // Janelas de mais de um dia precisam do dia na marca, senão 08:00 de
        // terça e 08:00 de quinta viram a mesma coisa.
        const clock = new Intl.DateTimeFormat(this.#locale(), hours > 24
            ? {day: '2-digit', month: '2-digit', hour: '2-digit'}
            : {hour: '2-digit', minute: '2-digit'});
        for (let index = 0; index <= 4; index++) {
            const time = start + (now - start) * index / 4;
            svg.appendChild(make('line', {
                x1: x(time), y1: pad.top, x2: x(time), y2: pad.top + plotHeight, class: 'grid',
            }));
            const label = make('text', {
                x: x(time), y: height - 12, class: 'tick',
                'text-anchor': index === 0 ? 'start' : index === 4 ? 'end' : 'middle',
            });
            label.textContent = clock.format(new Date(time));
            svg.appendChild(label);
        }

        svg.appendChild(make('path', {
            d: points.map((point, index) => `${index ? 'L' : 'M'} ${x(point.time).toFixed(1)} ${y(point.value).toFixed(1)}`).join(' '),
            class: 'trend',
        }));

        this.#plots.set(svg, {points, spec, start, now, pad, plotWidth, x, y, clock, target, height});

        // Um ponto por hora nas janelas curtas; janelas longas rareiam a marca
        // para o gráfico não virar um colar de bolinhas.
        const stepHours = hours <= 24 ? 1 : hours <= 72 ? 6 : 12;
        const stepMs = stepHours * 3600000;
        const tolerance = stepMs / 2;
        const taken = new Set();
        for (let mark = Math.ceil(start / stepMs) * stepMs; mark <= now; mark += stepMs) {
            let sample = null;
            let closest = Infinity;
            for (const point of points) {
                const gap = Math.abs(point.time - mark);
                if (gap < closest) {
                    closest = gap;
                    sample = point;
                }
            }
            if (!sample || closest > tolerance || taken.has(sample.time)) continue;
            taken.add(sample.time);
            const around = points.filter(point => Math.abs(point.time - mark) <= tolerance);
            const readings = around.map(point => point.value);
            this.#addSpot(svg, spec, {
                x: x(sample.time), y: y(sample.value), at: mark, value: sample.value,
                low: readings.length > 1 ? Math.min(...readings) : null,
                high: readings.length > 1 ? Math.max(...readings) : null,
                clock,
            });
        }

        const head = points.at(-1);
        svg.appendChild(make('circle', {cx: x(head.time), cy: y(head.value), r: 5, class: 'head'}));
        if (!target.noHeadLabel) {
            const label = make('text', {
                x: x(head.time) - 9, y: y(head.value) - 11, 'text-anchor': 'end', class: 'head-label',
            });
            label.textContent = `${this.#number(head.value, spec.digits)} ${spec.unit}`;
            svg.appendChild(label);
        }
        this.#addSpot(svg, spec, {
            x: x(head.time), y: y(head.value), at: head.time, value: head.value,
            low: null, high: null, clock, now: true,
        }, false);

        this.#addHoverTracker(svg, make, pad, plotWidth, plotHeight, width);
    }

    /* Toda a área do gráfico responde ao mouse: onde ele estiver, mostra a
       leitura daquela coluna, com guia e ponto na amostra mais próxima. */
    #addHoverTracker(svg, make, pad, plotWidth, plotHeight, width) {
        const guide = make('line', {
            x1: 0, y1: pad.top, x2: 0, y2: pad.top + plotHeight, class: 'cursor-line', opacity: 0,
        });
        const dot = make('circle', {cx: 0, cy: 0, r: 4, class: 'cursor-dot', opacity: 0});
        const catcher = make('rect', {
            x: pad.left, y: pad.top, width: plotWidth, height: plotHeight, class: 'hover-catch',
        });
        svg.append(guide, dot, catcher);

        const follow = event => {
            const plot = this.#plots.get(svg);
            if (!plot || !plot.points.length) return;
            const box = svg.getBoundingClientRect();
            const chartX = ((event.clientX - box.left) / box.width) * width;
            const time = plot.start + ((chartX - pad.left) / plotWidth) * (plot.now - plot.start);
            let point = null;
            let closest = Infinity;
            for (const candidate of plot.points) {
                const gap = Math.abs(candidate.time - time);
                if (gap < closest) {
                    closest = gap;
                    point = candidate;
                }
            }
            if (!point) return;
            const pointX = plot.x(point.time);
            const pointY = plot.y(point.value);
            guide.setAttribute('x1', pointX);
            guide.setAttribute('x2', pointX);
            guide.setAttribute('opacity', 1);
            dot.setAttribute('cx', pointX);
            dot.setAttribute('cy', pointY);
            dot.setAttribute('opacity', 1);
            this.#showTip(plot.target, this.#spotLines(plot.spec, {
                at: point.time, value: point.value, clock: plot.clock, low: null, high: null,
            }), pointX, pointY);
        };

        const leave = () => {
            guide.setAttribute('opacity', 0);
            dot.setAttribute('opacity', 0);
            this.#hideTip(this.#plots.get(svg)?.target);
        };

        catcher.addEventListener('pointermove', follow);
        catcher.addEventListener('pointerdown', follow);
        catcher.addEventListener('pointerleave', leave);
    }

    /* Desenha um ponto e a área invisível que carrega o tooltip. */
    #addSpot(svg, spec, spot, visible = true) {
        const make = (tag, attributes) => {
            const node = document.createElementNS(SVG_NS, tag);
            for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, value);
            return node;
        };
        if (visible) {
            svg.appendChild(make('circle', {cx: spot.x, cy: spot.y, r: 3, class: 'spot'}));
        }
        const lines = this.#spotLines(spec, spot);
        const hit = make('circle', {
            cx: spot.x, cy: spot.y, r: 13, class: 'spot-hit',
            tabindex: '0', role: 'button', 'aria-label': lines.join(' · '),
        });
        const show = event => {
            event.stopPropagation();
            this.#showTip(this.#plots.get(svg)?.target, lines, spot.x, spot.y);
        };
        hit.addEventListener('pointerenter', show);
        hit.addEventListener('click', show);
        hit.addEventListener('focus', show);
        hit.addEventListener('pointerleave', () => this.#hideTip(this.#plots.get(svg)?.target));
        hit.addEventListener('blur', () => this.#hideTip(this.#plots.get(svg)?.target));
        svg.appendChild(hit);
    }

    #spotLines(spec, spot) {
        const text = this.#text;
        const when = spot.now ? text.now : spot.clock.format(new Date(spot.at));
        const lines = [`${when} · ${this.#number(spot.value, spec.digits)} ${spec.unit}`];

        if (Number.isFinite(spot.low) && Number.isFinite(spot.high)) {
            const low = this.#number(spot.low, spec.digits);
            const high = this.#number(spot.high, spec.digits);
            if (low !== high) lines.push(`${text.lowest} ${low} · ${text.highest} ${high}`);
        }

        if (spec.isVpd) {
            const band = VPD_BANDS.find(item => spot.value >= item.from && spot.value < item.to);
            if (band) lines.push(text.band[band.key]);
        }

        const under = Number.isFinite(spec.low) && spot.value < spec.low;
        const over = Number.isFinite(spec.high) && spot.value > spec.high;
        if (Number.isFinite(spec.low) || Number.isFinite(spec.high)) {
            lines.push(under ? text.belowTarget : over ? text.aboveTarget : text.insideTarget);
        }
        return lines;
    }

    #showTip(target, lines, chartX, chartY) {
        if (!target) return;
        const tip = target.tip;
        const svg = target.svg;
        const wrap = target.wrap;
        tip.replaceChildren(...lines.map((line, index) => {
            const node = document.createElement(index ? 'span' : 'strong');
            node.textContent = line;
            return node;
        }));

        const svgBox = svg.getBoundingClientRect();
        const wrapBox = wrap.getBoundingClientRect();
        // A altura do viewBox varia por alvo; fixar 300 jogava o tooltip para
        // longe do ponto no gráfico do card, que tem 360.
        const height = this.#plots.get(svg)?.height || 300;
        const left = svgBox.left - wrapBox.left + (chartX / 720) * svgBox.width;
        const top = svgBox.top - wrapBox.top + (chartY / height) * svgBox.height;

        tip.style.visibility = 'hidden';
        tip.classList.add('show');
        const tipBox = tip.getBoundingClientRect();
        const half = Math.min(tipBox.width || 160, wrapBox.width - 12) / 2;
        tip.style.left = `${Math.min(Math.max(left, half + 6), wrapBox.width - half - 6)}px`;
        tip.style.top = `${top}px`;
        tip.classList.toggle('below', top - (tipBox.height || 60) - 12 < 6);
        tip.style.visibility = 'visible';
    }

    #hideTip(target) {
        if (!target) return;
        target.tip.classList.remove('show', 'below');
        target.tip.style.visibility = '';
    }

}

if (!customElements.get('weather-schedule-card')) {
    customElements.define('weather-schedule-card', WeatherScheduleCard);
}

window.customCards = window.customCards || [];
if (!window.customCards.some(card => card.type === 'weather-schedule-card')) {
    window.customCards.push({
        type: 'weather-schedule-card',
        name: 'Weather Schedule',
        description: 'VPD, temperature, humidity, CO₂ and fans for one room',
        preview: false,
        documentationURL: 'https://github.com/chadalau/weather-schedule',
    });
}

console.info(`%c WEATHER-SCHEDULE-CARD %c v${VERSION} `, 'color:#0d1413;background:#22ab9c;font-weight:600', 'color:#22ab9c;background:#0d1413');
