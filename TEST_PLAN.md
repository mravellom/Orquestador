# Plan de Tests del Orquestador

## Resumen

- **Total tests planificados: 89**
- **Archivos de test: 8**
- **Cobertura objetivo: >85%**
- **Framework: pytest + pytest-asyncio + pytest-mock**

---

## 1. Tests de Reglas (test_rules.py) — 26 tests

Funciones puras, sin mocks. Cada regla se testea en sus boundaries.

```
test_health_dead_fires_at_24h              → unhealthy_hours=24, fired=True, KILL
test_health_dead_no_fire_at_23h            → unhealthy_hours=23, fired=False
test_health_dead_fires_above_24h           → unhealthy_hours=48, fired=True

test_budget_exceeded_fires_at_151pct       → spend=151, budget=100, fired=True, PAUSE
test_budget_exceeded_no_fire_at_150pct     → spend=150, budget=100, fired=False
test_budget_exceeded_no_fire_zero_budget   → budget=0, fired=False

test_stagnant_fires_at_2x_window           → unchanged=1440, window=720, fired=True, PIVOT
test_stagnant_no_fire_below_threshold      → unchanged=1439, window=720, fired=False

test_roi_negative_fires_below_minus20      → roi=-21, fired=True, KILL
test_roi_negative_no_fire_at_minus20       → roi=-20, fired=False (boundary: < not <=)
test_roi_negative_no_fire_when_none        → roi=None, fired=False
test_roi_negative_requires_human_real_money→ roi=-25, handles_real_money=True, requires_human=True
test_roi_negative_no_human_paper           → roi=-25, handles_real_money=False, requires_human=False

test_roi_positive_fires_both_positive      → roi=10, trend=0.5, fired=True, SCALE
test_roi_positive_no_fire_trend_zero       → roi=10, trend=0, fired=False
test_roi_positive_no_fire_roi_zero         → roi=0, trend=0.5, fired=False
test_roi_positive_confidence_capped_at_95  → roi=50, trend=1, confidence=95

test_drawdown_fires_above_15               → drawdown=15.1, fired=True, PAUSE
test_drawdown_no_fire_at_15                → drawdown=15, fired=False

test_winrate_declining_fires_below_minus10 → delta=-11, fired=True, PAUSE
test_winrate_declining_no_fire_at_minus10  → delta=-10, fired=False

test_circuit_breaker_fires_when_active     → active=True, fired=True, PAUSE
test_circuit_breaker_no_fire_when_inactive → active=False, fired=False

test_daily_loss_fires_negative_pnl_and_roi → pnl=-100, roi=-6, fired=True, PAUSE
test_daily_loss_no_fire_pnl_neg_roi_ok     → pnl=-100, roi=-4, fired=False

test_libro_revenue_fires_above_5_per_book  → revenue=60, items=10, fired=True, SCALE
test_libro_revenue_no_fire_zero_items      → items=0, fired=False
test_libro_revenue_no_fire_at_5_per_book   → revenue=50, items=10, fired=False

test_libro_compliance_fires_high           → risk="HIGH", fired=True, PAUSE
test_libro_compliance_no_fire_medium       → risk="MEDIUM", fired=False

test_casas_fp_fires_above_40              → fp=41, fired=True, PIVOT
test_casas_fp_no_fire_at_40               → fp=40, fired=False

test_casas_no_users_fires_zero_healthy    → users=0, unhealthy=0, fired=True, KILL
test_casas_no_users_no_fire_zero_unhealthy→ users=0, unhealthy=1, fired=False
test_casas_no_users_no_fire_has_users     → users=5, fired=False
```

---

## 2. Tests de Scoring (test_scoring.py) — 16 tests

Funciones puras, sin mocks.

### calculate_portfolio_score
```
test_all_none_returns_baseline             → todos None, score ~47.5 (baselines)
test_perfect_health_adds_15_points         → healthy=True vs False, diff = 15
test_roi_20_gives_max_financial            → roi=20, financial=100
test_roi_0_gives_mid_financial             → roi=0, financial=50
test_roi_minus20_gives_zero_financial      → roi=-20, financial=0
test_revenue_positive_adds_bonus           → revenue=100, financial_score aumenta
test_drawdown_20_gives_zero_risk           → drawdown=20, risk=0
test_drawdown_0_gives_max_risk             → drawdown=0, risk=100
test_focus_2h_no_penalty                   → focus=2, penalty=0
test_focus_5h_penalizes_9_points           → focus=5, penalty=(5-2)*3=9
test_focus_0_no_penalty                    → focus=0, penalty=0
test_score_clamped_to_0_100                → inputs extremos, resultado entre 0 y 100
```

### evaluate_signal_with_hysteresis
```
test_empty_history_high_score_returns_scale    → history=[], score=80, signal="SCALE"
test_empty_history_low_score_returns_kill      → history=[], score=20, signal="KILL"
test_empty_history_mid_score_returns_hold      → history=[], score=50, signal="HOLD"
test_scale_requires_two_cycles_above_75        → history=[80,82], signal="SCALE"
test_no_scale_single_spike                     → history=[60,80], signal!="SCALE"
test_kill_requires_three_cycles_below_25       → history=[20,22,18], signal="KILL"
test_no_kill_only_two_cycles_low               → history=[20,22], signal!="KILL"
test_dead_zone_70_75_keeps_previous_signal     → score=72, history=[72,73], current="HOLD", returns "HOLD"
test_dead_zone_25_30_keeps_previous_signal     → score=27, current="HOLD", returns "HOLD"
test_clear_hold_zone                           → score=50, returns "HOLD"
test_boundary_75_is_dead_zone                  → score=75, keeps previous
test_boundary_30_is_hold_zone                  → score=30, returns "HOLD"
```

---

## 3. Tests del Conector Base (test_base_connector.py) — 10 tests

Requiere mock de httpx.

```
test_headers_with_api_key                  → api_key="abc", headers tiene X-API-Key
test_headers_without_api_key               → api_key=None, headers sin X-API-Key
test_circuit_breaker_opens_after_5_failures → 5 fallos consecutivos, circuit se abre
test_circuit_breaker_resets_on_success      → fallo+exito, consecutive_failures=0
test_circuit_open_blocks_requests           → circuit abierto, _get() lanza ConnectError
test_circuit_closes_after_60_seconds       → circuit abierto, pasa 60s, se cierra
test_safe_get_success_returns_response     → mock 200, returns (response, elapsed_ms)
test_safe_get_failure_returns_none         → mock exception, returns (None, elapsed_ms)
test_safe_get_records_timing_on_failure    → exception, elapsed_ms > 0
test_retry_on_connect_error               → primer intento falla, segundo exito
```

---

## 4. Tests del Conector Acciones (test_acciones_connector.py) — 11 tests

Mock de _safe_get y httpx.

```
test_health_unreachable_returns_unhealthy  → _safe_get returns (None, 100)
test_health_non_200_returns_unhealthy      → status_code=500
test_health_200_healthy                    → status="healthy", checks ok
test_health_200_degraded                   → status="degraded", is_healthy=False
test_health_missing_checks_defaults_false  → no "checks" key, database_ok=False

test_metrics_all_endpoints_200             → 3 endpoints ok, all fields populated
test_metrics_portfolio_fails_others_ok     → portfolio None, others ok, pnl=None
test_metrics_all_fail_returns_empty        → all None, all fields None

test_action_halt_success                   → POST 200, success=True
test_action_check_positions_returns_count  → GET 200, open_positions=3
test_action_unknown_returns_error          → action="foo", success=False
```

---

## 5. Tests del Monitor (test_monitor.py) — 8 tests

Mock de async_session, connectors, publish.

```
test_healthy_check_persists_to_db          → health ok, HealthCheck creado con is_healthy=True
test_unhealthy_increments_failure_count    → health bad, failure_count[slug] = 1
test_three_failures_triggers_alert         → 3 ciclos bad, publish("alert") called
test_four_failures_no_duplicate_alert      → 4 ciclos bad, alert solo en el 3ro
test_recovery_after_failures_publishes     → 3 bad + 1 good, publish("recovery") called
test_no_recovery_if_never_failed           → healthy desde siempre, no recovery
test_no_connector_skips_project            → slug desconocido, skip sin error
test_no_active_projects_does_nothing       → 0 proyectos, no crash
```

---

## 6. Tests del Fiscal (test_fiscal.py) — 6 tests

Mock de async_session, connectors, publish.

```
test_should_collect_first_cycle            → _cycle_count=1, last=0, cadence=1 → True
test_should_collect_respects_cadence       → cadence=5min, cycles<5 → False
test_should_collect_unknown_slug           → slug no en registry → False
test_collect_success_persists_snapshot     → metrics ok, MetricSnapshot creado
test_collect_failure_logs_no_snapshot      → exception, no snapshot, no crash
test_collect_updates_last_collection       → after collect, _last_collection[slug] updated
```

---

## 7. Tests del Estratega (test_estratega.py) — 12 tests

Mock de async_session, _build_metrics, rules, publish.

```
test_first_cycle_runs_strategic            → _last_strategic_cycle=None, strategic rules run
test_tactical_rules_always_run             → run_strategic=False, tactical rules still evaluated
test_strategic_rules_skip_when_not_due     → last_strategic < 6h ago, strategic skipped
test_strategic_runs_after_6_hours          → last_strategic > 6h ago, strategic rules run
test_cooldown_prevents_duplicate_fire      → rule fired 1h ago, cooldown=24h → skipped
test_cooldown_expired_allows_fire          → rule fired 25h ago, cooldown=24h → evaluated
test_kill_real_money_requires_human        → handles_real_money=True, KILL → needs_human=True
test_kill_paper_no_human_if_setting_off    → handles_real_money=False, setting=False → needs_human=False
test_rule_applies_to_filters_correctly     → rule for ["acciones"], project="libro" → skipped
test_universal_rule_applies_to_all         → rule ["*"], any project → evaluated
test_multiple_rules_fire_creates_multiple  → 2 rules fire, 2 decisions created
test_decision_persisted_with_correct_data  → decision in DB with type, confidence, reasons, rule_triggers
```

---

## 8. Tests del Executor (test_executor.py) — 16 tests

Mock de DockerManager, AccionesConnector, TelegramNotifier, async_session.

### Auto-aprobacion
```
test_auto_approve_non_human_proposed       → requires_human=False, status → APPROVED → executed
test_auto_approve_respects_kill_cooldown   → KILL + elapsed < 300s → NOT executed
test_auto_approve_kill_after_cooldown      → KILL + elapsed > 300s → executed
test_no_auto_approve_human_required        → requires_human=True → stays PROPOSED
```

### Kill seguro (Acciones)
```
test_kill_acciones_halts_first             → halt called before anything else
test_kill_acciones_waits_for_positions     → polls check_positions, waits for 0
test_kill_acciones_success_full_flow       → halt → positions=0 → docker down → status=KILLED
test_kill_acciones_aborts_on_timeout       → 20 polls, positions>0 → returns False, EMERGENCY alert
test_kill_acciones_aborts_on_check_fail    → positions=-1 → returns False, EMERGENCY alert
test_kill_non_graceful_skips_to_docker     → requires_graceful=False → straight to compose_down
```

### Pause/Resume
```
test_pause_acciones_uses_api_halt          → slug="acciones" → POST halt, status=PAUSED
test_pause_other_uses_docker               → slug="libro" → docker pause, status=PAUSED
test_resume_acciones_uses_api              → slug="acciones" → POST resume, status=ACTIVE
test_resume_other_uses_docker_unpause      → slug="casas" → docker unpause, status=ACTIVE
```

### Scale/Pivot
```
test_scale_sends_telegram_returns_true     → always True, telegram called
test_pivot_sends_telegram_returns_true     → PIVOT decision → alert sent, success=True
```

---

## 9. Test de Integracion (test_integration.py) — 1 test

Mock completo de infraestructura, flujo real end-to-end.

```
test_full_scenario_acciones_crash:
    1. Setup: proyecto Acciones con roi=-25%, drawdown=18%
    2. Fiscal recolecta metricas → snapshot con roi=-25
    3. Estratega evalua → FIN_ROI_NEGATIVE dispara → Decision(KILL, PROPOSED, requires_human=True)
    4. Simular aprobacion via API → Decision(KILL, APPROVED)
    5. Executor detecta → _execute_kill:
       a. halt trading → OK
       b. check_positions → 2 open → wait → 0 open
       c. docker compose down → OK
       d. project.status = KILLED
    6. Reporter genera reporte → Acciones aparece como KILLED
    7. Verificar: Decision.status=EXECUTED, Project.status=KILLED, telegram alertado
```

---

## Estructura de archivos

```
tests/
├── conftest.py                    # Fixtures compartidos (mock_session, mock_project, etc.)
├── test_engine/
│   ├── test_rules.py              # 26 tests
│   └── test_scoring.py            # 16 tests
├── test_connectors/
│   ├── test_base_connector.py     # 10 tests
│   └── test_acciones_connector.py # 11 tests
├── test_agents/
│   ├── test_monitor.py            # 8 tests
│   ├── test_fiscal.py             # 6 tests
│   ├── test_estratega.py          # 12 tests
│   └── test_executor.py           # 16 tests
└── test_integration.py            # 1 test (end-to-end)
```

---

## Dependencias adicionales (agregar a requirements.txt)

```
pytest>=8.0.0
pytest-asyncio>=0.24.0
pytest-mock>=3.12.0
pytest-cov>=5.0.0
```

---

## Cobertura objetivo por modulo

| Modulo | Target | Justificacion |
|--------|--------|---------------|
| engine/rules.py | **100%** | Funciones puras, criticas para decisiones |
| engine/scoring.py | **100%** | Funciones puras, criticas para scoring |
| connectors/base.py | **90%** | Circuit breaker y retry son criticos |
| connectors/acciones.py | **85%** | Conector de dinero real |
| agents/monitor.py | **80%** | Alertas tempranas |
| agents/fiscal.py | **75%** | Alimenta al estratega |
| agents/estratega.py | **85%** | Cerebro del sistema |
| agents/executor.py | **90%** | Ejecuta acciones peligrosas |
| **TOTAL** | **>85%** | |

---

## Orden de implementacion

```
Dia 1: test_rules.py (26) + test_scoring.py (16) = 42 tests
Dia 2: test_base_connector.py (10) + test_acciones_connector.py (11) = 21 tests
Dia 3: test_monitor.py (8) + test_fiscal.py (6) + test_estratega.py (12) = 26 tests
Dia 4: test_executor.py (16) + test_integration.py (1) = 17 tests → TOTAL: 106 tests
```

Nota: el conteo final (106) incluye variantes de tests que se expanden durante implementacion.

---

## Regla de oro

```bash
pytest --cov=app --cov-report=term-missing && coverage > 85%
```

**Si falla → NO DEPLOY**
