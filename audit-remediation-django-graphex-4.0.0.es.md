# Remediación de la auditoría de Django GraphEx 4.0.0: evidencias y decisiones detalladas

Este complemento del [informe original](auditoria-django-graphex-4.0.0.md) explica qué se investigó, por qué y qué falta. Es una **retrospectiva local congelada**, no un anuncio de versión ni la afirmación de que se corrigieron 100 bugs. El informe recibido es evidencia no rastreada (SHA-256 `6a0ee92c2fd51ce104080bf4ac5403c24c0e00abc075882735949036d478e561`), no una fuente confiable de cargas para ejecutar. Base de implementación `5a155a059a4d3995ead1b639f08136e5d7619aec`; snapshot `8d93483d2fd654012a544ce68365baf1964056f3`, registrado **2026-10-23 23:13:45 -04:00 (America/New_York)**. La rama histórica `9a6ec5adc89bdc24de138179ad1280751a5266e5` no es ancestro de esta implementación.

## Resultado esencial

| Disposición principal | ID | Interpretación correcta |
|---|---:|---|
| bounded-fixed | 51 | Se corrigió un comportamiento acotado y demostrado; pueden quedar subcasos abiertos. |
| partial | 25 | Hay evidencia o una corrección aceptada, pero resta un límite, backend o política. |
| contract | 9 | La expectativa original difiere del contrato vigente/documentado; no implica arreglo general. |
| recommendation | 7 | Consejos de cobertura u organización, no siete bugs independientes. |
| negative-limited | 6 | Afirmaciones tranquilizadoras con evidencia limitada, no seis correcciones. |
| decision-deferred | 2 | Una política pública, de seguridad o ciclo de vida requiere aprobación explícita. |

La [guía de disposición](docs/audit-4.0.0.md) tiene exactamente 100 filas principales. Sus resúmenes no sustituyen los alegatos originales: **C1** abarcaba toda salida `DecimalField` automática en graphql-core 3.3, no solo claves primarias; **C2** alegaba CPU exponencial en el optimizador por fragmentos repetidos y el orden de encuentro fue una corrección posterior. **C3** era otra ruta: ciclos durante coste/profundidad. Muchas etiquetas M/L/SD/Q/N son IDs normalizados por el seguimiento para prosa original sin número; las líneas remiten al texto real. El seguimiento contiene **215 tareas: 190 marcadas, 25 filas principales o solapadas sin marcar**, con **15 áreas principales T03–T17 abiertas**. Los **33 registros principales pendientes/limitados** son 25 parciales + 2 diferidos + 6 negativos limitados, no 33 bugs nuevos demostrados.

Aquí se separan alegato, arreglo causal inspeccionado en diff, commit relacionado aceptado, disposición basada en guía/seguimiento y test representativo. Coincidir en un archivo de prueba no demuestra causalidad. «Añadido» o «modificado» en pruebas se refiere a definiciones AST entre base y snapshot, no a casos recolectados por pytest. Los ejemplos de antes/después de cada hallazgo son **ilustraciones simplificadas** de contratos concretos, no logs copiados ni ejecución nueva de la carga original. Si no hubo arreglo, «después» indica comportamiento sin cambio u observación limitada. Todos los enlaces son relativos al repositorio; la prueba histórica externa se describe sin dar por supuesto que CI pueda leerla.

## Secuencia cronológica del trabajo

1. **Entorno y rutas bloqueantes, 13–14 de octubre.** Se separó graphql-core 3.3.0 soportado del entorno raíz obsoleto 3.2.13, se corrigió la selección de ocho resultados canónicos sin regenerar tiempos, y se trataron por separado ciclos de fragmentos, planificación/orden de fragmentos repetidos, salida/nulabilidad/precisión Decimal y BigInteger. `C1`, `C2` y `C3` tienen causas y pruebas distintas.
2. **Esquema, relaciones y mutaciones, 14–15 de octubre.** Conflictos de registro y selectores de salida dejaron de exponer campos en silencio; enlaces generados, adopción huérfana, metadatos GFK, poda de permisos fría y rutas seleccionadas de `get_queryset` recibieron protecciones acotadas. Siguieron aislamiento de notificaciones automáticas, fábricas de entrada, nombres reservados, interfaces, redacción de errores delete, validación de email/positivos, filtros null/date-part/to-many y paginación tipada. No se creó `strict_scope` global, `full_clean()` general ni atomicidad entre bases.
3. **Paginación, HTTP y concurrencia, 15–18 de octubre.** Se separaron cursores, page:null, tamaño predeterminado, fallo de count, desempate y orden de NULL. Coste con variables, identidad de caché, redacción de errores de producción, no cachear fallos, lotes y limpieza sync/async se resolvieron en unidades distintas. División del lock de permisos, forks de esquema, batching GFK union, errores de metadatos/properties, carreras enum/list e identidad de campo vivo tienen pruebas más estrechas que una garantía universal de concurrencia.
4. **Suscripciones y directivas, 18–23 de octubre.** Ciclo de vida WS, guardas pre-accept, `on_connect` opcional, snapshots delete, comparación Decimal/DateTime/Float finitos, controles SSE heartbeat/lease opt-in y casos `@date`/JSON/directivas avanzaron con límites explícitos. El commit SSE `7ec2264c763859cd840e1475e8f4cec9a47ed8fc` y su cierre `1d26aa6478e2dd7e39585c349a466a34f41c1175` sí son ancestros finales, a diferencia de una frase intermedia obsoleta del mapa. Luego los tipos/avisos M-D10 resolvieron el silencio original sin cerrar todas las políticas de anotaciones.
5. **Verificación y cierre.** El último full registrado para la función auditada fue **6697 passed, 7 skipped, 18 warnings**; cobertura de rama bruta **4687/4894 = 95.770331%** y combinada **17228/17616 = 97.797457%**. Son resultados *históricos del snapshot*, no verificación nueva de este informe. Separadamente, el cierre L-S1 consigna full previo **5825 passed, 7 skipped, 10 warnings** y diez integraciones Redis reales en una instancia; no se repitió full después de esos commits. El commit final `8d93483` cerró solo la redacción M-D10 en documentación. Este informe no implica PR, push, tag, publicación, cambio de API, nueva ejecución Redis ni benchmark.

## Todos los hallazgos originales, en orden de origen


### C1 — DecimalField devuelve null + error con graphql-core 3.3 · ✅ 3.3

**Estado:** bounded-fixed

**Problema original:** `DecimalField` devuelve `null` + error con graphql-core 3.3 · ✅ 3.3 [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 36–44. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 192; la [tarea T03a/T03](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** valor DecimalField Decimal("12.5"). Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```graphql
{ item { amount } }
```

**Antes (ilustrativo):**
```json
{"data": {"item": {"amount": null}}, "errors": ["Float cannot represent Decimal"]}
```

**Después (observado/actual):**
```json
{"data": {"item": {"amount": "12.5"}}}
```

**Cómo se llegó al resultado:**
1. En _to_graphql_field, la salida DecimalField automática recibió primero un adaptador para Float; el cambio posterior la asignó al escalar Decimal exacto. Otra corrección conservó la propagación no nula de la clave primaria.
2. `bd45a6546cbb70a3e4151b087ff51110eed00706`: cambios de fuente en [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py). Commits de seguimiento: `dbabfde2f1367f869c88ed22cfe91ce267ba02ca`, `d27832188f55e72d88551c16e077032d633c9875`.
3. Límite comprobado: Se corrigió primero la serialización Decimal automática, después la nulabilidad de la clave primaria y, por separado, la precisión decimal; los resolvers Float explícitos conservan su contrato.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_decimal_output.py](tests/core/test_decimal_output.py), `test_automatic_decimal_output_preserves_exact_text` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data == {"item": {"amount": str(amount), "ratio": 1.5}}
   ```
   - [tests/core/test_decimal_output.py](tests/core/test_decimal_output.py): `test_automatic_decimal_output_preserves_exact_text` (definición añadida); `test_automatic_decimal_primary_key_uses_decimal_nonnull` (definición añadida); `test_automatic_decimal_field_executes_as_exact_decimal` (definición añadida); `test_explicit_decimal_scalar_and_input_mapping_stay_precise` (definición añadida); `test_explicit_float_resolver_retains_legacy_numeric_contract` (definición añadida); `test_decimal_filter_literals_and_variables_remain_precise` (definición añadida); `test_generated_create_mutation_returns_exact_decimal_output` (definición añadida); `test_decimal_primary_key_keeps_nonnull_and_exact_output` (definición añadida); `test_null_decimal_primary_key_propagates_nonnull_error` (definición añadida).


### C2 — DoS exponencial de CPU por fragmentos repetidos en el optimizador · ✅ 3.3

**Estado:** bounded-fixed

**Problema original:** DoS exponencial de CPU por fragmentos repetidos en el optimizador · ✅ 3.3 [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 46–58. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 193; la [tarea T02b](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** grafo válido de fragmentos repetidos; el orden B-antes-A se verificó en una corrección posterior. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```graphql
query Q { user { ...F0 } }
fragment F0 on User { ...F1 ...F1 }
fragment F1 on User { username }
```

**Antes (ilustrativo):**
```json
{"optimizer_visits": "same selection context expanded along up to 2^8 paths"}
```

**Después (observado/actual):**
```json
{"optimizer_visits": "bounded to <=64 in each tested collector", "effects": "replayed in source encounter order"}
```

**Cómo se llegó al resultado:**
1. En recursive_params y los recorridos de prefetch filtrado, el optimizador memoriza la planificación por contexto de selección y evita recorrer de nuevo cada spread repetido. Después reproduce los efectos de prefetch en orden del documento, sin borrar la segunda aparición.
2. `92b1358f31a2973abe7a817b820d54775a9067a6`: cambios de fuente en [django_graphex/utils.py](django_graphex/utils.py). Commits de seguimiento: `7bec957180edcf138d50256777a9e1bfb196f2b5`.
3. Límite comprobado: La memoización acotó la planificación repetida; otra corrección restituyó los efectos en orden de aparición. La política de FieldNode duplicado no cambió.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_optimizer_fragment_fanout.py](tests/test_optimizer_fragment_fanout.py), `test_valid_repeated_fragment_graph_has_bounded_optimizer_visits` (extracto breve de fuente, no fallo reconstruido):
   ```python
   if calls > 64:
       pytest.fail(f"{name} expanded a repeated fragment more than 64 times")
   ```
   - [tests/test_optimizer_fragment_fanout.py](tests/test_optimizer_fragment_fanout.py): `test_bounded_promotion_iterator_handles_absent_and_cyclic_internal_inputs` (definición añadida); `test_interleaved_fragment_restores_last_annotation_alias_value` (definición añadida); `test_interleaved_fragment_restores_last_prefetch_annotation_plan` (definición añadida); `test_promotion_consumer_bounds_repeated_spreads_without_changing_rows` (definición añadida); `test_reused_fragment_keeps_distinct_relation_path_contexts` (definición añadida); `test_valid_repeated_fragment_graph_has_bounded_optimizer_visits` (definición añadida).


### C3 — DoS exponencial en las reglas de coste/profundidad con fragmentos cíclicos · ✅ 3.3

**Estado:** bounded-fixed

**Problema original:** DoS exponencial en las reglas de coste/profundidad con fragmentos cíclicos · ✅ 3.3 [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 60–72. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 194; la [tarea T02a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** el fragmento A expande B y B vuelve a expandir A. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```graphql
{ root { ...F } }
fragment F on Node { name child { ...F } }
```

**Antes (ilustrativo):**
```json
{"cost_walk": "re-enters F without a precheck"}
```

**Después (observado/actual):**
```json
{"error": "Cyclic fragment reference", "resolver_calls": 0}
```

**Cómo se llegó al resultado:**
1. Una comprobación iterativa compartida del grafo de fragmentos precede a la expansión de profundidad y coste. Rechaza ciclos con GraphQLError sin confundirlos con referencias ausentes ni grafos acíclicos.
2. `2943f4544fe0c56064895a35b8606effe50013be`: cambios de fuente en [django_graphex/_fragment_cycles.py](django_graphex/_fragment_cycles.py), [django_graphex/cost.py](django_graphex/cost.py), [django_graphex/validation.py](django_graphex/validation.py).
3. Límite comprobado: La comprobación compartida de ciclos rechaza el documento antes del recorrido de coste y profundidad; el ciclo obtiene un GraphQLError acotado.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_fragment_cycles.py](tests/test_fragment_cycles.py), `test_cyclic_fanout_is_rejected_before_expensive_walks` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert counts["depth"] <= 10
   ```
   - [tests/test_fragment_cycles.py](tests/test_fragment_cycles.py): `test_cyclic_fanout_is_rejected_before_expensive_walks` (definición añadida); `test_disconnected_fragment_cycle_rejects_direct_cost_analysis` (definición añadida); `test_acyclic_spreads_and_missing_targets_do_not_trigger_cycle_check` (definición añadida); `test_dense_multi_entry_cycle_is_detected` (definición añadida); `test_long_fragment_chain_uses_iterative_cycle_check` (definición añadida); `test_default_view_rejects_cycle_without_running_resolver` (definición añadida).


### A1 — ATOMIC_MUTATIONS no revierte. Solo hace rollback si se activa request.graphene_mutation_has_errors, flag heredado…

**Estado:** partial

**Problema original:** `ATOMIC_MUTATIONS` no revierte. Solo hace rollback si se activa `request.graphene_mutation_has_errors`, flag heredado de graphene que nadie activa; las excepciones de resolver acaban en `result.errors` y el `atomic()` hace commit. Además, `GraphQLView.get_response` no llama a `set_rollback()` (`BaseGraphQLView` sí), así que con `ATOMIC_REQUESTS=True` los errores de campo hacen commit. Repro: create y luego… [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 80. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 195; la [tarea T05a/T05](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** crear una fila y hacer fallar el resolver hermano dentro de una mutación atómica. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```graphql
mutation {
  userCreate(newUser: {username: "example" email: "example@example.test" firstName: "T" lastName: "User" password: "testpassword123"}) { ok user { username } errors { field messages } }
  explode
}
```

**Antes (ilustrativo):**
```json
{"errors": [{"path": ["explode"]}], "persisted_users": 1}
```

**Después (observado/actual):**
```json
{"errors": [{"path": ["explode"]}], "persisted_users": 0}
```

**Cómo se llegó al resultado:**
1. BaseGraphQLView/GraphQLView comprueba ExecutionResult.errors tras ejecutar GraphQL y marca para rollback la transacción Django activa, también con ATOMIC_REQUESTS. La respuesta puede conservar datos parciales aunque se revierta la escritura cubierta en la base predeterminada.
2. `f91022e7a00deda481e63c5b316cc9db003ae1a5`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: Los errores GraphQL revierten escrituras hermanas en la base predeterminada cubierta. ok:false nativo, bases múltiples y sobrescritura por instancia obsoleta siguen siendo decisiones distintas.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_views_atomic_errors.py](tests/test_views_atomic_errors.py), `test_atomic_mutations_execution_error_rolls_back_native_write` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert User.objects.filter(username=username).count() == 0
   ```
   - [tests/test_views_atomic_errors.py](tests/test_views_atomic_errors.py): `test_atomic_mutations_execution_error_rolls_back_native_write` (definición añadida); `test_atomic_requests_execution_error_rolls_back_native_write` (definición añadida); `test_atomic_requests_explicit_flag_rolls_back_without_graphql_error` (definición añadida); `test_atomic_mutations_explicit_flag_still_rolls_back` (definición añadida); `test_nonatomic_execution_error_keeps_durable_write_and_invalidates` (definición añadida); `test_atomic_execution_error_does_not_invalidate_rolled_back_write` (definición añadida); `test_atomic_success_commits_and_invalidates` (definición añadida); `test_native_ok_false_does_not_retroactively_rollback_prior_root` (definición añadida); `test_batch_failed_atomic_operation_then_success_invalidates_once` (definición añadida).

**Límite pendiente:** Los errores GraphQL revierten escrituras hermanas en la base predeterminada cubierta. ok:false nativo, bases múltiples y sobrescritura por instancia obsoleta siguen siendo decisiones distintas.


### A2 — Caché de parseo/validación sin límite de memoria. El LRU está acotado por número de entradas (128), no por bytes.…

**Estado:** partial

**Problema original:** Caché de parseo/validación sin límite de memoria. El LRU está acotado por número de entradas (128), no por bytes. Una query de 1,5 MB genera un AST de unos 120 MB, así que 128 queries distintas fijan unos 15 GB por proceso. Además, con `CACHE_ACTIVE` se parsea y se hashea antes del guard `MAX_REQUEST_BODY_SIZE` (repro: 413 correcto, pero el AST ya quedó cacheado). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 81. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 196; la [tarea T04a/T04](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** cuerpo POST superior al límite con caché activa. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```http
POST /graphql/
Content-Type: application/json

{"query":"{ ping }", "padding":"...above MAX_REQUEST_BODY_SIZE..."}
```

**Antes (ilustrativo):**
```json
{"cache_reads": 1, "http_status": 413}
```

**Después (observado/actual):**
```json
{"cache_reads": 0, "http_status": 413}
```

**Cómo se llegó al resultado:**
1. La vista comprueba el cuerpo POST real antes del parseo o la lectura de caché. Un Content-Length falso no elude la comprobación; los bytes retenidos de caché son otra cuota.
2. `84369e41431e16a6ebe53159c2b7b6fd3401b1db`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: El límite del cuerpo POST se aplica antes del parseo y de la caché; no se aprobó un presupuesto de bytes retenidos ni de memoria agregada.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   - [tests/test_views_body_cap_cache.py](tests/test_views_body_cap_cache.py): `test_oversized_cache_active_body_is_rejected_before_parse_or_cache` (definición añadida); `test_body_at_cap_still_warms_and_hits_response_cache` (definición añadida); `test_tightened_cap_rejects_an_already_cached_query` (definición añadida); `test_spoofed_low_content_length_still_rejects_actual_body` (definición añadida); `test_cache_disabled_retains_early_base_view_rejection` (definición añadida); `test_disabled_cap_allows_the_same_query` (definición añadida); `test_get_with_invalid_body_keeps_bad_request_not_body_cap` (definición añadida); `test_authentication_denial_precedes_body_cap` (definición añadida).

**Límite pendiente:** El límite del cuerpo POST se aplica antes del parseo y de la caché; no se aprobó un presupuesto de bytes retenidos ni de memoria agregada.


### A3 — exclude_fields/only_fields sin validar. En auth.User: exclude_fields=("pasword",) publica password;…

**Estado:** bounded-fixed

**Problema original:** `exclude_fields`/`only_fields` sin validar. En `auth.User`: `exclude_fields=("pasword",)` publica `password`; `exclude_fields="password"` (string sin coma, que se convierte en `set` de caracteres) también lo publica; `only_fields="username"` deja el tipo con 0 campos. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 82. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 197; la [tarea T06a/T06](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** exclusión mal escrita de password en User. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"model": "User", "exclude_fields": ["pasword"]}
```

**Antes (ilustrativo):**
```json
{"registered_fields": ["id", "password"]}
```

**Después (observado/actual):**
```json
{"schema_build_error": "unknown field pasword"}
```

**Cómo se llegó al resultado:**
1. La construcción de salida valida la forma de cada selector y resuelve su nombre frente a campos del modelo, relaciones inversas y campos declarados antes del registro. Una exclusión mal escrita falla, no abre todos los campos.
2. `edb82a30dae7bd96b5a56627963746d6e87b00cd`: cambios de fuente en [django_graphex/types.py](django_graphex/types.py).
3. Límite comprobado: Los selectores de campos inválidos se rechazan explícitamente en vez de degradarse a todos los campos; esto no prueba seguridad universal de cada solicitud anónima.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_output_selector_validation.py](tests/test_output_selector_validation.py), `test_reverse_accessor_and_query_name_selectors_remain_valid` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert ("entries" in fields) == (option == "only_fields")
   ```
   - [tests/test_output_selector_validation.py](tests/test_output_selector_validation.py): `test_reverse_accessor_and_query_name_selectors_remain_valid` (definición añadida); `test_unknown_output_selector_fails_before_registration` (definición añadida); `test_bare_string_output_selector_is_rejected` (definición añadida); `test_valid_model_and_declared_selectors_remain_supported` (definición añadida); `test_noninterface_declared_wire_name_keeps_existing_contract` (definición añadida); `test_generic_foreign_key_and_set_selectors_remain_supported` (definición añadida); `test_declared_custom_only_output_remains_valid` (definición añadida); `test_corrected_exclusion_hides_sensitive_user_field` (definición añadida); `test_one_shot_selector_is_reused_for_projection` (definición añadida); `test_custom_slug_key_and_empty_selector_are_valid` (definición añadida); `test_non_name_selectors_fail_in_configuration` (definición añadida).


### A4 — Dos DjangoObjectType del mismo modelo: gana el último, en silencio. Las relaciones resuelven al último registrado:…

**Estado:** bounded-fixed

**Problema original:** Dos `DjangoObjectType` del mismo modelo: gana el último, en silencio. Las relaciones resuelven al último registrado: si `AdminUser` (todos los campos) se importa después de `PublicUser`, `Post.author` expone los campos del admin. El resultado depende del orden de import y no hay warning. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 83. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 198; la [tarea T06b/T06](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** declarar PublicAuthor y luego AdminAuthor para Author en un Registry. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```python
registry = Registry()
# PublicAuthor and AdminAuthor both use Meta.model = Author and Meta.registry = registry.
# PublicAuthor.only_fields = ("id", "name")
# AdminAuthor.only_fields = ("id", "name", "bio")
```

**Antes (ilustrativo):**
```json
{"registered_output": "AdminAuthor", "exposed_fields": ["id", "name", "bio"]}
```

**Después (observado/actual):**
```json
{"error": "ImproperlyConfigured on second incompatible output"}
```

**Cómo se llegó al resultado:**
1. Registry.register compara modelo Django e identidad pública antes de sustituir una entrada. Un segundo tipo incompatible en el mismo Registry falla; registros distintos permanecen independientes.
2. `65e99d35bd3392a640619a089307a7977627b57f`: cambios de fuente en [django_graphex/registry.py](django_graphex/registry.py), [django_graphex/types.py](django_graphex/types.py).
3. Límite comprobado: El registro identifica la salida pública por modelo y rechaza el segundo tipo incompatible en el mismo registro; registros separados mantienen esquemas separados.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_output_registration_conflict.py](tests/test_output_registration_conflict.py), `test_second_public_author_type_fails_without_shadowing_nested_author` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data == {"post": {"author": {"name": "Public"}}}
   ```
   - [tests/test_output_registration_conflict.py](tests/test_output_registration_conflict.py): `test_second_public_author_type_fails_without_shadowing_nested_author` (definición añadida); `test_identical_class_reregistration_is_idempotent` (definición añadida); `test_distinct_registries_may_publish_distinct_author_views` (definición añadida); `test_non_registering_internal_view_does_not_replace_public_type` (definición añadida); `test_registered_node_remains_list_and_filter_target` (definición añadida); `test_input_registration_and_proxy_model_keys_remain_distinct` (definición añadida); `test_model_mutation_reuses_registered_public_output` (definición añadida); `test_public_and_admin_user_schemas_bind_post_user_independently` (definición añadida).


### A5 — Suscripciones + PERMISSION_SCOPED_SCHEMA: ORM síncrono en el event loop. schema_provider(user) llama a…

**Estado:** bounded-fixed

**Problema original:** Suscripciones + `PERMISSION_SCOPED_SCHEMA`: ORM síncrono en el event loop. `schema_provider(user)` llama a `get_all_permissions()` dentro del loop. En WS toda suscripción de un no-superusuario recibe `You cannot call this from an async context`; en SSE da un 500. Los tests usan un `_User` falso y no lo ven. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 84. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 199; la [tarea T08a/T08](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** usuario Django frío abre WS o SSE. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```python
user = await _real_user(may_view_post=False)
# WS/SSE schema_provider receives this cold Django user.
```

**Antes (ilustrativo):**
```json
{"event_loop": "sync ORM permission lookup / error"}
```

**Después (observado/actual):**
```json
{"schema": "permission-pruned for effective user", "event_loop": "ORM lookup offloaded"}
```

**Cómo se llegó al resultado:**
1. subscription_sse_view y subscription_ws_consumer resuelven en un hilo el esquema podado para un usuario Django frío, evitando ORM síncrono en el event loop. El usuario efectivo sigue determinando los campos privados.
2. `ac72aa7b9ca4b4532c26535f43e569c1cda0503e`: cambios de fuente en [django_graphex/subscriptions/transports/sse.py](django_graphex/subscriptions/transports/sse.py), [django_graphex/subscriptions/transports/ws.py](django_graphex/subscriptions/transports/ws.py).
3. Límite comprobado: La resolución del proveedor de esquema sale del bucle asíncrono para el usuario Django frío; se conservan las restricciones de campos privados sin inferir todos los proveedores de autenticación.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_transport_cold_permissions.py](tests/subscriptions/test_transport_cold_permissions.py), `test_sse_provider_resolves_cold_real_user_permissions` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert response.status_code == 200
   ```
   - [tests/subscriptions/test_transport_cold_permissions.py](tests/subscriptions/test_transport_cold_permissions.py): `test_sse_provider_resolves_cold_real_user_permissions` (definición añadida); `test_sync_providers_preserve_context_and_error_paths` (definición añadida); `test_ws_concurrent_operations_resolve_provider_once` (definición añadida); `test_ws_provider_resolves_cold_real_user_permissions` (definición añadida); `test_ws_real_auth_handshake_prunes_cold_permissions` (definición añadida).
   - [tests/subscriptions/test_transport_real_user_resolution.py](tests/subscriptions/test_transport_real_user_resolution.py): `test_sse_authenticated_caller_streams` (localizador histórico fuera del inventario); `test_sse_anonymous_caller_is_denied` (localizador histórico fuera del inventario); `test_sse_session_of_a_deleted_user_is_denied` (localizador histórico fuera del inventario); `test_sse_request_without_any_session_is_denied` (localizador histórico fuera del inventario); `test_sse_schema_provider_receives_a_resolved_user` (localizador histórico fuera del inventario); `test_ws_authenticated_caller_streams` (localizador histórico fuera del inventario); `test_ws_anonymous_caller_is_denied` (localizador histórico fuera del inventario); `test_ws_session_of_a_deleted_user_is_denied` (localizador histórico fuera del inventario); `test_ws_scope_without_a_user_is_denied` (localizador histórico fuera del inventario).


### A6 — Redis caído rompe las escrituras. El callback on_commit de las bindings no es robusto: ConnectionError sube al…

**Estado:** bounded-fixed

**Problema original:** Redis caído rompe las escrituras. El callback `on_commit` de las bindings no es robusto: `ConnectionError` sube al llamador de `Model.objects.create()` (la fila ya está commiteada) y los `on_commit` posteriores no se ejecutan. Un error en `to_representation` rompe `save()`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 85. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 200; la [tarea T08b/T08](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** se confirma save del modelo, pero falla el envío Redis automático. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```python
with transaction.atomic():
    row = HookModel.objects.create(text="committed-before-send")
    transaction.on_commit(lambda: later.append("continued"))
# The automatic channel-layer group_send raises after commit.
```

**Antes (ilustrativo):**
```json
{"row_exists": true, "caller_exception": "post-commit send failure", "later_on_commit_callback_ran": false}
```

**Después (observado/actual):**
```json
{"row_exists": true, "caller_exception": null, "later_on_commit_callback_ran": true, "delivery_guaranteed": false}
```

**Cómo se llegó al resultado:**
1. El envío automático de SubscriptionBinding posterior al commit captura y registra excepciones de Redis cuando la fila ya es duradera. El broadcast manual mantiene la propagación estricta de errores al llamador.
2. `901c35bd9b754f6b21b6f61715c0f62ea0604d15`: cambios de fuente en [django_graphex/subscriptions/bindings.py](django_graphex/subscriptions/bindings.py).
3. Límite comprobado: La notificación automática se trata como mejor esfuerzo para no convertir un guardado confirmado en una excepción de escritura. El broadcast manual permanece estricto y no se promete entrega.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_automatic_best_effort.py](tests/subscriptions/test_automatic_best_effort.py), `test_snapshot_failure_does_not_abort_atomic_save` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert HookModel.objects.filter(pk=row.pk).exists()
   ```
   - [tests/subscriptions/test_automatic_best_effort.py](tests/subscriptions/test_automatic_best_effort.py): `test_snapshot_failure_does_not_abort_atomic_save` (definición añadida); `test_failed_snapshot_does_not_change_generated_mutation_result` (definición añadida); `test_failed_delivery_preserves_autocommit_update_and_delete` (definición añadida); `test_explicit_manual_broadcast_remains_strict` (definición añadida); `test_rollback_discards_automatic_failures_and_snapshots` (definición añadida); `test_async_automatic_failure_logs_only_metadata` (definición añadida); `test_base_exception_is_not_swallowed` (definición añadida); `test_logging_backend_failure_does_not_abort_save` (definición añadida); `test_database_write_error_remains_strict` (definición añadida); `test_broken_notification_transaction_still_propagates_database_error` (definición añadida); `test_missing_layer_warning_backend_failure_is_best_effort` (definición añadida); `test_send_failure_keeps_committed_write_and_later_callback` (definición añadida).


### A7 — default_factory se evalúa una sola vez al compilar. uid: UUID = Field(default_factory=uuid4) da el mismo UUID en…

**Estado:** bounded-fixed

**Problema original:** `default_factory` se evalúa una sola vez al compilar. `uid: UUID = Field(default_factory=uuid4)` da el mismo UUID en todas las peticiones; `tags: list = Field(default_factory=list)` es la misma lista compartida (mutarla filtra estado entre peticiones), y queda horneado en el SDL. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 86. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 201; la [tarea T09a/T09](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** dos objetos de entrada independientes omiten uid. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```graphql
mutation { submit(payload: {}) { result } }
```

**Antes (ilustrativo):**
```json
{"uids": ["same-schema-time-UUID", "same-schema-time-UUID"]}
```

**Después (observado/actual):**
```json
{"uids": ["fresh-UUID-A", "fresh-UUID-B"]}
```

**Cómo se llegó al resultado:**
1. compile_input_type conserva metadatos de fábrica sin invocarla al crear SDL. La coerción evalúa cada campo ausente por objeto y poda metadatos de alias sobrescritos; los valores explícitos y la introspección no la invocan.
2. `eee1a6dd2b7743763066d81f544e709c7c76d180`: cambios de fuente en [django_graphex/core/input_compiler.py](django_graphex/core/input_compiler.py), [django_graphex/core/schema_pruner.py](django_graphex/core/schema_pruner.py). Commits de seguimiento: `ef7f6b5ad5b9e711d36ab7d3c45694fc3c987906`.
3. Límite comprobado: La fábrica se ejecuta por objeto de entrada ya coercionado cuando falta el campo; el valor explícito la omite y la introspección no la ejecuta.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_input_factory_per_object.py](tests/core/test_input_factory_per_object.py), `test_omitted_factory_values_are_fresh_across_graphql_executions` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert second.data == {"submit": {"result": "uid-2:seed,changed"}}
   ```
   - [tests/core/test_input_factory_per_object.py](tests/core/test_input_factory_per_object.py): `test_omitted_factory_values_are_fresh_across_graphql_executions` (definición añadida); `test_factory_respects_variables_explicit_values_and_field_aliases` (definición añadida); `test_nested_inputs_and_inline_aliases_create_distinct_objects` (definición añadida); `test_factory_failures_are_graphql_input_errors_without_private_text` (definición añadida); `test_permission_pruned_input_does_not_reinsert_hidden_factory_field` (definición añadida); `test_validated_data_factory_remains_a_model_validation_default` (definición añadida); `test_model_derived_input_keeps_omitted_factory_field_absent` (definición añadida); `test_overwritten_wire_alias_only_runs_effective_field_factory` (definición añadida); `test_literal_field_overwriting_factory_alias_does_not_run_factory` (definición añadida).


### A8 — BigIntegerField/PositiveBigIntegerField se mapean al Int de 32 bits. 240 da null + Int cannot represent non 32-bit…

**Estado:** bounded-fixed

**Problema original:** `BigIntegerField`/`PositiveBigIntegerField` se mapean al `Int` de 32 bits. `240` da `null` + `Int cannot represent non 32-bit signed integer`. En input se rechazan valores > 2³¹-1. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 87. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 202; la [tarea T03b/T03](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** BigIntegerField contiene 9007199254740993. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"model_field": "BigIntegerField", "value": 9007199254740993}
```

**Antes (ilustrativo):**
```json
{"graphql_type": "Int", "data": null, "error": "32-bit range"}
```

**Después (observado/actual):**
```json
{"graphql_type": "decimal-string scalar", "data": "9007199254740993"}
```

**Cómo se llegó al resultado:**
1. BigInteger del modelo usa un escalar de texto decimal en los límites GraphQL, evitando el Int de 32 bits y el redondeo flotante. Los ID de relación y choices se ajustaron por separado.
2. `8f86dc8927eb66a62dcdcf8936c40b659d6e6ead`: cambios de fuente en [django_graphex/core/__init__.py](django_graphex/core/__init__.py), [django_graphex/core/fields.py](django_graphex/core/fields.py), [django_graphex/core/input_compiler.py](django_graphex/core/input_compiler.py), [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py), [django_graphex/core/scalars.py](django_graphex/core/scalars.py). Commits de seguimiento: `12a7506a8b83c75ee211e1174dca9c3fbdf748c2`.
3. Límite comprobado: Los enteros grandes se representan con texto decimal exacto; los identificadores de relación y los enums conservan reglas aparte.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_bigint.py](tests/core/test_bigint.py), `test_auto_output_uses_decimal_string_bigint` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert fields["positive"].type.name == "BigInt"
   ```
   - [tests/core/test_bigint.py](tests/core/test_bigint.py): `test_auto_output_uses_decimal_string_bigint` (definición añadida); `test_explicit_bigint_primary_key_keeps_nonnull_wrapper` (definición añadida); `test_nullable_bigint_output_keeps_null` (definición añadida); `test_explicit_scalar_override_keeps_its_declared_contract` (definición añadida); `test_null_bigint_primary_key_propagates_nonnull_error` (definición añadida); `test_signed_minimum_and_out_of_range_output` (definición añadida); `test_generated_input_parses_decimal_strings_to_python_int` (definición añadida); `test_bigint_rejects_invalid_variables_before_resolver` (definición añadida); `test_bigint_accepts_only_string_literals` (definición añadida); `test_positive_bigint_validation_keeps_nonnegative_constraint` (definición añadida); `test_relation_ids_with_explicit_bigint_pk_keep_old_input_type` (definición añadida); `test_bigint_foreign_key_id_mutation_accepts_existing_wire_values` (definición añadida); `test_positive_bigint_numeric_choice_mutation_accepts_valid_enum` (definición añadida); `test_generated_model_mutation_persists_exact_bigint` (definición añadida); `test_automatic_filter_lookups_use_bigint` (definición añadida); `test_automatic_bigint_filter_executes_orm_query` (definición añadida).


### A9 — Delete con FK PROTECT/RESTRICT lanza ProtectedError crudo: error top-level en vez del sobre ok:false, errors:[…],…

**Estado:** bounded-fixed

**Problema original:** Delete con FK `PROTECT`/`RESTRICT` lanza `ProtectedError` crudo: error top-level en vez del sobre `ok:false, errors:[…]`, y filtra nombres de modelo y campo. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 88. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 203; la [tarea T10a/T10](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** borrar una fila protegida. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"mutation": "generated delete", "row_id": 7, "constraint": "protected relation"}
```

**Antes (ilustrativo):**
```json
{"errors": ["database constraint/table detail"]}
```

**Después (observado/actual):**
```json
{"errors": ["safe generated delete error"]}
```

**Cómo se llegó al resultado:**
1. La eliminación generada traduce fallos de integridad protegidos y no mapeados a un error GraphQL seguro. No captura toda excepción de aplicación ni expone nombres internos de restricciones o modelos.
2. `74146dd55f74108b9b3c4b5d913c2a21b36c550a`: cambios de fuente en [django_graphex/mutation.py](django_graphex/mutation.py), [django_graphex/types.py](django_graphex/types.py). Commits de seguimiento: `8db3083585f44e65cbf5f7eba496f3b4e004e728`.
3. Límite comprobado: La eliminación generada redacta detalles internos del error de base de datos; no se añadió una captura indiscriminada de cualquier excepción.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_generated_delete_security.py](tests/test_generated_delete_security.py), `test_blocked_generated_delete_hides_collector_details` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert payload["data"] == {"deleteCategory": None}
   ```
   - [tests/test_generated_delete_security.py](tests/test_generated_delete_security.py): `test_blocked_generated_delete_hides_collector_details` (definición añadida); `test_blocked_delete_preserves_sibling_rollback` (definición añadida); `test_generated_delete_keeps_success_and_not_found_contract` (definición añadida); `test_unclassified_integrity_error_uses_generic_generated_policy` (definición añadida).


### A10 — IntegrityError no mapeado y validators de Django ignorados. CheckConstraint, UniqueConstraint…

**Estado:** partial

**Problema original:** `IntegrityError` no mapeado y validators de Django ignorados. `CheckConstraint`, `UniqueConstraint` condicional/funcional y el upsert anidado de reverse-O2O sin `id` provocan un `IntegrityError` crudo con el nombre del constraint. Tampoco se ejecutan `validators`/`full_clean`: se acepta `email="not-an-email"` y `title=""` con `blank=False`; `PositiveIntegerField=-1` da `IntegrityError`; un int enorme da… [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 89. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 204; la [tarea T10](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** crear con email inválido o entero positivo negativo. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"generated_create": {"email": "not-an-email", "positive_count": -1}}
```

**Antes (ilustrativo):**
```json
{"save_attempt": "invalid covered values reached persistence"}
```

**Después (observado/actual):**
```json
{"save_attempt": false, "errors": ["email/positive input validation"]}
```

**Cómo se llegó al resultado:**
1. La conversión de entrada generada valida enteros positivos y email cubiertos antes de guardar y redacta fallos mapeados. No ejecuta full_clean para todo modelo ni vuelve atómicos los upserts anidados.
2. `6bd37b2d9dcac7359f3f0c94fc47f65a350bac5f`: cambios de fuente en [django_graphex/core/fields.py](django_graphex/core/fields.py). Commits de seguimiento: `81f79492a3b5906687194cbf143ca483c80cfee9`, `610162956ca645d85bf7e7749a19ada81aac055f`.
3. Límite comprobado: Se validaron casos acotados de email y enteros positivos y se redactaron errores de persistencia generada. full_clean general y upsert anidado siguen pendientes.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_positive_input_validation.py](tests/core/test_positive_input_validation.py), `test_positive_validator_preserves_null_and_reports_invalid_choice_value` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert validator(None) is None
   ```
   - [tests/core/test_positive_input_validation.py](tests/core/test_positive_input_validation.py): `test_positive_validator_preserves_null_and_reports_invalid_choice_value` (definición añadida); `test_generated_positive_input_rejects_negative_before_sql` (definición añadida); `test_positive_field_error_preserves_earlier_sibling_write` (definición añadida); `test_positive_choices_validate_stored_number_and_keep_enum` (definición añadida); `test_custom_schema_preserves_nullable_positive_choice_enum` (definición añadida); `test_nested_positive_input_rejects_child_before_parent_persists` (definición añadida).

**Límite pendiente:** Se validaron casos acotados de email y enteros positivos y se redactaron errores de persistencia generada. full_clean general y upsert anidado siguen pendientes.


### A11 — @replace sin tope de salida. @replace(old:"", new:"<20 KB>") sobre 5.000 caracteres genera 100 M de caracteres en…

**Estado:** bounded-fixed

**Problema original:** `@replace` sin tope de salida. `@replace(old:"", new:"<20 KB>")` sobre 5.000 caracteres genera 100 M de caracteres en 8 ms; los alias lo multiplican y el coste no cuenta directivas. Es un DoS de memoria. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 90. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 205; la [tarea T04b/T04](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** aplicar @replace con sustitución que expande la cadena. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"directive": "@replace", "source": "aaaa", "old": "", "new": "long", "max_output_length": 8}
```

**Antes (ilustrativo):**
```json
{"result": "expansion longer than 8 code points"}
```

**Después (observado/actual):**
```json
{"error": "result exceeds configured output cap"}
```

**Cómo se llegó al resultado:**
1. La directiva replace calcula un límite prospectivo del resultado Unicode antes de materializar la expansión. Falla una salida individual excesiva; muchas salidas pequeñas no tienen cuota agregada nueva.
2. `441899a520778e03518d81816eef0ddbd00dab8a`: cambios de fuente en [django_graphex/directives/string.py](django_graphex/directives/string.py), [django_graphex/settings.py](django_graphex/settings.py).
3. Límite comprobado: Se limita cada resultado Unicode de replace antes de materializar una salida excesiva; no hay cuota agregada para muchos resultados pequeños.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_replace_output_limit.py](tests/test_replace_output_limit.py), `test_replace_rejects_expansion_before_returning_result` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data == {"text": None, "other": "safe"}
   ```
   - [tests/test_replace_output_limit.py](tests/test_replace_output_limit.py): `test_replace_rejects_expansion_before_returning_result` (definición añadida); `test_replace_nonnull_error_bubbles` (definición añadida); `test_replace_limit_default_is_one_million` (definición añadida); `test_replace_limit_rejects_nonpositive_values` (definición añadida); `test_replace_limit_rejects_noninteger_values` (definición añadida); `test_replace_limit_none_preserves_uncapped_behavior` (definición añadida); `test_replace_exact_python_semantics` (definición añadida); `test_replace_rejects_already_oversized_noop` (definición añadida); `test_replace_rejects_without_calling_replace` (definición añadida); `test_replace_preserves_null_field` (definición añadida).


### A12 — and sobre relaciones to-many devuelve vacío. Se pliega en un único Q, que reutiliza un solo JOIN:…

**Estado:** bounded-fixed

**Problema original:** `and` sobre relaciones to-many devuelve vacío. Se pliega en un único `Q`, que reutiliza un solo JOIN: `and:[{tags:{label:"x"}},{tags:{label:"y"}}]` devuelve `[]` aunque el post tenga ambas etiquetas. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 91. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 206; la [tarea T11/T11c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** un post tiene etiquetas x e y en dos filas relacionadas. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"post_id": 1, "tags": ["x", "y"], "filter": {"AND": [{"tag": "x"}, {"tag": "y"}]}}
```

**Antes (ilustrativo):**
```json
{"result_ids": []}
```

**Después (observado/actual):**
```json
{"result_ids": [1]}
```

**Cómo se llegó al resultado:**
1. El backend de filtros separa predicados relacionales de ramas AND sobre colecciones, de modo que filas relacionadas distintas pueden satisfacer cada rama. Los predicados de una misma rama siguen refiriéndose a la misma fila.
2. `342a4ab92b2797e142a325d11311495cfc5808e2`: cambios de fuente en [django_graphex/filtering/backend.py](django_graphex/filtering/backend.py). Commits de seguimiento: `4c3e4bbd0df9948c53eb3d2d4846064571934d10`.
3. Límite comprobado: Las ramas AND separadas pueden encontrar filas relacionadas distintas; un predicado compuesto conserva la semántica de misma fila.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_and_many_filtering.py](tests/test_and_many_filtering.py), `test_public_deeper_and_keeps_one_outer_comment` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert sorted(row["title"] for row in rows["results"]) == expected
   ```
   - [tests/test_and_many_filtering.py](tests/test_and_many_filtering.py): `test_public_deeper_and_keeps_one_outer_comment` (definición añadida); `test_public_deeper_grouping_and_missing_child_sql_null` (definición añadida); `test_public_m2m_and_branches_match_distinct_rows` (definición añadida); `test_public_reverse_fk_and_branches_match_distinct_rows` (definición añadida); `test_public_and_keeps_relation_object_same_row` (definición añadida); `test_public_nested_or_not_and_multihop_correlation` (definición añadida); `test_public_exact_null_and_isnull_keep_absent_reverse_row` (definición añadida); `test_empty_boolean_operands_and_direct_many_ids` (definición añadida); `test_unset_boolean_children_keep_independent_branch` (definición añadida); `test_scoped_queryset_alias_projection_and_one_sql` (definición añadida); `test_public_paginated_count_and_variables` (definición añadida).


### A13 — Cursor en memoria con orden float/Decimal/UUID provoca TypeError. _coerce_like solo convierte int y fecha/hora; el…

**Estado:** partial

**Problema original:** Cursor en memoria con orden float/Decimal/UUID provoca `TypeError`. `_coerce_like` solo convierte int y fecha/hora; el resto se compara `str` contra el valor real y sale una excepción no-GraphQL en la segunda página. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 92. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 207; la [tarea T12](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** continuar segunda página con cursor Decimal o UUID. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"order_field": "Decimal", "cursor": "typed boundary at 1.25", "next_page": true}
```

**Antes (ilustrativo):**
```json
{"error": "string/Decimal comparison TypeError"}
```

**Después (observado/actual):**
```json
{"continuation": "next matching window", "malformed_cursor": "GraphQL error"}
```

**Cómo se llegó al resultado:**
1. La decodificación del cursor restaura límites Float, Decimal y UUID tipados antes de comparar en memoria y rechaza valores inválidos. Cubre continuaciones concretas, no todos los backends de cursor.
2. `e18f02b8b15b7cdfaf1fad06adc545527f1f8026`: cambios de fuente en [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py). Commits de seguimiento: `c3a063aeaaa0e765d9b3d3dc7749168ec6f2c842`.
3. Límite comprobado: La continuación de cursores tipados cubiertos funciona y los límites decodificados inválidos se rechazan; otros contratos de cursor permanecen abiertos.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_pagination_cursor_typed_http.py](tests/test_pagination_cursor_typed_http.py), `test_generated_root_cursor_and_nested_relation_http` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert token == nested_first["pageInfo"]["endCursor"]
   ```
   - [tests/test_pagination_cursor_typed_http.py](tests/test_pagination_cursor_typed_http.py): `test_generated_root_cursor_and_nested_relation_http` (definición añadida); `test_malformed_cursor_is_existing_graphql_error_envelope` (definición añadida); `test_typed_invalid_cursor_value_http_error` (definición añadida); `test_typed_invalid_cursor_direct_pagination_and_page_info` (definición añadida); `test_unapproved_other_type_coercion_fallback_is_unchanged` (definición añadida); `test_tied_boundaries_match_orm_in_both_orderings` (definición añadida).

**Límite pendiente:** La continuación de cursores tipados cubiertos funciona y los límites decodificados inválidos se rechazan; otros contratos de cursor permanecen abiertos.


### SD1 — get_queryset del tipo destino no se aplica a través de relaciones. Lo señalaron cuatro auditores por separado

**Estado:** partial

**Problema original:** `get_queryset` del tipo destino no se aplica a través de relaciones. Lo señalaron cuatro auditores por separado: [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 98–99. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 208; la [tarea T07/R06a/R06f/R06g](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** padre visible apunta a destino oculto. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"parent_id": 1, "destination_id": 9, "destination_visible": false}
```

**Antes (ilustrativo):**
```json
{"data": {"parent": {"destination": {"id": 9}}}}
```

**Después (observado/actual):**
```json
{"data": {"parent": {"destination": null}}}
```

**Cómo se llegó al resultado:**
1. Los campos automáticos aplican el queryset visible del destino antes de exponer FK, one-to-one, FK inversa y M2M o sus conteos. Los resolvers personalizados no se reescriben.
2. `0ee46b94bb391bb59c599f9e88af46ce0a8f0f1b`: cambios de fuente en [django_graphex/converter.py](django_graphex/converter.py), [django_graphex/fields.py](django_graphex/fields.py), [django_graphex/utils.py](django_graphex/utils.py). Commits de seguimiento: `603a117f67a41502f93d6551dbc5355c592b23ca`, `8ebfd43fce7071660795398e70f90ed0e2359054`.
3. Límite comprobado: Las relaciones automáticas FK, OneToOne, FK inversa y M2M aplican el scope de destino en los casos aprobados; los resolvers personalizados y una política global quedan fuera.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_sd1_m2m_output_scope.py](tests/test_sd1_m2m_output_scope.py), `test_optimized_m2m_scope_uses_source_database_alias` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert context.calls
   ```
   - [tests/test_sd1_m2m_output_scope.py](tests/test_sd1_m2m_output_scope.py): `test_optimized_m2m_scope_uses_source_database_alias` (definición añadida); `test_declared_m2m_members_follow_destination_scope` (definición añadida); `test_reverse_m2m_members_follow_destination_scope` (definición añadida); `test_declared_m2m_count_only_is_scoped` (definición añadida); `test_reverse_m2m_count_only_is_scoped` (definición añadida); `test_m2m_scope_uses_current_request_and_compiled_schema` (definición añadida); `test_m2m_count_precedes_nested_page_limit` (definición añadida); `test_unscoped_prefetch_cache_cannot_authorize_m2m_output` (definición añadida); `test_custom_through_and_reverse_accessor_scope_m2m_output` (definición añadida); `test_optimized_scoped_m2m_prefetch_does_not_grow_per_parent` (definición añadida).

**Límite pendiente:** Las relaciones automáticas FK, OneToOne, FK inversa y M2M aplican el scope de destino en los casos aprobados; los resolvers personalizados y una política global quedan fuera.


### SD2 — Filtro como oráculo: Author{posts:{title:{icontains:"secret"}}} filtra por posts ocultos, y un recorrido por…

**Estado:** partial

**Problema original:** Filtro como oráculo: `Author{posts:{title:{icontains:"secret"}}}` filtra por posts ocultos, y un recorrido por prefijos recupera los títulos (`filtering/translate.py:229-235`). 📖 [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 100. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 209; la [tarea T07/R06b/R06c/R06d/R06e](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** filtrar origen por fila relacionada oculta. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"source_id": 1, "children": [{"id": 7, "visible": false, "tag": "x"}], "filter": {"child_tag": "x"}}
```

**Antes (ilustrativo):**
```json
{"result_ids": [1]}
```

**Después (observado/actual):**
```json
{"result_ids": [], "direct_source_fk_id": "unchanged"}
```

**Cómo se llegó al resultado:**
1. La traducción de filtros intersecta los IDs atravesados con get_queryset de cada destino. En reverse-FK y M2M, varios predicados sobre un hijo exigen un mismo testigo hijo visible, no combinan datos de hijos distintos; los IDs directos de hijo reverse/M2M se acotan. Un ID directo FK/OneToOne propiedad de la fuente conserva su significado; la salida proyectada es otro límite.
2. `0f64533aff4210b77f4b4659d74fa264f46cf283`: cambios de fuente en [django_graphex/filtering/backend.py](django_graphex/filtering/backend.py). Commits de seguimiento: `603a117f67a41502f93d6551dbc5355c592b23ca`.
3. Límite comprobado: Los filtros FK, OneToOne, FK inversa y M2M recorren únicamente destinos visibles en los casos cubiertos; el ID directo de origen conserva su política anterior.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_sd2_forward_o2o_filter_scope.py](tests/test_sd2_forward_o2o_filter_scope.py), `test_forward_and_reverse_destination_policies` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert found == ["visible-user"]
   ```
   - [tests/test_sd2_forward_o2o_filter_scope.py](tests/test_sd2_forward_o2o_filter_scope.py): `test_forward_and_reverse_destination_policies` (definición añadida); `test_null_and_direct_id_controls` (definición añadida); `test_boolean_and_empty_forward_nodes_keep_visible_sources` (definición añadida); `test_reverse_then_forward_one_to_one_scopes_each_destination` (definición añadida); `test_forward_scope_errors_fail_closed` (definición añadida).

**Distinción de alcance:** Con una fuente visible y dos hijos, `child.color="red" AND child.size="large"` exige **el mismo hijo visible** como testigo; un hijo solo rojo y otro solo grande no bastan. Un hijo oculto nunca sirve de testigo. Los IDs directos de hijo inverso/objetivo M2M se acotan al destino; un ID directo FK/OneToOne propiedad de la fuente no cambia de significado en silencio. Véanse `tests/test_sd2_forward_o2o_filter_scope.py` y la fila aceptada de la guía; recorridos personalizados y scope de salida siguen aparte.

**Límite pendiente:** Los filtros FK, OneToOne, FK inversa y M2M recorren únicamente destinos visibles en los casos cubiertos; el ID directo de origen conserva su política anterior.


### SD3 — Vinculación (IDOR de enlace): category:{id:<pk de otro tenant>} o tags:[<pk ajeno>] enlaza filas fuera de scope, y…

**Estado:** bounded-fixed

**Problema original:** Vinculación (IDOR de enlace): `category:{id:<pk de otro tenant>}` o `tags:[<pk ajeno>]` enlaza filas fuera de scope, y la diferencia entre "no existe" y "ok" confirma su existencia (`nested.py:381-398`, `:626-640`). 🔁 [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 101. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 210; la [tarea T07c/T07](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** enlazar ID de categoría de otro tenant. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"mutation": "link category", "category_id": 9, "category_visible": false}
```

**Antes (ilustrativo):**
```json
{"linked_category_id": 9}
```

**Después (observado/actual):**
```json
{"error": "destination not visible", "linked_category_id": null}
```

**Cómo se llegó al resultado:**
1. El enlace anidado generado resuelve cada ID de destino mediante candidatos visibles antes de asignarlo. Un ID oculto falla en el enlace, no se adjunta para ocultarlo después.
2. `a96ca179b90714f39c4b69a79ebb24255aa17578`: cambios de fuente en [django_graphex/nested.py](django_graphex/nested.py), [django_graphex/utils.py](django_graphex/utils.py).
3. Límite comprobado: Los ID de destino generados se comprueban contra opciones visibles antes de enlazar; esta protección no equivale a ACL global de todas las lecturas.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_destination_link_scope.py](tests/test_destination_link_scope.py), `test_hidden_relation_id_has_the_same_error_as_missing` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert not Post.objects.filter(title__in=("hidden-link", "missing-link")).exists()
   ```
   - [tests/test_destination_link_scope.py](tests/test_destination_link_scope.py): `test_hidden_relation_id_has_the_same_error_as_missing` (definición añadida); `test_nested_link_is_scoped_before_parent_save` (definición añadida); `test_existing_nested_child_update_is_not_reclassified_as_a_link` (definición añadida); `test_request_registry_not_global_registry_selects_destination_scope` (definición añadida); `test_unregistered_destination_adds_no_fk_lookup` (definición añadida); `test_destination_hook_for_wrong_model_fails_before_write` (definición añadida).


### SD4 — Reclamar filas huérfanas: un hijo con FK nula de cualquier tenant se puede adoptar y editar nombrando su pk,…

**Estado:** bounded-fixed

**Problema original:** Reclamar filas huérfanas: un hijo con FK nula de cualquier tenant se puede adoptar y editar nombrando su pk, cuando el modelo hijo no tiene host registrado (`nested.py:560-585`). ✅ 3.3 [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 102. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 211; la [tarea T07/T07d/T07e](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** padre 10 intenta adoptar hijo huérfano 7. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"parent_id": 10, "child_id": 7, "child_parent_id": null}
```

**Antes (ilustrativo):**
```json
{"child_parent_id": 10}
```

**Después (observado/actual):**
```json
{"error": "orphan adoption denied", "child_parent_id": null}
```

**Cómo se llegó al resultado:**
1. La actualización anidada de FK inversa exige que el hijo pertenezca al host actual. Una fila huérfana no puede reclamarse solo por presentar su clave primaria.
2. `bb592ddb7c1e90e0300ee4be8f30252b2c19d6a6`: cambios de fuente en [django_graphex/nested.py](django_graphex/nested.py).
3. Límite comprobado: Se deniega la adopción huérfana sin host en el caso reverse-FK probado; no se infiere una política general de todos los hijos.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_nested_sd4_orphan_scope.py](tests/test_nested_sd4_orphan_scope.py), `test_existing_orphan_requires_child_update_host` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data["updateParent"]["ok"] is False
   ```
   - [tests/test_nested_sd4_orphan_scope.py](tests/test_nested_sd4_orphan_scope.py): `test_existing_orphan_requires_child_update_host` (definición añadida); `test_update_host_preserves_scope_and_child_permission` (definición añadida); `test_existing_owned_and_new_children_keep_prior_paths` (definición añadida); `test_later_orphan_denial_rolls_back_earlier_sibling_write` (definición añadida); `test_update_serving_mutation_host_admits_visible_orphan` (definición añadida); `test_unrelated_registry_cannot_supply_child_update_host` (definición añadida); `test_parent_create_keeps_new_child_path` (definición añadida).


### SD5 — GenericForeignKey: el tipo plano GenericForeignKeyType devuelve app_label/model/pk del destino sin comprobar…

**Estado:** bounded-fixed

**Problema original:** GenericForeignKey: el tipo plano `GenericForeignKeyType` devuelve `app_label`/`model`/`pk` del destino sin comprobar permisos y el pruner lo deja público (`core/output_compiler.py:245-327`). 📖 [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 103. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 212; la [tarea T07/T07d/T07f](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** destino GenericForeignKey oculto. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"query": "{ comment { body target { appLabel modelName id } } }", "permissions": ["tests.view_track2gfkcomment"], "target_exists": true}
```

**Antes (ilustrativo):**
```json
{"data": {"comment": {"body": "public", "target": {"appLabel": "tests", "modelName": "Track2Account", "id": "<target id>"}}}}
```

**Después (observado/actual):**
```json
{"data": {"comment": {"body": "public", "target": null}}}
```

**Cómo se llegó al resultado:**
1. El podador de permisos comprueba el destino GenericForeignKey antes de proyectar metadatos planos de aplicación, modelo y clave. Si falla lectura o scope, retira todos esos campos.
2. `f0b3126260224c62ff1422e1e8e86ba5d8bf11bb`: cambios de fuente en [django_graphex/core/_flat_gfk_scope.py](django_graphex/core/_flat_gfk_scope.py), [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py), [django_graphex/core/permission_signature_cache.py](django_graphex/core/permission_signature_cache.py), [django_graphex/core/schema_pruner.py](django_graphex/core/schema_pruner.py), [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: El pruner elimina metadatos planos GFK cuando falla lectura o scope del destino; no se implementó una ACL global.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_flat_gfk_pruned_security.py](tests/test_flat_gfk_pruned_security.py), `test_flat_target_denied_by_actual_model_permission` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert print_schema(denied) == print_schema(allowed)
   ```
   - [tests/test_flat_gfk_pruned_security.py](tests/test_flat_gfk_pruned_security.py): `test_flat_target_denied_by_actual_model_permission` (definición añadida); `test_missing_flat_target_stays_null` (definición añadida); `test_flat_target_uses_registered_scope_per_request` (definición añadida); `test_registered_default_hook_adds_no_membership_query` (definición añadida); `test_invalid_registered_scope_fails_closed` (definición añadida); `test_registered_scope_preserves_join_and_slice_membership` (definición añadida); `test_flat_cache_keys_unregistered_target_grants` (definición añadida); `test_explicit_prune_grants_never_widen_from_context_or_reprune` (definición añadida); `test_unmarked_schema_keeps_projected_signature` (definición añadida); `test_http_cache_rechecks_same_users_target_grant` (definición añadida).


### SD6 — Recomendación: un modo opt-in strict_scope (o activado por defecto en una mayor) que aplique el scope del tipo…

**Estado:** recommendation

**Problema original:** Recomendación: un modo opt-in `strict_scope` (o activado por defecto en una mayor) que aplique el scope del tipo destino vía `Prefetch`/`Exists`, más un *system check* que avise cuando un tipo con `get_queryset` propio es alcanzable por una relación. Combinado con A3/A4, hoy es fácil filtrar datos sin darse cuenta. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 105. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 213; la [tarea T07](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** propuesta de strict_scope global para relaciones. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"current opt-in relation behavior"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"unchanged; proposal deferred"
```

**Cómo se llegó al resultado:**
1. No se instaló strict_scope ni un system check. Ese predeterminado rechazaría esquemas que hoy optan por scope relacional y exige una decisión pública de compatibilidad.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: No se adoptó un interruptor strict_scope ni una comprobación del sistema: cambiaría semántica pública y requiere decisión específica.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### M-S1 — Con MAX_PAGE_SIZE=None, limit:$n se costea como DEFAULT_PAGE_SIZE y el literal limit:100000 como 100000: mover el…

**Estado:** bounded-fixed

**Problema original:** Con `MAX_PAGE_SIZE=None`, `limit:$n` se costea como `DEFAULT_PAGE_SIZE` y el literal `limit:100000` como 100000: mover el valor a una variable esquiva `MAX_QUERY_COST`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 114. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 214; la [tarea T13/T13a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** variable activa una rama de consulta costosa. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"query": "query Probe($n: Int = 5) { items(limit: $n) { child { name } } }", "operationName": "Probe", "variables": {"n": 150}, "MAX_QUERY_COST": 120}
```

**Antes (ilustrativo):**
```json
{"resolver_calls": 1}
```

**Después (observado/actual):**
```json
{"resolver_calls": 0, "status": 400, "error_code": "QUERY_TOO_COMPLEX", "computed_cost": 151}
```

**Cómo se llegó al resultado:**
1. La operación seleccionada se analiza con las variables aportadas antes de ejecutar resolvers y se rechaza si supera el coste configurado. Es un guardia de ejecución, no un presupuesto SQL o de memoria.
2. `96e1f9efb0569d27a08235c84656cf6be100caf1`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: El coste de la operación seleccionada se comprueba con variables antes de ejecutarla; esto no representa un límite total de memoria o consultas SQL.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_cost_variable_http.py](tests/test_cost_variable_http.py), `test_high_variable_is_rejected_before_resolver_on_validation_cache_hits` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert validate_spy.call_count == 1
   ```
   - [tests/test_cost_variable_http.py](tests/test_cost_variable_http.py): `test_high_variable_is_rejected_before_resolver_on_validation_cache_hits` (definición añadida); `test_small_and_declared_default_variables_remain_accepted` (definición añadida); `test_high_declared_default_is_checked_when_variable_is_omitted` (definición añadida); `test_no_cost_budget_remains_a_noop` (definición añadida); `test_static_fallback_still_rejects_a_small_bound_variable` (definición añadida); `test_only_selected_operation_is_bound_checked_and_invalid_input_keeps_its_error` (definición añadida); `test_unselected_operation_still_receives_static_validation` (definición añadida); `test_bound_skip_directive_controls_actual_cost` (definición añadida); `test_custom_scalar_and_executor_build_once_before_cost_refusal` (definición añadida); `test_input_default_factories_are_not_recoerced_for_bound_cost` (definición añadida).


### M-S2 — Defaults abiertos: MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE, MAX_QUERY_DEPTH, MAX_QUERY_COST y MAX_REQUEST_BODY_SIZE valen…

**Estado:** partial

**Problema original:** Defaults abiertos: `MAX_PAGE_SIZE`, `DEFAULT_PAGE_SIZE`, `MAX_QUERY_DEPTH`, `MAX_QUERY_COST` y `MAX_REQUEST_BODY_SIZE` valen `None`; listas `in:` sin tope (40k valores dan `too many SQL variables`); `and`/`or`/`not` sin límite de anchura ni profundidad. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 115. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 215; la [tarea T11/T13/R07](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** omitir pageSize en un campo paginado. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"paginated_field": "posts", "pageSize": "omitted", "configured_default": 100}
```

**Antes (ilustrativo):**
```json
{"default_bound": "not established by original premise"}
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
{"effective_page_size": 100, "depth_or_byte_cap": "not inferred"}
```

**Cómo se llegó al resultado:**
1. La inspección separó el tamaño de página 100 ya aceptado de políticas de profundidad, anchura y bytes. No se cambió otro predeterminado por una alegación agrupada.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
   El predeterminado de página 100 procede del cambio distinto `M-F7` (`5faeef7188`); esta fila no añadió límites predeterminados de profundidad, anchura ni bytes retenidos.
3. Límite comprobado: El tamaño de página omitido ya tiene predeterminado 100; profundidad, anchura y cuotas de bytes requieren evidencia o política separadas.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** El tamaño de página omitido ya tiene predeterminado 100; profundidad, anchura y cuotas de bytes requieren evidencia o política separadas.


### M-S3 — ALLOW_INTROSPECTION=False por defecto, pero es inerte sin DisableIntrospectionMiddleware. Está documentado, aunque…

**Estado:** contract

**Problema original:** `ALLOW_INTROSPECTION=False` por defecto, pero es inerte sin `DisableIntrospectionMiddleware`. Está documentado, aunque resulta engañoso: con settings de serie `__schema` responde. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 116. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 216; la [tarea T13/T13g](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** solicitar introspección sin middleware configurado. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"audit assumes hard block by default"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"configuration-dependent contract documented"
```

**Cómo se llegó al resultado:**
1. El guardia de introspección documentado depende de instalar el middleware. No se añadió middleware predeterminado; el despliegue debe configurar ese límite opt-in.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: La guía explica el requisito del middleware configurado; el valor predeterminado de ejecución no cambió.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_introspection_docs.py](tests/test_introspection_docs.py), `test_security_guide_installs_middleware_before_blocking_introspection` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert configuration["ALLOW_INTROSPECTION"] is False
   ```
   - [tests/test_introspection_docs.py](tests/test_introspection_docs.py): `test_security_guide_installs_middleware_before_blocking_introspection` (definición añadida); `test_introspection_setting_requires_installed_middleware` (definición añadida).


### M-S4 — Los errores se serializan con str(error) sin enmascarar (SQL, nombres de constraint y de tabla), incluso con…

**Estado:** bounded-fixed

**Problema original:** Los errores se serializan con `str(error)` sin enmascarar (SQL, nombres de constraint y de tabla), incluso con `DEBUG=False`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 117. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 217; la [tarea T13/T13c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** excepción GraphQL inesperada en producción. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"environment": "production", "resolver_exception": "database table secret"}
```

**Antes (ilustrativo):**
```json
{"errors": ["database table secret"]}
```

**Después (observado/actual):**
```json
{"errors": ["sanitized internal error"]}
```

**Cómo se llegó al resultado:**
1. La vista HTTP de producción clasifica excepciones inesperadas de ejecución y emite errores GraphQL redactados, no detalles internos. Diagnóstico de desarrollo y otras clases de error siguen separados.
2. `a401f9e25e6989ccb28571815931fc6baf624593`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: La respuesta HTTP de producción cubierta omite detalles internos; no se deduce una auditoría universal de cada error.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_http_internal_error_diagnostics.py](tests/test_http_internal_error_diagnostics.py), `test_internal_failures_have_safe_http_diagnostics_and_correlated_logs` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert payload["data"] == {"healthy": "healthy", "failure": None}
   ```
   - [tests/test_http_internal_error_diagnostics.py](tests/test_http_internal_error_diagnostics.py): `test_internal_failures_have_safe_http_diagnostics_and_correlated_logs` (definición añadida); `test_ids_are_unique_and_wrapped_internal_extensions_are_dropped` (definición añadida); `test_public_errors_validation_and_http_parse_errors_keep_their_contract` (definición añadida); `test_debug_and_shared_transport_formatter_keep_existing_diagnostics` (definición añadida); `test_shared_formatter_is_unchanged_in_production` (definición añadida); `test_nonnull_error_keeps_null_data_and_safe_message_in_every_view` (definición añadida); `test_logger_failure_cannot_change_safe_http_response` (definición añadida); `test_custom_view_formatter_remains_an_explicit_override` (definición añadida); `test_production_error_documentation_example_matches_the_wire_contract` (definición añadida).


### M-S5 — La clave de caché GET concatena query, variables y operationName sin separador; hay colisión demostrada con un…

**Estado:** bounded-fixed

**Problema original:** La clave de caché GET concatena `query`, `variables` y `operationName` sin separador; hay colisión demostrada con un comentario `#`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 118. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 218; la [tarea T13/T13b](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** componentes ambiguos de clave de caché GET. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"key_parts_a": ["ab", "c"], "key_parts_b": ["a", "bc"]}
```

**Antes (ilustrativo):**
```json
{"encoded_a": "abc", "encoded_b": "abc"}
```

**Después (observado/actual):**
```json
{"encoded_a": "2:ab1:c", "encoded_b": "1:a2:bc"}
```

**Cómo se llegó al resultado:**
1. La clave de caché enmarca componentes con longitud antes del hash; concatenaciones ambiguas ya no colisionan dentro de la misma partición de identidad. No rediseña la política entre identidades.
2. `d9d2c40f7bb4af2fc2125f76d344c124f8a3df74`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: Los componentes de la clave se enmarcan con longitud para separar secuencias ambiguas; la política entre identidades no se rediseñó.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_views_cache_key_framing.py](tests/test_views_cache_key_framing.py), `test_comment_boundary_cannot_select_another_cached_operation` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert response.status_code == 200
   ```
   - [tests/test_views_cache_key_framing.py](tests/test_views_cache_key_framing.py): `test_comment_boundary_cannot_select_another_cached_operation` (definición añadida); `test_get_components_and_body_have_unambiguous_boundaries` (definición añadida); `test_get_raw_body_is_documented_and_changes_default_cache_key` (definición añadida); `test_utf8_and_framing_like_text_cannot_cross_get_components` (definición añadida); `test_frame_length_counts_utf8_bytes` (definición añadida); `test_missing_and_empty_get_parameters_remain_equivalent` (definición añadida); `test_custom_fetch_cache_key_override_remains_in_dispatch` (definición añadida).


### M-S6 — Los shortcuts Field/CharField/IntField… no aceptan required_perms: bajo PERMISSION_SCOPED_SCHEMA quedan públicos…

**Estado:** contract

**Problema original:** Los shortcuts `Field`/`CharField`/`IntField`… no aceptan `required_perms`: bajo `PERMISSION_SCOPED_SCHEMA` quedan públicos en silencio. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 119. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 219; la [tarea T06](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** pasar required_perms como atajo de permisos. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"assumed accepted by audit"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"TypeError; use documented lower-case field form"
```

**Cómo se llegó al resultado:**
1. La API de campo acepta el argumento de permisos documentado en minúsculas, no el atajo propuesto required_perms. Conservar TypeError evita inventar una firma pública.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: El shortcut required_perms sigue produciendo TypeError; el argumento de campo documentado funciona y no se inventó una nueva API.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_permission_keyword_boundaries.py](tests/test_permission_keyword_boundaries.py), `test_permission_hook_excludes_positional_only_and_varargs_names` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert policy(object(), action=narrowed["action"]) == "list"
   ```
   - [tests/test_permission_keyword_boundaries.py](tests/test_permission_keyword_boundaries.py): `test_permission_hook_excludes_positional_only_and_varargs_names` (localizador histórico fuera del inventario).


### M-D1 — Lost update: un update parcial hace save() de la fila completa, así que dos updates concurrentes de campos…

**Estado:** partial

**Problema original:** Lost update: un update parcial hace `save()` de la fila completa, así que dos updates concurrentes de campos distintos se pisan. Usar `update_fields`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 124. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 220; la [tarea T05](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** guardar una instancia obsoleta tras otra actualización. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"loaded_instance": {"title": "old", "bio": "old"}, "other_writer": {"title": "new"}, "first_instance_save": {"bio": "new"}}
```

**Antes (ilustrativo):**
```json
{"final_title": "old"}
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
{"final_title": "old", "change": "no universal update_fields policy accepted"}
```

**Cómo se llegó al resultado:**
1. Un testigo secuencial con instancia obsoleta confirmó que un save amplio puede sobrescribir un valor reciente. Se registra el riesgo; no se añadió update_fields universal ni se afirmó una carrera PostgreSQL.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: El testigo secuencial nativo confirmó la sobrescritura por instancia obsoleta; no se aprobó update_fields general ni se afirmó una carrera PostgreSQL.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** El testigo secuencial nativo confirmó la sobrescritura por instancia obsoleta; no se aprobó update_fields general ni se afirmó una carrera PostgreSQL.


### M-D2 — transaction.atomic() sin using= en las escrituras anidadas: con multi-DB no hay transacción externa y quedan…

**Estado:** partial

**Problema original:** `transaction.atomic()` sin `using=` en las escrituras anidadas: con multi-DB no hay transacción externa y quedan huérfanos. Lo mismo ocurre con `on_commit` sin `using=` en bindings. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 125. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 221; la [tarea T05/T08/R05b/R05c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** CREATE anidado con alias de base del padre. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"nested_create": {"parent": "new", "child": "new"}, "parent_alias": "B", "through_route_after_generated_id": "A"}
```

**Antes (ilustrativo):**
```json
{"possible_child_alias": "A", "possible_partial_write": true}
```

**Después (observado/actual):**
```json
{"alias_B_rows_after_rollback": 0, "alias_A_through_rows": 0}
```

**Cómo se llegó al resultado:**
1. El backend Django incluido elige el alias de escritura del padre aún sin guardar y fija allí las escrituras hijas. Comprueba el routing explícito de la tabla through antes del DML y vuelve a comprobarlo con el ID de padre generado antes de enlazar; una divergencia tardía revierte las escrituras en ese alias local. UPDATE, backends personalizados, atomicidad multibase y cambios tras la última comprobación siguen aparte.
2. `c408989f75d4d4f5729edd5296d93c36108f8efe`: cambios de fuente en [django_graphex/nested.py](django_graphex/nested.py). Commits de seguimiento: `57e0aaba2de6954f6aa1dc10b4ea690d4e16a686`.
3. Límite comprobado: El backend Django incluido fija alias en CREATE anidado y rechaza rutas through divergentes antes de DML; backends personalizados y atomicidad entre bases siguen abiertos.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_routed_nested_atomic.py](tests/test_routed_nested_atomic.py), `test_explicit_divergent_through_router_rejects_before_any_write` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert writes == []
   ```
   - [tests/test_routed_nested_atomic.py](tests/test_routed_nested_atomic.py): `test_explicit_divergent_through_router_rejects_before_any_write` (definición añadida); `test_post_id_divergent_through_router_rolls_back_without_foreign_sql` (definición añadida); `test_late_failure_after_real_writes_rolls_back_chosen_alias` (definición añadida); `test_later_child_failure_rolls_back_create` (definición añadida); `test_later_child_failure_rolls_back_update` (definición añadida); `test_nested_create_succeeds_on_own_alias` (definición añadida); `test_populated_parent_routes_entire_nested_create_to_one_alias` (definición añadida); `test_instance_routed_create_initializes_once_and_commits_only_on_success` (definición añadida); `test_instance_routed_forward_and_m2m_writes_share_parent_boundary` (definición añadida); `test_custom_backend_keeps_existing_create_instance_contract` (definición añadida); `test_nested_routing_contract_documents_native_instance_create_boundary` (definición añadida).

**Dos comprobaciones de routing:** (1) Si la tabla through M2M explícita va a otro alias, se rechaza antes del DML. (2) Si la ruta cambia al asignarse el PK del padre, se reevalúa antes del enlace y se revierten las escrituras en el alias local elegido al divergir. Esto no convierte varias bases en una transacción ni garantiza que el router permanezca estable después de la última comprobación. `tests/test_routed_nested_atomic.py` prueba ambos casos.

**Límite pendiente:** El backend Django incluido fija alias en CREATE anidado y rechaza rutas through divergentes antes de DML; backends personalizados y atomicidad entre bases siguen abiertos.


### M-D3 — DecimalField → Float pierde precisión (≥ 17 dígitos), además de C1

**Estado:** partial

**Problema original:** `DecimalField` → `Float` pierde precisión (≥ 17 dígitos), además de C1. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 126. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 222; la [tarea T03c/T03](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** Decimal de 17 o más dígitos significativos. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"model_value": "Decimal(\"9007199254740993\")"}
```

**Antes (ilustrativo):**
```json
{"graphql_output": 9007199254740992}
```

**Después (observado/actual):**
```json
{"graphql_output": "9007199254740993"}
```

**Cómo se llegó al resultado:**
1. La salida Decimal automática usa el escalar exacto de cadena decimal en vez de conversión flotante. El redondeo al recargar SQLite y la coerción de entrada son límites distintos.
2. `d27832188f55e72d88551c16e077032d633c9875`: cambios de fuente en [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py).
3. Límite comprobado: La salida decimal automática usa texto exacto; el redondeo al recargar SQLite y la coerción de entrada son temas distintos.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_decimal_output.py](tests/core/test_decimal_output.py), `test_automatic_decimal_output_preserves_exact_text` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data == {"item": {"amount": str(amount), "ratio": 1.5}}
   ```
   - [tests/core/test_decimal_output.py](tests/core/test_decimal_output.py): `test_automatic_decimal_output_preserves_exact_text` (definición añadida); `test_automatic_decimal_primary_key_uses_decimal_nonnull` (definición añadida); `test_automatic_decimal_field_executes_as_exact_decimal` (definición añadida); `test_explicit_decimal_scalar_and_input_mapping_stay_precise` (definición añadida); `test_explicit_float_resolver_retains_legacy_numeric_contract` (definición añadida); `test_decimal_filter_literals_and_variables_remain_precise` (definición añadida); `test_generated_create_mutation_returns_exact_decimal_output` (definición añadida); `test_decimal_primary_key_keeps_nonnull_and_exact_output` (definición añadida); `test_null_decimal_primary_key_propagates_nonnull_error` (definición añadida).

**Límite pendiente:** La salida decimal automática usa texto exacto; el redondeo al recargar SQLite y la coerción de entrada son temas distintos.


### M-D4 — El scalar Decimal acepta NaN, Infinity y 1E+999999999, lo que provoca un ValidationError de Django no-GraphQL

**Estado:** partial

**Problema original:** El scalar `Decimal` acepta `NaN`, `Infinity` y `1E+999999999`, lo que provoca un `ValidationError` de Django no-GraphQL. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 127. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 223; la [tarea T03](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** enviar NaN, Infinity o exponente extremo en mutación. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"generated_mutation_decimal": "NaN"}
```

**Antes (ilustrativo):**
```json
{"save_attempt": "possible downstream validation failure"}
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
{"save_attempt": false, "graphql_error": "non-finite decimal rejected"}
```

**Cómo se llegó al resultado:**
1. La mutación pública rechaza NaN, ambas infinidades y el exponente extremo ejercitado antes de guardar. No se ejecutó el token exacto 1E+999999999 del informe.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: La mutación pública rechaza NaN, ±Infinity y 1e1000 sin guardar; el caso exacto 1E+999999999 no se ejecutó.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** La mutación pública rechaza NaN, ±Infinity y 1e1000 sin guardar; el caso exacto 1E+999999999 no se ejecutó.


### M-D5 — El scalar JSON deja pasar str que sean JSON válido: el string "123" se emite como el número 123

**Estado:** contract

**Problema original:** El scalar `JSON` deja pasar `str` que sean JSON válido: el string `"123"` se emite como el número `123`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 128. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 224; la [tarea T15](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** introducir cadena JSON "123" en dos escalares distintos. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"audit treats both as numeric coercion"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"JSONField stays string; JSONString yields integer"
```

**Cómo se llegó al resultado:**
1. La cadena de JSONField crudo se conserva en entrada, base y salida; JSONString decodifica deliberadamente texto JSON. Son dos contratos de scalar, no un único defecto.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Un JSONField público conserva la cadena "123" tras entrada, BD y salida; JSONString interpreta deliberadamente ese texto JSON como entero 123.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_explicit_null_and_json_input.py](tests/test_explicit_null_and_json_input.py), `test_python_type_mapping_via_build_model_schema` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert isinstance(gql_input, GraphQLInputObjectType)
   ```
   - [tests/test_explicit_null_and_json_input.py](tests/test_explicit_null_and_json_input.py): `test_update_bio_null_clears_field` (localizador histórico fuera del inventario); `test_update_bio_omitted_keeps_field` (localizador histórico fuera del inventario); `test_update_nullable_fk_null_clears` (localizador histórico fuera del inventario); `test_update_m2m_null_clears` (localizador histórico fuera del inventario); `test_update_m2m_empty_list_clears` (localizador histórico fuera del inventario); `test_update_m2m_omitted_untouched` (localizador histórico fuera del inventario); `test_update_required_field_null_is_validation_error` (localizador histórico fuera del inventario); `test_create_explicit_null_on_nullable_field` (localizador histórico fuera del inventario); `test_update_bio_null_clears_field` (localizador histórico fuera del inventario); `test_update_bio_omitted_keeps_field` (localizador histórico fuera del inventario); `test_update_m2m_null_clears` (localizador histórico fuera del inventario); `test_update_required_field_null_is_validation_error` (localizador histórico fuera del inventario); `test_python_type_mapping_via_build_model_schema` (localizador histórico fuera del inventario); `test_input_sdl_renders_json` (localizador histórico fuera del inventario); `test_create_stores_dict` (localizador histórico fuera del inventario); `test_create_stores_list` (localizador histórico fuera del inventario); `test_update_stores_dict` (localizador histórico fuera del inventario); `test_create_dict_through_graphql` (localizador histórico fuera del inventario); `test_json_marker_maps_to_raw_json` (localizador histórico fuera del inventario); `test_bare_any_still_falls_back_to_string` (localizador histórico fuera del inventario); `test_json_scalar_importable_from_core` (localizador histórico fuera del inventario); `test_jsonstring_escape_hatch_still_importable` (localizador histórico fuera del inventario).


### M-D6 — JSONRaw mantiene Undefined en listas y acepta 1e999, que acaba como Infinity (JSON inválido)

**Estado:** partial

**Problema original:** `JSONRaw` mantiene `Undefined` en listas y acepta `1e999`, que acaba como `Infinity` (JSON inválido). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 129. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 225; la [tarea T15/R03i/R03j](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** variable ausente en lista JSON y número no finito. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"raw_json_input": [1, "omitted $v", 3], "variables": {}}
```

**Antes (ilustrativo):**
```json
{"list_slot": "ambiguous omitted position"}
```

**Después (observado/actual):**
```json
{"resolver_input": [1, null, 3], "raw_1e999": "rejected before resolver"}
```

**Cómo se llegó al resultado:**
1. La coerción JSON cruda coloca null en la posición de lista de una variable ausente y omite una clave de objeto ausente. Rechaza números no finitos antes del resolver; la salida tiene otro contrato.
2. `3a7f2da0ac65e49d2fde02d403dbe95de664f143`: cambios de fuente en [django_graphex/core/scalars.py](django_graphex/core/scalars.py).
3. Límite comprobado: La lista JSON sitúa null donde falta la variable y la clave de objeto omitida sigue omitida; números no finitos fallan antes del resolver. Salida cruda mantiene límites propios.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_json_nonfinite_input.py](tests/test_json_nonfinite_input.py), `test_literal_overflow_rejected_before_resolver` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert "JSON cannot represent non-finite numbers" in result.errors[0].message
   assert _CALLS == []
   ```
   - [tests/test_json_nonfinite_input.py](tests/test_json_nonfinite_input.py): `test_literal_overflow_rejected_before_resolver` (definición añadida); `test_nested_variable_infinity_rejected_before_resolver` (definición añadida); `test_variable_nonfinite_values_fail_before_resolver` (definición añadida); `test_overflow_literal_shapes_fail_before_resolver` (definición añadida); `test_nonfinite_default_literal_rejected` (definición añadida); `test_available_variable_literal_path_rejects_nonfinite` (definición añadida); `test_finite_and_string_values_keep_identity_and_wire_shape` (definición añadida); `test_huge_finite_int_and_native_container_aliases_are_not_rewritten` (definición añadida); `test_defaults_missing_members_and_explicit_null_keep_their_contract` (definición añadida); `test_http_input_error_uses_graphql_error_wire` (definición añadida); `test_raw_output_and_json_string_scalar_remain_separate` (definición añadida).

**Límite pendiente:** La lista JSON sitúa null donde falta la variable y la clave de objeto omitida sigue omitida; números no finitos fallan antes del resolver. Salida cruda mantiene límites propios.


### M-D7 — Colisión de nombres de enum: shop.Order.line_status y shop_order.Line.status generan ambos…

**Estado:** bounded-fixed

**Problema original:** Colisión de nombres de enum: `shop.Order.line_status` y `shop_order.Line.status` generan ambos `shopOrderLineStatusEnum`, y el segundo recibe el enum del primero. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 130. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 226; la [tarea T06c/T06](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** dos enums homónimos con choices incompatibles. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"enum_name": "shopOrderLineStatusEnum", "first_field_choices": ["OPEN", "CLOSED"], "second_field_choices": ["OPEN", "ARCHIVED"]}
```

**Antes (ilustrativo):**
```json
{"second_field_reused_first_enum_values": ["OPEN", "CLOSED"]}
```

**Después (observado/actual):**
```json
{"error": "incompatible shopOrderLineStatusEnum registration", "first_enum_values_remain": ["OPEN", "CLOSED"]}
```

**Cómo se llegó al resultado:**
1. La creación de enums compara nombre y estructura de valores antes de reutilizar caché; tipos incompatibles homónimos fallan. Choices equivalentes reordenados reutilizan el enum sin alterar valores de cable.
2. `34b37e6f014c8c6d3308dabc1427fbd68748eac6`: cambios de fuente en [django_graphex/converter.py](django_graphex/converter.py), [django_graphex/core/compiler.py](django_graphex/core/compiler.py). Commits de seguimiento: `0b267dab424c506ed85b080b2754a496c39ee6c1`.
3. Límite comprobado: Se rechazan colisiones incompatibles de nombre; el reordenamiento de elecciones equivalentes sigue siendo válido.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_choices_enum_name_collisions.py](tests/core/test_choices_enum_name_collisions.py), `test_incompatible_choices_collision_rejects_schema` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert set(original.values) == expected_values
   ```
   - [tests/core/test_choices_enum_name_collisions.py](tests/core/test_choices_enum_name_collisions.py): `test_incompatible_choices_collision_rejects_schema` (definición añadida); `test_distinct_registries_keep_colliding_names_isolated` (definición añadida); `test_compatible_same_name_reuses_registry_enum` (definición añadida); `test_colliding_choice_descriptions_are_incompatible` (definición añadida); `test_generated_create_input_rejects_incompatible_enum` (definición añadida); `test_filter_input_rejects_incompatible_enum` (definición añadida); `test_reordered_compatible_choices_share_public_schema_and_inputs` (definición añadida).


### M-D8 — Campos de modelo llamados schema, copy, json, dict, validate… chocan con atributos de pydantic y rompen el tipo…

**Estado:** bounded-fixed

**Problema original:** Campos de modelo llamados `schema`, `copy`, `json`, `dict`, `validate`… chocan con atributos de pydantic y rompen el tipo con un `TypeError`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 131. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 227; la [tarea T09b/T09](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** columna Django model_config en conflicto con los metadatos de configuración de Pydantic. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```python
class Record(models.Model):
    model_config = models.CharField(max_length=40)
# GraphQL input: {modelConfig: "created"}; backend column: model_config
```

**Antes (ilustrativo):**
```json
{"schema_build": "Pydantic reserved-name collision"}
```

**Después (observado/actual):**
```json
{"validation_alias": "model_config", "internal_field": "isolated private name", "django_value": "created"}
```

**Cómo se llegó al resultado:**
1. Las columnas Django reservadas por Pydantic, como model_config, reciben un campo interno privado libre de colisión con validation_alias="model_config" y un mapa al nombre original. La entrada pública sigue siendo modelConfig y el atributo de modelo sigue siendo model_config; validadores/serializadores heredados se redirigen al campo aislado en una base derivada sin mutar la base del usuario. model_dump/model_validate se cubren por separado.
2. `480167af7d17354d477041f76a4a662b1814604e`: cambios de fuente en [django_graphex/core/backend.py](django_graphex/core/backend.py), [django_graphex/core/fields.py](django_graphex/core/fields.py), [django_graphex/core/input_compiler.py](django_graphex/core/input_compiler.py), [django_graphex/core/validators.py](django_graphex/core/validators.py). Commits de seguimiento: `9e36576513cf1e0ced46ad96a799666caa39a3f0`.
3. Límite comprobado: La construcción conserva los campos reservados del modelo y sus hooks heredados; no se afirma solución para cualquier nombre futuro.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_reserved_model_fields.py](tests/core/test_reserved_model_fields.py), `test_inherited_model_config_hooks_use_original_field` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert row.model_config == "original"
   ```
   - [tests/core/test_reserved_model_fields.py](tests/core/test_reserved_model_fields.py): `test_inherited_model_config_hooks_use_original_field` (definición añadida); `test_inherited_mixed_hooks_preserve_modes_and_caller_base` (definición añadida); `test_generated_mutation_persists_reserved_field` (definición añadida); `test_internal_name_avoids_real_column_and_preserves_inline_validation` (definición añadida); `test_reserved_default_and_partial_omission_keep_original_presence` (definición añadida); `test_original_methods_remain_available_on_generated_class` (definición añadida); `test_existing_custom_base_config_and_dump_override_remain_active` (definición añadida).

**Mapa de nombres, no campo descartado:** Una columna Django `model_config` no puede reutilizar el atributo homónimo de configuración de Pydantic como campo generado. `build_model_schema` crea un nombre interno libre, añade `Field(validation_alias="model_config")` y registra el nombre original. La mutación GraphQL aún acepta `modelConfig`; el backend persiste la columna real `model_config`. La base Pydantic derivada redirige validadores/serializadores heredados de esa columna sin alterar la base del usuario ni otros hooks. `model_dump`/`model_validate` son otros nombres reservados cubiertos, no prueba sobre cualquier palabra de Python.


### M-D9 — Interfaces: ignoran name= (usan to_camel_case(attr)), mientras que los object types lo respetan

**Estado:** bounded-fixed

**Problema original:** Interfaces: ignoran `name=` (usan `to_camel_case(attr)`), mientras que los object types lo respetan. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 132. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 228; la [tarea T09c/T09](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** campo internal_name = field(..., name="name") con nombre GraphQL explícito; el resolver conserva la clave Python. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```python
class Named(DjangoInterfaceType):
    internal_name = field(GraphQLString, name="name")
    custom_label = field(GraphQLString, name="label")
# Resolver lookup keys remain internal_name and custom_label.
```

**Antes (ilustrativo):**
```json
{"SDL": "internalName: String", "query_name": "unavailable"}
```

**Después (observado/actual):**
```json
{"SDL": "name: String", "query": "{ asInterface { name } }", "data": {"asInterface": {"name": "Ada"}}}
```

**Cómo se llegó al resultado:**
1. DjangoInterfaceType emite cada campo declarado con _rendered_field_name(field, field_name), respetando el nombre GraphQL explícito en interfaz e implementador. La búsqueda del resolver sigue usando internal_name/custom_label de Python; los campos públicos son name/label/displayLabel, no internalName/customLabel. El segundo commit acota la proyección a implementadores y no renombra NamedAuthor.
2. `0ea68ac4f120bc2bfedfde65c6e3fb7c97a7111e`: cambios de fuente en [django_graphex/core/polymorphic_compiler.py](django_graphex/core/polymorphic_compiler.py), [django_graphex/types.py](django_graphex/types.py). Commits de seguimiento: `a64d7f58adc370ac250a4c61fc2c82e84eeb7c01`.
3. Límite comprobado: Los nombres públicos explícitos de campos name/label se conservan en interfaz e implementador, mientras los resolvers siguen buscando internal_name/custom_label. No se cambió el nombre del tipo NamedAuthor ni una identidad global.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_audit_forked_pair_and_field_names.py](tests/core/test_audit_forked_pair_and_field_names.py), `test_explicit_interface_name_is_shared_with_implementor` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert {"name", "label", "displayLabel"} <= set(fields)
   ```
   - [tests/core/test_audit_forked_pair_and_field_names.py](tests/core/test_audit_forked_pair_and_field_names.py): `test_explicit_interface_name_is_shared_with_implementor` (definición añadida).


### M-D10 — Input: Literal, dict[...], set y Union se degradan a String sin warning

**Estado:** bounded-fixed

**Problema original:** Input: `Literal`, `dict[...]`, `set` y `Union` se degradan a `String` sin warning. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 133. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 229; la [tarea T09/R08a/R08b/R08c/R08d/R08e/R08f/R08g/R08h/R08i/R08j/R08k/R08l/R08m/R08n/R08o/R08p/R08q/R08r](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** anotaciones Literal, dict, set y Union de entrada. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```python
class Payload(InputType):
    state: Literal["draft", "published"]
    flags: dict[str, bool]
    amounts: set[float]
    value: Union[int, str]
```

**Antes (ilustrativo):**
```json
{"SDL": "String fallback without warning for alleged shapes"}
```

**Después (observado/actual):**
```json
{"SDL": {"state": "named enum", "flags": "JSON", "amounts": "[Float!]!", "value": "IntOrString"}, "wire_input": {"state": "DRAFT", "flags": {"enabled": true}, "amounts": [1.5, 1.5, 2.0], "value": "42"}, "resolver_values": {"state": "draft", "flags": {"enabled": true}, "amounts": "{1.5, 2.0} (Python set)", "value": "42"}}
```

**Cómo se llegó al resultado:**
1. Anotaciones aprobadas obtuvieron mapeos precisos en unidades separadas; las formas aún no soportadas avisan antes del fallback String anterior. El fallback es visible, no eliminado universalmente.
2. `7a1dfe3b8406a15fc1fdd2b7221196181449e350`: cambios de fuente en [django_graphex/core/input_compiler.py](django_graphex/core/input_compiler.py). Commits de seguimiento: `b5e48232e4615b0ae5e1d4b29ed874f55a3f859b`, `7d0165c2df1b3e0006b5a4fd28abf55bd2d4975b`, `ca95f9039978693562e7c26294a2c3d9e7a0e9d3`, `d66b1752449a0441bd06d6e0167f2790ab32c907`.
3. Límite comprobado: Las formas todavía no soportadas conservan String pero avisan; varias formas precisas aprobadas recibieron mapeo tipado. El alcance original se cerró sin afirmar soporte universal.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_input_typing_fallback_warnings.py](tests/core/test_input_typing_fallback_warnings.py), `test_public_input_mutation_warns_without_changing_wire_behavior` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert sum(name in message for message in messages) == count
   ```
   - [tests/core/test_input_typing_fallback_warnings.py](tests/core/test_input_typing_fallback_warnings.py): `test_public_input_mutation_warns_without_changing_wire_behavior` (definición añadida); `test_supported_annotations_do_not_gain_fallback_warnings` (definición añadida).

**Contratos exactos aceptados (no reescritura genérica de anotaciones):**
1. `Literal["draft", "published"]` con solo cadenas se convierte en enum nombrado en SDL, pero llega al resolver como cadena original. Un Literal numérico o mixto todavía avisa y conserva el fallback String.
2. `dict[str, int]`, `dict[str, str]` y `dict[str, bool]` exactos, también con `typing.Dict`, usan entrada JSON compartida y validan el tipo declarado sin convertir cadenas a números/booleanos. Un campo omitido conserva su default declarado; omisión y null explícito no se confunden. Las listas anidadas de hojas admitidas conservan nulabilidad recursiva y coerción normal de elemento único a lista.
3. `set[int]`, `set[str]`, `set[bool]`, `set[float]`, `set[uuid.UUID]` y `set[decimal.Decimal]` exactos, también con alias `typing.Set`, exponen respectivamente `[Int!]!`, `[String!]!`, `[Boolean!]!`, `[Float!]!`, `[UUID!]!` y `[Decimal!]!`. La entrada única/lista aceptada llega al resolver como `set` Python sin orden y sin duplicados. Boolean exige booleanos reales; Float/Decimal/UUID conservan validación nativa numérica, de precisión o UUID. Un literal Float con overflow o un valor Decimal NaN/sNaN/±Infinity aportado se rechaza **solo en ese campo**, antes del resolver; defaults/fábricas históricas omitidas no se reescriben en silencio.
4. `Union[int, str]` o `int | str` directos (ambos órdenes) usan el escalar estricto compartido `IntOrString`: enteros Int32, cadenas intactas, sin booleano como entero ni conversión cadena/número, y wrapper exterior opcional según declaración. Union envuelto en lista, otros Union, Literal no textual y otros mapas/conjuntos parametrizados siguen en String con aviso. Darles tipos requiere otra aprobación; la ausencia original de aviso queda acotada, no se elimina toda limitación.
**Pruebas representativas:** `tests/core/test_literal_string_enum_input.py`, `test_boolean_dict_json_input.py`, `test_recursive_input_lists.py`, `test_float_set_input.py`, `test_decimal_set_input.py` y `test_int_or_string_union_input.py`. Prueban formas aceptadas distintas, no todas las anotaciones.
**Comprobaciones con nombre:** `test_public_mutation_uses_literal_enum_and_raw_resolver_value`, `test_exact_boolean_map_uses_json_input`, `test_nested_list_nullability_and_singleton_coercion`, `test_typing_set_int_list_reaches_resolver_as_set`, `test_float_sets_publish_list_and_reach_resolver_as_set`, `test_decimal_sets_publish_list_and_reach_resolver_as_set` y `test_direct_union_publishes_shared_scalar` son definiciones actuales en los archivos citados. El apéndice completo de 189 rutas identifica su procedencia frente a la base.


### M-F1 — _is_pk_lookups decide por el nombre de la clave: un filtro anidado sobre un campo relacionado llamado year, month,…

**Estado:** bounded-fixed

**Problema original:** `_is_pk_lookups` decide por el nombre de la clave: un filtro anidado sobre un campo relacionado llamado `year`, `month`, `day`, `range`… revienta con `TypeError`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 138. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 230; la [tarea T11/T11d](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** lookup de parte de fecha relacionada y clave primaria. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"rows": [{"owner": "first", "target": {"code_pk": 1, "year": 2024, "exact": 7}}, {"owner": "second", "target": {"code_pk": 2, "year": 2023, "exact": 8}}], "nested_query": "{ owners(filter: { target: { year: { exact: 2024 } } }) { name } }", "direct_pk_query": "{ owners(filter: { target: { exact: 1 } }) { name } }"}
```

**Antes (ilustrativo):**
```json
{"direct_pk_query_names": [], "reason": "target__exact selected related exact column (7/8), not code PK (1/2)"}
```

**Después (observado/actual):**
```json
{"nested_query_names": ["first"], "direct_pk_query_names": ["first"], "direct_lookup_path": "target__pk__exact"}
```

**Cómo se llegó al resultado:**
1. La traducción de filtros anidados diferencia date-part relacionada del nombre de búsqueda de clave primaria. No mezcla cuestiones separadas de null e identidad to-many.
2. `954a2036b53a540e4db9829b6373eb66b2570474`: cambios de fuente en [django_graphex/filtering/translate.py](django_graphex/filtering/translate.py).
3. Límite comprobado: Se distinguieron rutas de date-part y PK relacionadas en los casos observados; nulabilidad y A12 siguen independientes.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_relation_lookup_name_collision.py](tests/test_relation_lookup_name_collision.py), `test_nested_lookup_name_and_direct_pk_exact` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert reverse_many is True
   ```
   - [tests/test_relation_lookup_name_collision.py](tests/test_relation_lookup_name_collision.py): `test_nested_lookup_name_and_direct_pk_exact` (definición añadida).


### M-F2 — Los lookups year, month, day, hour… se tipan como DateTime en vez de Int, así que son inutilizables

**Estado:** bounded-fixed

**Problema original:** Los lookups `year`, `month`, `day`, `hour`… se tipan como `DateTime` en vez de `Int`, así que son inutilizables. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 139. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 231; la [tarea T11/T11b](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** filtrar por componentes numéricos de Date/DateTime. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```graphql
# DateTime field createdAt, numeric date-part filter
{ posts(filters: {createdAt: {year: 2026}}) { results { id } } }
```

**Antes (ilustrativo):**
```json
{"SDL": "year: DateTime", "result": "integer literal rejected"}
```

**Después (observado/actual):**
```json
{"SDL": "year: Int", "result": "integer literal accepted"}
```

**Cómo se llegó al resultado:**
1. El constructor de filtros nativos identifica lookups numéricos de fecha y pasa GraphQLInt a _build_lookups_type, en vez de reutilizar _field_scalar(field). Año y mes admiten enteros; fechas completas Date/DateTime y TimeField conservan sus reglas de escalar.
2. `53b3481fff2eed6eb1a0a7d5ee07cd85f8f975e8`: cambios de fuente en [django_graphex/filtering/native_schema.py](django_graphex/filtering/native_schema.py).
3. Límite comprobado: Las partes numéricas de Date/DateTime usan GraphQL Int; el valor temporal completo y TimeField conservan sus escalares separados.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_datepart_filtering.py](tests/test_datepart_filtering.py), `test_numeric_date_parts_have_int_sdl_and_work_over_http` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert payload["data"][root_name] == [{"label": "match"}]
   ```
   - [tests/test_datepart_filtering.py](tests/test_datepart_filtering.py): `test_numeric_date_parts_have_int_sdl_and_work_over_http` (definición añadida); `test_lookup_type_boundaries_and_shared_inputs` (definición añadida).


### M-F3 — Semántica fail-open: exact:null elimina el filtro, not:{} y or:[] devuelven todo, y or:[{}, X] devuelve solo X

**Estado:** partial

**Problema original:** Semántica fail-open: `exact:null` elimina el filtro, `not:{}` y `or:[]` devuelven todo, y `or:[{}, X]` devuelve solo X. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 140. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 232; la [tarea T11/T11a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** comparar exact:null con omitir el predicado. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"filters": [{"exact": null}, {}]}
```

**Antes (ilustrativo):**
```json
{"branches": ["same", "same"]}
```

**Después (observado/actual):**
```json
{"branches": ["is-null", "omitted"], "empty_boolean": "unchanged"}
```

**Cómo se llegó al resultado:**
1. El traductor emite SQL IS NULL para exact:null explícito en vez de tratarlo como omisión. No se asigna en silencio otra identidad a ramas Boolean vacías.
2. `c4273e2b09624cfdd615e8f908abcb30ad2efb54`: cambios de fuente en [django_graphex/filtering/translate.py](django_graphex/filtering/translate.py).
3. Límite comprobado: Se diferenciaron exact:null y la omisión; identidades Boolean vacías requieren decisión distinta y no cambiaron.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_exact_null_filtering.py](tests/test_exact_null_filtering.py), `test_public_literal_exact_null_is_distinct_from_omission` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert _titles(path_name, explicit) == ["Django deep dive"]
   ```
   - [tests/test_exact_null_filtering.py](tests/test_exact_null_filtering.py): `test_public_literal_exact_null_is_distinct_from_omission` (definición añadida); `test_public_variable_exact_null_is_distinct_from_omission` (definición añadida); `test_native_coercion_preserves_lookup_presence` (definición añadida); `test_public_exact_null_composes_without_changing_empty_nodes` (definición añadida); `test_exact_null_field_matrix_and_json_sql_null` (definición añadida); `test_nullable_choice_and_text_exact_null` (definición añadida); `test_direct_relation_and_unset_lookup_boundaries` (definición añadida); `test_to_many_null_keeps_distinct_and_nested_prefix` (definición añadida).

**Límite pendiente:** Se diferenciaron exact:null y la omisión; identidades Boolean vacías requieren decisión distinta y no cambiaron.


### M-F4 — page: null provoca un TypeError crudo

**Estado:** bounded-fixed

**Problema original:** `page: null` provoca un `TypeError` crudo. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 141. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 233; la [tarea T12/T12c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** enviar page:null explícito. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"pagination": {"page": null, "size": 10}}
```

**Antes (ilustrativo):**
```json
{"page_path": "different from omission"}
```

**Después (observado/actual):**
```json
{"page_path": "first-page omission semantics"}
```

**Cómo se llegó al resultado:**
1. La paginación normaliza page:null a la ruta de primera página omitida antes de calcular offsets. No redefine cero ni páginas negativas.
2. `9ab95cb26b95af0fb2baae04c79108bdcbd1765f`: cambios de fuente en [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py).
3. Límite comprobado: page:null sigue la ruta de página omitida; cero y negativos mantienen su semántica existente.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_pagination_page_null_http.py](tests/test_pagination_page_null_http.py), `test_explicit_null_page_matches_omission_http` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert expected["totalCount"] == 5
   ```
   - [tests/test_pagination_page_null_http.py](tests/test_pagination_page_null_http.py): `test_explicit_null_page_matches_omission_http` (definición añadida); `test_existing_page_boundaries_http` (definición añadida); `test_omitted_nullable_variable_keeps_default_http` (definición añadida); `test_nested_null_page_reaches_materialized_list_without_optimizer` (definición añadida); `test_direct_page_null_normalizes_both_paths` (definición añadida).


### M-F5 — LimitOffset y Page no añaden pk como desempate: hay filas duplicadas o saltadas entre páginas en Postgres/MySQL

**Estado:** bounded-fixed

**Problema original:** LimitOffset y Page no añaden `pk` como desempate: hay filas duplicadas o saltadas entre páginas en Postgres/MySQL. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 142. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 234; la [tarea T12/T12f](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** paginar filas con igual valor de orden. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"rows": [{"id": 2, "score": 5}, {"id": 1, "score": 5}], "order": "score asc"}
```

**Antes (ilustrativo):**
```json
{"ids": [2, 1]}
```

**Después (observado/actual):**
```json
{"ids": [1, 2]}
```

**Cómo se llegó al resultado:**
1. En ordenación de modelo cubierta, la paginación añade la clave primaria ascendente para desempatar tras el orden efectivo del queryset. Orden aleatorio y offset son otros casos.
2. `f6e88d446f492324b5ec09f72c880c88842acb6d`: cambios de fuente en [django_graphex/fields.py](django_graphex/fields.py), [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py). Commits de seguimiento: `d1a6a18c167451546f8cf8bb4c91614cbd18c492`.
3. Límite comprobado: Se añade PK ascendente como desempate del modelo cubierto; orden aleatorio y offset mantienen reglas aparte.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_pagination_pk_tiebreak.py](tests/test_pagination_pk_tiebreak.py), `test_limit_offset_db_appends_pk_to_client_order` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert page.query.order_by == ("-title", "id")
   ```
   - [tests/test_pagination_pk_tiebreak.py](tests/test_pagination_pk_tiebreak.py): `test_limit_offset_db_appends_pk_to_client_order` (definición añadida); `test_page_db_appends_pk_to_client_order` (definición añadida); `test_materialized_model_list_uses_same_tie_break` (definición añadida); `test_explicit_descending_pk_is_not_overridden` (definición añadida); `test_explicit_id_inside_multiple_terms_is_not_duplicated` (definición añadida); `test_no_order_uses_pk_and_page_materialized_rows_match` (definición añadida); `test_queryset_default_and_explicit_order_are_preserved` (definición añadida); `test_queryset_expression_order_stays_ahead_of_pk` (definición añadida); `test_queryset_extra_ordering_stays_ahead_of_pk` (definición añadida); `test_col_pk_expression_is_not_duplicated` (definición añadida); `test_unbounded_no_order_preserves_original_queryset_cache` (definición añadida); `test_unbounded_no_order_retains_meta_ordering_without_a_clone` (definición añadida); `test_internal_pk_does_not_expand_client_ordering_allowlist` (definición añadida); `test_model_meta_ordering_survives_db_and_materialized_paths` (definición añadida); `test_unsupported_meta_list_ordering_keeps_pk_fallback` (definición añadida); `test_natural_pk_uses_field_name_not_id` (definición añadida); `test_natural_pk_alias_and_attname_keep_explicit_direction` (definición añadida); `test_reverse_fk_window_row_number_uses_pk_secondary` (definición añadida); `test_reverse_fk_window_keeps_model_meta_ordering` (definición añadida); `test_reverse_fk_window_keeps_hook_queryset_ordering` (definición añadida); `test_reverse_fk_window_keeps_extra_queryset_ordering` (definición añadida); `test_reverse_fk_window_falls_back_for_unsupported_hook_terms` (definición añadida); `test_nested_hidden_pk_is_internal_not_client_ordering` (definición añadida); `test_public_graphql_pages_cover_equal_name_rows_once` (definición añadida); `test_http_offset_pages_keep_equal_name_rows_disjoint` (definición añadida).


### M-F6 — _get_count hace fallback a len(qs) ante DatabaseError: un count() con timeout carga la tabla entera en memoria

**Estado:** bounded-fixed

**Problema original:** `_get_count` hace fallback a `len(qs)` ante `DatabaseError`: un `count()` con timeout carga la tabla entera en memoria. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 143. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 235; la [tarea T12/T12e](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** fallo de count() al pedir página negativa. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"page": -1, "queryset_count": "raises DatabaseError"}
```

**Antes (ilustrativo):**
```json
{"fallback": "iterate/materialize rows"}
```

**Después (observado/actual):**
```json
{"results": null, "error": "controlled GraphQLError"}
```

**Cómo se llegó al resultado:**
1. Si count() falla al calcular página negativa, se devuelve error GraphQL controlado en vez de materializar toda la colección. Los resultados quedan null.
2. `c75ea72fb0576fb86b1dbe829d6e4b3f42c93933`: cambios de fuente en [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py), [django_graphex/paginations/utils.py](django_graphex/paginations/utils.py).
3. Límite comprobado: Si falla count para página negativa, se devuelve GraphQLError controlado y results:null, sin iterar ni cargar toda la colección.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_negative_page_count_error_http.py](tests/test_negative_page_count_error_http.py), `test_failed_negative_page_count_is_generic_and_does_not_fetch_rows` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert not any('FROM "tests_post"' in item["sql"] for item in queries)
   ```
   - [tests/test_negative_page_count_error_http.py](tests/test_negative_page_count_error_http.py): `test_failed_negative_page_count_is_generic_and_does_not_fetch_rows` (definición añadida); `test_failed_count_does_not_use_length_or_iteration` (definición añadida); `test_list_fallback_and_unrelated_count_errors_are_unchanged` (definición añadida); `test_positive_page_does_not_attempt_count_when_not_selected` (definición añadida).


### M-F7 — PageGraphqlPagination sin page size da results: null con totalCount > 0

**Estado:** bounded-fixed

**Problema original:** `PageGraphqlPagination` sin page size da `results: null` con `totalCount > 0`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 144. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 236; la [tarea T12/T12d/T12g](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** omitir pageSize frente a page_size=None del servidor. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```graphql
{ pagePosts { totalCount results(ordering: "id") { id } } }
# 105 rows; no client pageSize; DEFAULT_PAGE_SIZE = 100.
```

**Antes (ilustrativo):**
```json
{"data": {"pagePosts": {"results": null, "totalCount": 105}}}
```

**Después (observado/actual):**
```json
{"selected_root": "pagePosts", "selected_item_shape": {"id": "<post pk>"}, "totalCount": 105, "first_page_result_count": 100, "second_page_result_count": 5}
```

**Cómo se llegó al resultado:**
1. El constructor hereda DEFAULT_PAGE_SIZE=100 al omitir page_size, de modo que un total positivo presenta una ventana concreta de resultados. PageGraphqlPagination(page_size=None, max_page_size=None) es otra cosa: una opción explícita de servidor que preserva el legado; pageSize:null del cliente resuelve al predeterminado configurado, no a ilimitado.
2. `5faeef718816e9e3fda12472f588da92ade02edf`: cambios de fuente en [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py), [django_graphex/settings.py](django_graphex/settings.py).
3. Límite comprobado: El tamaño omitido usa DEFAULT_PAGE_SIZE=100 y produce una ventana; page_size=None explícito en servidor conserva el legado y pageSize:null del cliente usa el predeterminado.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_default_page_size_http.py](tests/test_default_page_size_http.py), `test_omitted_size_uses_library_default_across_public_paginators` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert graphql_api_settings.DEFAULT_PAGE_SIZE == 100
   ```
   - [tests/test_default_page_size_http.py](tests/test_default_page_size_http.py): `test_omitted_size_uses_library_default_across_public_paginators` (definición añadida); `test_default_is_not_a_maximum_http` (definición añadida); `test_nested_omitted_size_uses_library_default_http` (definición añadida); `test_explicit_none_preserves_each_legacy_paginator_policy` (definición añadida); `test_startup_global_override_and_local_size_take_precedence` (definición añadida).


### M-H1 — Batching: un HttpError en la entrada N aborta todo el batch con un único 400, aunque las entradas anteriores ya se…

**Estado:** bounded-fixed

**Problema original:** Batching: un `HttpError` en la entrada N aborta todo el batch con un único 400, aunque las entradas anteriores ya se hayan commiteado. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 149. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 237; la [tarea T05/T13/T13h](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** segundo elemento de lote malformado tras uno válido. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"batch": ["valid query", "invalid second request"]}
```

**Antes (ilustrativo):**
```json
{"http_status": 400, "data": null}
```

**Después (observado/actual):**
```json
{"http_status": 400, "first_data": "retained", "second_error": "reported", "later_items": "not run"}
```

**Cómo se llegó al resultado:**
1. El lote conserva datos y errores de elementos previos al detenerse por uno posterior malformado con HTTP 400. No revierte escrituras ya duraderas.
2. `347b2ff7ac383bf791b795b6c51d9f825236ceeb`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: La respuesta 400 conserva datos y error anteriores y detiene el lote; escrituras ya realizadas no se vuelven transaccionales.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_batch_http_error_partial.py](tests/test_batch_http_error_partial.py), `test_later_http_400_keeps_prior_result_and_stops_batch` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert payload[1]["status"] == 400
   ```
   - [tests/test_batch_http_error_partial.py](tests/test_batch_http_error_partial.py): `test_later_http_400_keeps_prior_result_and_stops_batch` (definición añadida); `test_partial_response_does_not_depend_on_response_cache` (definición añadida); `test_non_400_http_error_keeps_existing_request_level_envelope` (definición añadida); `test_first_http_400_has_one_error_entry_and_no_invalidation` (definición añadida); `test_validation_error_continues_until_later_transport_error` (definición añadida); `test_outer_preflight_and_single_error_keep_existing_object_envelope` (definición añadida).


### M-H2 — Resolvers async en la vista síncrona: AttributeError: 'coroutine' object has no attribute 'errors', que acaba en…

**Estado:** bounded-fixed

**Problema original:** Resolvers `async` en la vista síncrona: `AttributeError: 'coroutine' object has no attribute 'errors'`, que acaba en 500. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 150. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 238; la [tarea T13/T13f](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** resolver async en vista HTTP síncrona. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"view": "synchronous", "resolver": "returns coroutine"}
```

**Antes (ilustrativo):**
```json
{"response": "uncontrolled coroutine path"}
```

**Después (observado/actual):**
```json
{"http_status": 500, "body": {"errors": ["controlled internal error"]}, "cleanup": "performed"}
```

**Cómo se llegó al resultado:**
1. La vista síncrona detecta ejecución async no soportada, cierra recursos coroutine anidados y devuelve JSON 500 controlado. No se convierte en endpoint HTTP async.
2. `23c06e0b6b7d86f2b082b86a50e4a6d715a3e78e`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py). Commits de seguimiento: `e8d0cf9eb5e40c03d9a1b2ee8fb3a9d42e63f3e6`, `dd1cf898dd94d01e44ff7672e764ea6807cf2f7b`.
3. Límite comprobado: La vista síncrona rechaza uso asíncrono con JSON 500 controlado y limpia recursos; no ofrece soporte async general.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_sync_async_http.py](tests/test_sync_async_http.py), `test_falsey_object_middleware_is_ignored_like_native` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert response.status_code == 200
   ```
   - [tests/test_sync_async_http.py](tests/test_sync_async_http.py): `test_falsey_object_middleware_is_ignored_like_native` (definición añadida); `test_callable_object_middleware_remains_active` (definición añadida); `test_async_resolver_returns_json_500_and_closes_owned_coroutines` (definición añadida); `test_sync_middleware_closes_nested_owned_resolver_coroutines` (definición añadida); `test_sync_middleware_keeps_borrowed_coroutine_open` (definición añadida); `test_async_middleware_is_rejected_without_running_its_body` (definición añadida); `test_custom_executor_owned_coroutine_is_closed` (definición añadida); `test_executor_exception_after_async_value_closes_owned_coroutine` (definición añadida); `test_async_mutation_is_rejected_with_transaction_policy` (definición añadida).


### M-H3 — CLEAN_RESPONSE=True elimina 0, False, "" y [], no solo null

**Estado:** bounded-fixed

**Problema original:** `CLEAN_RESPONSE=True` elimina `0`, `False`, `""` y `[]`, no solo `null`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 151. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 239; la [tarea T13/T13d](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** respuesta con cero o false. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"resolver_data": {"zero": 0, "flag": false}}
```

**Antes (ilustrativo):**
```json
{"response_data": {}}
```

**Después (observado/actual):**
```json
{"response_data": {"zero": 0, "flag": false}}
```

**Cómo se llegó al resultado:**
1. La limpieza de respuesta comprueba ausencia en vez de truthiness y conserva cero y false. La clasificación de introspección por fragmentos fue independiente.
2. `043811eefaec7c4662eb53672b994ec65f9ac545`: cambios de fuente en [django_graphex/utils.py](django_graphex/utils.py).
3. Límite comprobado: El limpiador conserva 0 y false; la clasificación de introspección con fragmentos fue una corrección diferente.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_clean_response_http.py](tests/test_clean_response_http.py), `test_selected_operation_controls_introspection_cleaning` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert normal["data"] == {"count": 0, "enabled": False}
   ```
   - [tests/test_clean_response_http.py](tests/test_clean_response_http.py): `test_clean_response_keeps_zero_false_and_nonempty_values` (definición añadida); `test_disabled_cleaning_leaves_the_full_payload_unchanged` (definición añadida); `test_selected_operation_controls_introspection_cleaning` (definición añadida).


### M-H4 — La caché de respuesta guarda también respuestas con errors (fallos transitorios cacheados 300 s)

**Estado:** partial

**Problema original:** La caché de respuesta guarda también respuestas con `errors` (fallos transitorios cacheados 300 s). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 152. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 240; la [tarea T13/T13e](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** respuesta GraphQL con errors y caché activa. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"GET_query": "{ unstable }", "first_result": {"errors": ["resolver failed"]}}
```

**Antes (ilustrativo):**
```json
{"cache_entry": "failed response"}
```

**Después (observado/actual):**
```json
{"cache_entry": null, "second_request": "re-executes"}
```

**Cómo se llegó al resultado:**
1. La inserción en caché exige respuesta GraphQL exitosa; un resultado con errores se devuelve pero no se guarda para aciertos posteriores.
2. `69d326eecee9c71ffe19db64e9019812297c74a1`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: Solo se cachean respuestas exitosas; las salvedades de seguridad finita y de lint histórico permanecen.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_success_response_cache.py](tests/test_success_response_cache.py), `test_partial_execution_error_recovers_then_success_hits` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert third.content == second.content
   ```
   - [tests/test_success_response_cache.py](tests/test_success_response_cache.py): `test_partial_execution_error_recovers_then_success_hits` (definición añadida); `test_validation_error_is_not_stored_or_reused` (definición añadida); `test_legacy_failed_entry_is_ignored_and_replaced` (definición añadida); `test_malformed_legacy_entry_is_ignored` (definición añadida); `test_disabled_cache_executes_without_response_cache_io` (definición añadida); `test_cookie_bearing_queries_bypass_response_cache` (definición añadida).

**Límite pendiente:** Solo se cachean respuestas exitosas; las salvedades de seguridad finita y de lint histórico permanecen.


### M-O1 — El optimizador raíz solo mira info.field_nodes[0]: si un campo raíz aparece también dentro de un fragmento, se…

**Estado:** bounded-fixed

**Problema original:** El optimizador raíz solo mira `info.field_nodes[0]`: si un campo raíz aparece también dentro de un fragmento, se ignora esa selección. Resultado: 16 queries frente a 1 (N+1 con colocation tipo Relay). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 157. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 241; la [tarea T14/T14b](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** varios FieldNode raíz fusionados seleccionan relaciones. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"rows": [1, 2, 3], "selection": "related author under merged alias"}
```

**Antes (ilustrativo):**
```json
{"relation_fetches": 3}
```

**Después (observado/actual):**
```json
{"relation_fetches": "one covered batch"}
```

**Cómo se llegó al resultado:**
1. El optimizador fusiona selecciones FieldNode raíz de una misma respuesta antes de reunir prefetches. Evita el N+1 ejercitado sin prometer consultas constantes para todo ORM.
2. `316844e376f9585f873903a60d73eb25a39aeb58`: cambios de fuente en [django_graphex/utils.py](django_graphex/utils.py).
3. Límite comprobado: La planificación agrupa nodos raíz fusionados en el caso probado; no convierte todos los patrones ORM en una garantía de consultas constantes.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   - [tests/test_optimizer_merged_field_nodes.py](tests/test_optimizer_merged_field_nodes.py): `test_direct_and_fragment_root_fields_share_relation_and_column_plan` (definición añadida); `test_second_root_node_promotes_annotated_relation` (definición añadida).


### M-O2 — La caché de firmas de permisos toma el mismo RLock global durante prune_fn: un hit espera ~0,9 s a que otra firma…

**Estado:** bounded-fixed

**Problema original:** La caché de firmas de permisos toma el mismo `RLock` global durante `prune_fn`: un hit espera ~0,9 s a que otra firma termine de construirse. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 158. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 242; la [tarea T14/T14c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** acierto caliente de caché mientras se calcula otra firma fría. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"cache": "warm permission signature", "other_thread": "cold signature fill"}
```

**Antes (ilustrativo):**
```json
{"warm_hit": "waits on global cold-fill lock"}
```

**Después (observado/actual):**
```json
{"warm_hit": "served without cold-fill wait"}
```

**Cómo se llegó al resultado:**
1. La caché de firma de permisos atiende claves calientes fuera del bloqueo de otra firma fría. La poda fría sigue siendo por firma y sensible a permisos.
2. `961c018e2d089962679c65329ebdb6bff765ba26`: cambios de fuente en [django_graphex/core/permission_signature_cache.py](django_graphex/core/permission_signature_cache.py).
3. Límite comprobado: Los aciertos calientes pueden servirse mientras se llena otra firma fría; no se afirma una garantía general de concurrencia.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_permission_cache_lock_split.py](tests/test_permission_cache_lock_split.py), `test_warm_hit_completes_before_unrelated_cold_prune_is_released` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert results[0] is cached_b
   ```
   - [tests/test_permission_cache_lock_split.py](tests/test_permission_cache_lock_split.py): `test_warm_hit_completes_before_unrelated_cold_prune_is_released` (definición añadida); `test_cold_builds_remain_serial_and_same_key_is_shared` (definición añadida); `test_clear_waits_for_build_then_removes_entry` (definición añadida); `test_reentrant_clear_and_failed_prune_leave_cache_recoverable` (definición añadida).


### M-U1 — Un complete o desconexión durante start() deja la suscripción en el grupo (suscriptor fantasma)

**Estado:** partial

**Problema original:** Un `complete` o desconexión durante `start()` deja la suscripción en el grupo (suscriptor fantasma). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 163. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 243; la [tarea T08/R01b](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** cancelación de arranque ASGI después de unirse al grupo. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"startup": "cancel after WS group join", "operation_id": "op1"}
```

**Antes (ilustrativo):**
```json
{"group_membership": "stale", "retry": "blocked"}
```

**Después (observado/actual):**
```json
{"group_membership": "removed", "retry": "admitted"}
```

**Cómo se llegó al resultado:**
1. La cancelación de arranque ASGI libera grupo y slot antes de reintentar con la misma fuente. Es limpieza local, no garantía de lease distribuido.
2. `fe545832513244bdddf2d35cea4cc845fc34cad9`: cambios de fuente en [django_graphex/subscriptions/source.py](django_graphex/subscriptions/source.py). Commits de seguimiento: `514def143c42d6dad082e4590fb9edce813c90d6`.
3. Límite comprobado: El arranque ASGI libera el grupo tras la cancelación antes de devolver; la limpieza distribuida sigue siendo de mejor esfuerzo.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_startup_cleanup.py](tests/subscriptions/test_startup_cleanup.py), `test_client_complete_during_real_join_discards_membership` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert not layer.groups
   ```
   - [tests/subscriptions/test_startup_cleanup.py](tests/subscriptions/test_startup_cleanup.py): `test_client_complete_during_real_join_discards_membership` (definición añadida); `test_disconnect_during_real_join_discards_membership` (definición añadida); `test_sse_cancel_during_real_join_discards_membership` (definición añadida); `test_failed_second_join_discards_only_its_memberships` (definición añadida); `test_failure_before_backend_join_preserves_original_error` (definición añadida); `test_cleanup_failure_does_not_replace_startup_failure` (definición añadida); `test_same_source_retry_after_failed_join_delivers_and_cleans_up` (definición añadida); `test_explicit_close_after_failed_join_stays_closed` (definición añadida).

**Límite pendiente:** El arranque ASGI libera el grupo tras la cancelación antes de devolver; la limpieza distribuida sigue siendo de mejor esfuerzo.


### M-U2 — Los eventos delete se descartan si hay scope o filtros no-pk en modo id_only (por defecto): la comprobación…

**Estado:** partial

**Problema original:** Los eventos `delete` se descartan si hay scope o filtros no-pk en modo `id_only` (por defecto): la comprobación `exists()` corre cuando la fila ya no existe. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 164. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 244; la [tarea T08](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** delete automático con solo ID después del commit. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"deleted_row": {"pk": 7, "tenant": "A"}, "filter": {"tenant": "A"}}
```

**Antes (ilustrativo):**
```json
{"event": null}
```

**Después (observado/actual):**
```json
{"event": {"pk": 7}, "wrong_tenant_event": null}
```

**Cómo se llegó al resultado:**
1. La señal automática de borrado captura antes de eliminar la fila los escalares privados concretos, proyectados y ya cargados. Tras commit, igualdad y scope de servidor usan esa instantánea confiable y pueden emitir solo PK; escalares ausentes/diferidos/no proyectados, relaciones solo-ID, backends personalizados y filtros lookup siguen conservadores. No se confía por ello en payloads externos arbitrarios.
2. `1ee78e2548dcb7fc4d466a1c702f1ae9e060671d`: cambios de fuente en [django_graphex/subscriptions/bindings.py](django_graphex/subscriptions/bindings.py), [django_graphex/subscriptions/source.py](django_graphex/subscriptions/source.py), [django_graphex/subscriptions/subscription.py](django_graphex/subscriptions/subscription.py).
3. Límite comprobado: La señal captura escalares concretos privados al borrar, suficientes para igualdad y scope aprobados; no convierte un evento externo genérico en dato confiable.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_delete_snapshot_matching.py](tests/subscriptions/test_delete_snapshot_matching.py), `test_private_capture_excludes_relations_containers_nonfinite_and_custom_backend` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert ProjectedSubscription._serialize_delete_match(instance) == {}
   ```
   - [tests/subscriptions/test_delete_snapshot_matching.py](tests/subscriptions/test_delete_snapshot_matching.py): `test_private_capture_excludes_relations_containers_nonfinite_and_custom_backend` (definición añadida); `test_real_delete_uses_signal_time_projected_equality` (definición añadida); `test_missing_or_malformed_private_delete_snapshot_fails_closed` (definición añadida); `test_private_delete_equality_preserves_typed_scalar_contract` (definición añadida).

**Por qué coincide un borrado solo-ID:** La fila borrada ya no puede recargarse tras commit. Por ello la señal automática guarda **solo escalares privados concretos, proyectados y ya cargados** antes de borrar. Para `{pk: 7, tenant: "A"}`, el filtro de igualdad `tenant: "A"` puede coincidir y el dato publicado seguir siendo `{"pk": 7}`; `tenant: "B"` no coincide. Un `tenant` diferido, ausente o no proyectado no se adivina desde el PK. IDs de relación solos y predicados lookup, backends personalizados y payloads externos de broadcast quedan fuera de esta confianza. Véase `tests/subscriptions/test_delete_snapshot_matching.py`.

**Límite pendiente:** La señal captura escalares concretos privados al borrar, suficientes para igualdad y scope aprobados; no convierte un evento externo genérico en dato confiable.


### M-U3 — Los filtros en memoria comparan con str(): Decimal, DateTime y Float nunca coinciden

**Estado:** partial

**Problema original:** Los filtros en memoria comparan con `str()`: Decimal, DateTime y Float nunca coinciden. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 165. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 245; la [tarea T08/R02](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** comparar instantáneas finitas Decimal, DateTime y Float. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"event_decimal": "1.00", "filter_decimal": "1.0", "float_values": [-0.0, 0.0]}
```

**Antes (ilustrativo):**
```json
{"match": false}
```

**Después (observado/actual):**
```json
{"finite_match": true, "non_finite_policy": "unchanged"}
```

**Cómo se llegó al resultado:**
1. La comparación de suscripciones normaliza por rutas distintas Decimal finito, DateTime nativo exacto y Float finito, incluido cero con signo. No reescribe tipos mixtos ni no finitos globalmente.
2. `c664db3fe7d727e073de7725564a9cbe8a49e0fa`: cambios de fuente en [django_graphex/subscriptions/mixins.py](django_graphex/subscriptions/mixins.py). Commits de seguimiento: `6df731e0d01b67997bf2fa6de457c372f4a33855`, `33ff8786e03901ef1ca9bf0e7f34c82ab2b0a0b5`.
3. Límite comprobado: Se corrigieron por separado Decimal finito, DateTime nativo exacto y Float finito (incluido ±0); tipos mixtos y no finitos conservan límites.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_float_snapshot_filter.py](tests/subscriptions/test_float_snapshot_filter.py), `test_real_float_field_exact_event` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert type(parsed_filters[0]["floating"]) is float
   ```
   - [tests/subscriptions/test_float_snapshot_filter.py](tests/subscriptions/test_float_snapshot_filter.py): `test_real_float_field_exact_event` (definición añadida); `test_float_pair_only_changes_finite_exact_equality` (definición añadida).

**Límite pendiente:** Se corrigieron por separado Decimal finito, DateTime nativo exacto y Float finito (incluido ±0); tipos mixtos y no finitos conservan límites.


### M-U4 — No hay m2m_changed, y bulk_/QuerySet.update no emiten eventos (sin documentar)

**Estado:** contract

**Problema original:** No hay `m2m_changed`, y `bulk_*`/`QuerySet.update` no emiten eventos (sin documentar). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 166. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 246; la [tarea T08](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** señal automática frente a broadcast manual y operación bulk. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"all assumed commit-time automatic"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"model save after commit; bulk none; manual immediate"
```

**Cómo se llegó al resultado:**
1. Las señales post-save/delete programan envío automático tras commit; bulk no emite señal y broadcast manual sigue inmediato. Son límites documentados, no implementación cambiada.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Las señales post_save/post_delete programan envío tras commit; bulk/update no emiten señales y broadcast manual es inmediato. No cambio de contrato.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### M-U5 — Una directiva sobre un resolver async devuelve "<COROUTINE OBJECT …>"

**Estado:** bounded-fixed

**Problema original:** Una directiva sobre un resolver `async` devuelve `"<COROUTINE OBJECT …>"`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 167. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 247; la [tarea T15/R03a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** directiva async recibe resolver pendiente o Future prestado. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"resolver_value": "borrowed Future[str]", "directive": "@uppercase"}
```

**Antes (ilustrativo):**
```json
{"formatter_input": "Future object", "cancellation": "may propagate to borrowed future"}
```

**Después (observado/actual):**
```json
{"formatter_input": "awaited string", "borrowed_future_cancelled": false}
```

**Cómo se llegó al resultado:**
1. El middleware async espera la salida del resolver antes de formatear y no cancela un Future ajeno. HTTP síncrono sigue rechazando async por otra ruta.
2. `ace6638e65f70843d123263f7ea09b7c780a595b`: cambios de fuente en [django_graphex/middleware.py](django_graphex/middleware.py). Commits de seguimiento: `031299c46e3127c080a3554f0c708b01147ad7a2`.
3. Límite comprobado: El formateador asíncrono espera el valor y conserva Futures prestados; HTTP síncrono sigue rechazando async con JSON 500.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_async_directive_middleware.py](tests/test_async_directive_middleware.py), `test_native_async_execution_applies_directive_after_await` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert started == ["resolver"]
   ```
   - [tests/test_async_directive_middleware.py](tests/test_async_directive_middleware.py): `test_native_async_execution_applies_directive_after_await` (definición añadida); `test_sync_http_rejects_async_resolver_with_directive` (definición añadida); `test_sync_http_preserves_borrowed_future_with_directive` (definición añadida); `test_synchronous_directive_behavior_is_unchanged` (definición añadida); `test_http_outer_wrapper_does_not_leak_directive_coroutine` (definición añadida).


### M-U6 — @date sobre None no devuelve null; @date no aplica localtime; una fecha sin hora se rellena con la hora actual;…

**Estado:** partial

**Problema original:** `@date` sobre `None` no devuelve `null`; `@date` no aplica `localtime`; una fecha sin hora se rellena con la hora actual; `@snake_case`/`@kebab_case`/`@camel_case` fallan con camelCase; `@number`/`@currency` convierten `None` en `0`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 168. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 248; la [tarea T15](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** @date con null, texto naive, offset y variantes de mayúsculas. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```graphql
{ dateValue @date(format: "yyyy-MM-dd HH:mm") numberValue @number }
# Nullable resolver values are None; separate text-date and case examples follow below.
```

**Antes (ilustrativo):**
```json
{"null_result": "formatting error", "case": "inconsistent"}
```

**Después (observado/actual):**
```json
{"null_result": null, "date_clock": "00:00:00", "camel": "httpServer", "snake": "http_server", "kebab": "http-server"}
```

**Cómo se llegó al resultado:**
1. La cadena de directivas conserva None nullable en @date, @number y @currency, mientras GraphQL NonNull propaga el error. Texto solo-fecha/hora parcial rellena componentes ausentes con cero; valores aware o con offset/Z conservan el instante al mostrarse en zona activa, mientras texto sin zona adjunta la zona activa a su hora escrita independientemente de USE_TZ. El formato relativo puede cambiar; zonas nombradas/desconocidas quedan limitadas. Las tres directivas de caso manejan palabras y bloques de acrónimos aprobados (HTTPServer -> httpServer/http_server/http-server) sin renombrar campos SDL ni helpers compartidos.
2. `1f97d24d06309309601e029eb21766dcd1da6e67`: cambios de fuente en [django_graphex/directives/date.py](django_graphex/directives/date.py). Commits de seguimiento: `35199aa09a2ce3331456accb72348171cb9b98e5`, `dc556059c5c06e5d21bcf63388535901ffe3979a`.
3. Límite comprobado: Se corrigieron límites concretos de null en date/number/currency, texto de fecha y zona activa, y formas de palabras/acrónimos en directivas de caso; parseo DateTime nativo y otros formatos siguen aparte.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_directive_date_null.py](tests/test_directive_date_null.py), `test_nullable_date_field_stays_null` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert next(iter(result.data.values())) is None
   ```
   - [tests/test_directive_date_null.py](tests/test_directive_date_null.py): `test_date_only_value_still_uses_existing_formatting` (definición añadida); `test_date_resolver_none_is_not_a_format_wrapper` (definición añadida); `test_invalid_non_null_value_keeps_fallback` (definición añadida); `test_nullable_date_field_stays_null` (definición añadida); `test_required_nested_date_bubbles_only_to_nullable_parent` (definición añadida); `test_required_root_date_uses_normal_non_null_error` (definición añadida); `test_valid_datetime_still_formats` (definición añadida).
   - [tests/test_directive_date_text_time.py](tests/test_directive_date_text_time.py): `test_parser_zeros_microseconds_without_changing_explicit_or_nontext_values` (definición añadida); `test_text_default_preserves_active_timezone_with_use_tz_false` (definición añadida); `test_text_time_components_are_zero_in_native_graphql` (definición añadida); `test_text_time_only_keeps_current_date_across_days` (definición añadida).
   - [tests/test_directive_date_timezone.py](tests/test_directive_date_timezone.py): `test_absolute_formats_localize_only_explicit_instants` (definición añadida); `test_active_zone_applies_to_aware_instants_with_use_tz_false` (definición añadida); `test_adjacent_zero_offset_relative_formats_keep_instant` (definición añadida); `test_clock_adjacent_zero_offsets_match_z_absolute_zone` (definición añadida); `test_dst_conversion_uses_each_instants_active_offset` (definición añadida); `test_explicit_offset_before_accepted_abbreviation_is_localized` (definición añadida); `test_explicit_offset_before_trailing_year_is_localized` (definición añadida); `test_invalid_offset_text_keeps_string_fallback` (definición añadida); `test_naive_text_and_typed_inputs_keep_existing_wall_clock` (definición añadida); `test_parser_accepted_adjacent_zero_spellings_are_explicit` (definición añadida); `test_public_helpers_and_other_input_kinds_are_unchanged` (definición añadida); `test_relative_formats_keep_current_path` (definición añadida).
   - [tests/test_directive_date_naive_timezone.py](tests/test_directive_date_naive_timezone.py): `test_missing_components_keep_the_parser_default_across_midnight` (definición añadida); `test_named_unknown_and_numeric_offset_text_keep_previous_paths` (definición añadida); `test_original_explicit_offset_helper_retains_its_boolean_contract` (definición añadida); `test_timezone_less_summer_text_uses_each_active_zone` (definición añadida); `test_timezone_less_text_uses_active_zone_for_absolute_and_relative_formats` (definición añadida).

**Ejemplos por límite de directiva:** `@date`, `@number` y `@currency` nullable devuelven null para entrada null; un campo GraphQL NonNull sigue propagando. `"2026-01-10"` pasa a medianoche, y `"2026-01-10 14:30"` completa segundos/microsegundos con cero; el texto solo-hora conserva la política de fecha actual del parser. Para salida absoluta, `2026-01-10T23:30:00+00:00` puede mostrar **el día siguiente** en zona activa +02:00 conservando el instante; `"2026-01-10 14:30"` sin zona asocia la zona activa a su hora escrita incluso con `USE_TZ=False`. La frase relativa puede variar por la zona de referencia. Los offsets equivalentes `Z`, `+00:00` y `+0000` se reconocen en el camino cubierto; zonas nombradas/desconocidas siguen pendientes. Las directivas de caso convierten `orderTotal` en `order_total`/`order-total` y `HTTPServer` en `httpServer`/`http_server`/`http-server`; no renombran campos SDL. Preservar null en number/currency no elimina validación de formato ni topes de salida. Parsear el escalar DateTime nativo es otro contrato. Pruebas representativas: `tests/test_directive_date_text_time.py`, `test_directive_date_timezone.py`, `test_directive_date_naive_timezone.py` y `test_directive_date_null.py`.

**Límite pendiente:** Se corrigieron límites concretos de null en date/number/currency, texto de fecha y zona activa, y formas de palabras/acrónimos en directivas de caso; parseo DateTime nativo y otros formatos siguen aparte.


### M-T1 — _forking_depth es un global de módulo, no threading.local/ContextVar. Construir un schema forked en un hilo hace…

**Estado:** bounded-fixed

**Problema original:** `_forking_depth` es un global de módulo, no `threading.local`/`ContextVar`. Construir un schema forked en un hilo hace que otros hilos se salten el registro, y la entrada sintetizada pierde `only_fields`/`exclude_fields`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 173. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 249; la [tarea T14d/T14](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** fork de esquema en un hilo mientras otro construye esquema normal. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"thread_A": "schema fork depth 1", "thread_B": "ordinary compilation"}
```

**Antes (ilustrativo):**
```json
{"thread_B_depth": 1}
```

**Después (observado/actual):**
```json
{"thread_B_depth": 0}
```

**Cómo se llegó al resultado:**
1. La profundidad de registro de fork pasó de estado compartido a contexto por hilo. Un esquema ordinario concurrente no hereda el marcador de otro hilo.
2. `4df64c4ff7dadb0c61b82fb72324f72179af4fc0`: cambios de fuente en [django_graphex/core/base.py](django_graphex/core/base.py), [django_graphex/schema.py](django_graphex/schema.py).
3. Límite comprobado: Se aisló el marcador de profundidad por hilo; las carreras del registro y caché de enums se tratan aparte.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_schema_fork_threads.py](tests/core/test_schema_fork_threads.py), `test_concurrent_fork_preserves_sibling_output_projections` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert str(types["MT1AuthorList"].fields["results"].type) == "[MT1AuthorOnly]"
   ```
   - [tests/core/test_schema_fork_threads.py](tests/core/test_schema_fork_threads.py): `test_concurrent_fork_preserves_sibling_output_projections` (definición añadida); `test_serial_projected_list_keeps_its_node_type` (definición añadida); `test_fork_marker_is_nested_and_restored_after_error` (definición añadida).


### L-C1 — get_node/retrieve/DjangoObjectField con id malformado ("abc") dan error crudo en vez de null. Reusar…

**Estado:** bounded-fixed

**Problema original:** `get_node`/`retrieve`/`DjangoObjectField` con id malformado (`"abc"`) dan error crudo en vez de `null`. Reusar `get_Object_or_None` (`types.py:1496`, `:3640`; `fields.py:195`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 180. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 250; la [tarea T15/R04a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** ID malformado frente a ID bien formado ausente u oculto. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"node_id": "abc", "model_pk": "integer"}
```

**Antes (ilustrativo):**
```json
{"exception": "raw conversion error"}
```

**Después (observado/actual):**
```json
{"errors": [{"code": "INVALID_ID"}]}
```

**Cómo se llegó al resultado:**
1. La coerción de ID distingue valor malformado de fila bien formada ausente u oculta; el primero devuelve INVALID_ID seguro y la segunda null.
2. `0512657622e64c731db94a699693999865c34703`: cambios de fuente en [django_graphex/fields.py](django_graphex/fields.py), [django_graphex/types.py](django_graphex/types.py), [django_graphex/utils.py](django_graphex/utils.py).
3. Límite comprobado: Los ID malformados devuelven INVALID_ID con formato seguro; ID bien formados ausentes u ocultos devuelven null sin ese error.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_invalid_id_contract.py](tests/test_invalid_id_contract.py), `test_malformed_integer_id_has_safe_public_error` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data == {"article": None}
   ```
   - [tests/test_invalid_id_contract.py](tests/test_invalid_id_contract.py): `test_malformed_integer_id_has_safe_public_error` (definición añadida); `test_malformed_uuid_id_has_safe_public_error` (definición añadida); `test_get_node_rejects_malformed_integer_id` (definición añadida); `test_malformed_id_in_generated_retrieve_field` (definición añadida); `test_valid_missing_and_char_primary_keys_keep_orm_meaning` (definición añadida); `test_hidden_row_still_looks_missing` (definición añadida); `test_unrelated_queryset_errors_are_not_relabelled` (definición añadida); `test_custom_primary_key_prepared_once_with_generic_error` (definición añadida); `test_custom_primary_key_renamed_argument_keeps_safe_public_error` (definición añadida); `test_http_production_wire_keeps_deliberate_error` (definición añadida); `test_existing_numeric_and_null_coercion_remain_orm_owned` (definición añadida); `test_non_null_field_bubbles_the_deliberate_error` (definición añadida); `test_uuid_missing_and_valid_ids_keep_lookup_behavior` (definición añadida); `test_retrieve_authorization_error_precedes_id_conversion` (definición añadida); `test_existing_missing_exception_boundary_in_hooks_is_preserved` (definición añadida).


### L-C2 — assert usados como guards de configuración, que python -O elimina (types.py:1173)

**Estado:** bounded-fixed

**Problema original:** `assert` usados como guards de configuración, que `python -O` elimina (`types.py:1173`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 181. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 251; la [tarea T14/T14a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** constructor de vista inválido ejecutado con python -O. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"runtime": "python -O", "constructor": "invalid schema or conflicting mode"}
```

**Antes (ilustrativo):**
```json
{"assertion": "optimized away", "accepted": true}
```

**Después (observado/actual):**
```json
{"error": "explicit AssertionError", "accepted": false}
```

**Cómo se llegó al resultado:**
1. Dos precondiciones de constructor pasaron de assert a excepciones explícitas, de modo que python -O no las elimina. No se auditó todo guardia.
2. `9fec11da77a76f697ff6365a6c0bc5ed6c33f4d7`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: Dos validaciones de constructor sobreviven a python -O; no se infiere validación universal.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_view_base.py](tests/test_view_base.py), `test_view_constructor_does_not_use_optimized_away_validation` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert not any(isinstance(node, ast.Assert) for node in ast.walk(constructor))
   ```
   - [tests/test_view_base.py](tests/test_view_base.py): `test_view_constructor_rejects_invalid_schema` (definición añadida); `test_view_constructor_rejects_conflicting_modes` (definición añadida); `test_view_constructor_does_not_use_optimized_away_validation` (definición añadida).
**Corrección del localizador heredado:** La guía cita `tests/test_settings_boundary_values.py`, que prueba settings, no las dos guardas del constructor de vista. Los tests causales de `9fec11d` están en `tests/test_view_base.py`; la cita anterior solo documenta la procedencia de la guía.


### L-C3 — Divergencia de status entre GraphQLView y BaseGraphQLView, y falta data: null (views.py:2204 frente a :1066)

**Estado:** bounded-fixed

**Problema original:** Divergencia de status entre `GraphQLView` y `BaseGraphQLView`, y falta `data: null` (`views.py:2204` frente a `:1066`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 182. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 252; la [tarea T13/R04b](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** error de ejecución en raíz no nula. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"query": "{ requiredRoot }", "resolver": "raises"}
```

**Antes (ilustrativo):**
```json
{"http_status": 400, "data": "omitted"}
```

**Después (observado/actual):**
```json
{"http_status": 200, "data": null, "errors": ["resolver failed"]}
```

**Cómo se llegó al resultado:**
1. Las vistas mejorada y base conservan data:null y errors bajo HTTP 200 en fallo de raíz no nula. Parseo y validación mantienen HTTP 400 sin data.
2. `276841a9f9ff1796153c6ca52194f20866067373`: cambios de fuente en [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: Ambas vistas devuelven HTTP 200 con data:null y errors en ejecución; sintaxis y validación siguen HTTP 400 sin data.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_http_execution_error_contract.py](tests/test_http_execution_error_contract.py), `test_nonnull_root_execution_error_has_null_data_in_both_views` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert payload["errors"][0]["path"] == ["required"]
   ```
   - [tests/test_http_execution_error_contract.py](tests/test_http_execution_error_contract.py): `test_nonnull_root_execution_error_has_null_data_in_both_views` (definición añadida); `test_null_execution_envelope_survives_cleaning_and_production_formatting` (definición añadida); `test_request_errors_stay_http_400_without_data` (definición añadida); `test_nullable_error_and_success_keep_existing_data_and_cost` (definición añadida); `test_null_execution_errors_are_not_cached_or_replayed` (definición añadida); `test_batch_execution_error_continues_and_validation_error_remains_scoped` (definición añadida); `test_multipart_form_uses_same_execution_envelope` (definición añadida).


### L-C4 — Los archivos multipart no aplican MAX_UPLOAD_SIZE (uploads.py:350-434)

**Estado:** bounded-fixed

**Problema original:** Los archivos multipart no aplican `MAX_UPLOAD_SIZE` (`uploads.py:350-434`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 183. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 253; la [tarea T13/R04c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** archivo multipart grande aunque no esté mapeado a operations. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"upload_bytes": 4, "configured_cap_bytes": 3, "upload_referenced": false}
```

**Antes (ilustrativo):**
```json
{"resolver_calls": 1}
```

**Después (observado/actual):**
```json
{"http_status": 413, "resolver_calls": 0}
```

**Cómo se llegó al resultado:**
1. El parseo multipart mide cada archivo recibido frente a MAX_UPLOAD_SIZE antes de mapearlo a operations, también repetidos o no usados. Otras codificaciones no quedan cubiertas.
2. `dfb47a0078466b96eb59d9ccba150639db08e225`: cambios de fuente en [django_graphex/settings.py](django_graphex/settings.py), [django_graphex/views.py](django_graphex/views.py).
3. Límite comprobado: Cada archivo multipart recibido se limita, incluso repetido o no usado, antes del resolver; None/Base64/límites del cuerpo siguen aparte.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_multipart_file_size_http.py](tests/test_multipart_file_size_http.py), `test_oversized_multipart_file_is_rejected_before_resolver` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert "MAX_UPLOAD_SIZE" in payload["errors"][0]["message"]
   ```
   - [tests/test_multipart_file_size_http.py](tests/test_multipart_file_size_http.py): `test_oversized_multipart_file_is_rejected_before_resolver` (definición añadida); `test_single_file_boundary_and_uncapped_mode` (definición añadida); `test_every_repeated_file_is_checked` (definición añadida); `test_multiple_files_are_not_summed` (definición añadida); `test_malformed_multipart_batch_keeps_400_before_file_cap` (definición añadida); `test_graphiql_success_path_still_checks_files` (definición añadida); `test_cache_active_multipart_cannot_bypass_file_cap` (definición añadida); `test_independent_total_body_cap_still_rejects_first` (definición añadida); `test_temporary_uploaded_file_is_rejected_and_closed` (definición añadida); `test_csrf_header_refusal_precedes_file_cap` (definición añadida); `test_oversized_file_prevents_mutation_resolver` (definición añadida).


### L-C5 — LIMIT_MINIMUMS no valida MAX_BATCH_SIZE, MAX_REQUEST_BODY_SIZE ni DOCUMENT_CACHE_MAXSIZE

**Estado:** bounded-fixed

**Problema original:** `LIMIT_MINIMUMS` no valida `MAX_BATCH_SIZE`, `MAX_REQUEST_BODY_SIZE` ni `DOCUMENT_CACHE_MAXSIZE`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 184. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 254; la [tarea T13/R04d](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** ajuste de límite mínimo cero recibe valor negativo. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"setting": "MAX_BATCH_SIZE", "value": -1}
```

**Antes (ilustrativo):**
```json
{"startup": "accepted invalid value"}
```

**Después (observado/actual):**
```json
{"error": "ImproperlyConfigured: minimum 0"}
```

**Cómo se llegó al resultado:**
1. La lectura de settings rechaza enteros negativos en MAX_BATCH_SIZE, MAX_REQUEST_BODY_SIZE y DOCUMENT_CACHE_MAXSIZE. Cero y None conservan su significado.
2. `9760b29773e3f62e9afebe7ac878779398878256`: cambios de fuente en [django_graphex/settings.py](django_graphex/settings.py).
3. Límite comprobado: MAX_BATCH_SIZE, MAX_REQUEST_BODY_SIZE y DOCUMENT_CACHE_MAXSIZE rechazan enteros negativos al leerse; cero y None conservan contratos.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_settings_minimum_zero.py](tests/test_settings_minimum_zero.py), `test_negative_integer_limit_fails_on_public_setting_read` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert remedy in message
   ```
   - [tests/test_settings_minimum_zero.py](tests/test_settings_minimum_zero.py): `test_negative_integer_limit_fails_on_public_setting_read` (definición añadida); `test_approved_boundary_values_are_retained` (definición añadida); `test_default_is_unchanged` (definición añadida); `test_existing_nonnegative_bool_and_noninteger_policy_is_unchanged` (definición añadida); `test_negative_limit_is_validated_lazily` (definición añadida).


### L-C6 — ensure_csrf_cookie hace que, tras la primera petición, los navegadores nunca usen la caché (views.py:788, :1651)

**Estado:** contract

**Problema original:** `ensure_csrf_cookie` hace que, tras la primera petición, los navegadores nunca usen la caché (`views.py:788`, `:1651`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 185. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 255; la [tarea T13/R04e](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** miss de caché sin cookie, hit y posterior petición con cookie. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"all paths assumed to set cookie"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"miss may set cookie; hit does not; cookie-bearing request bypasses"
```

**Cómo se llegó al resultado:**
1. Se documentó la traza cookie/caché sin parche: un miss sin cookie puede fijar csrftoken, un hit sin cookie retorna antes y la petición posterior con cookie omite la caché de respuesta.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Un miss sin cookie puede fijar csrftoken; un hit sin cookie retorna antes y no crea cookie. Una petición posterior con cookie omite la caché del servidor; no hay prueba de reutilización del navegador.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_views_cache_cookie_bypass.py](tests/test_views_cache_cookie_bypass.py), `test_issued_csrf_cookie_bypasses_next_server_cache_lookup` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert second.status_code == 200
   ```
   - [tests/test_views_cache_cookie_bypass.py](tests/test_views_cache_cookie_bypass.py): `test_cookie_dependent_anonymous_queries_are_not_shared` (definición sin cambios); `test_default_hook_rejects_cookie_bearing_queries` (definición sin cambios); `test_default_hook_allows_cookie_free_queries` (definición sin cambios); `test_cookie_bearing_mutation_still_invalidates` (definición sin cambios); `test_issued_csrf_cookie_bypasses_next_server_cache_lookup` (definición añadida).


### L-C7 — Los sufijos posicionales en enums de choices (A_B_1) cambian de nombre al reordenar las choices…

**Estado:** bounded-fixed

**Problema original:** Los sufijos posicionales en enums de choices (`A_B_1`) cambian de nombre al reordenar las choices (`converter.py:207-240`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 186. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 256; la [tarea T06e/T06](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** choices generan nombre de miembro enum ambiguo. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"enum_choices": [["1", "A B"], ["2", "A_B"]], "normalized_name": "A_B"}
```

**Antes (ilustrativo):**
```json
{"members": ["A_B", "A_B_1"]}
```

**Después (observado/actual):**
```json
{"error": "choice name collision"}
```

**Cómo se llegó al resultado:**
1. La construcción de enum rechaza nombres de miembro ambiguos derivados de choices posicionales, evitando identidad de cable dependiente del orden. El multiselect opcional no se ejercitó.
2. `c3a35a741a769cbb90bc6846062f0800b1199f9b`: cambios de fuente en [django_graphex/converter.py](django_graphex/converter.py).
3. Límite comprobado: Se rechaza el miembro ambiguo generado; el multiselect opcional no quedó cubierto por esa prueba.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_choices_enum_member_ambiguity.py](tests/core/test_choices_enum_member_ambiguity.py), `test_ambiguous_members_reject_public_schema_without_cache_pollution` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert list(corrected.values) == ["ALPHA", "BETA"]
   ```
   - [tests/core/test_choices_enum_member_ambiguity.py](tests/core/test_choices_enum_member_ambiguity.py): `test_ambiguous_members_reject_all_supported_choices_forms` (definición añadida); `test_ambiguous_members_reject_public_schema_without_cache_pollution` (definición añadida); `test_ambiguous_members_reject_generated_input_and_filter` (definición añadida).


### L-C8 — page: -1 no da la última página real (pagination.py:1240)

**Estado:** contract

**Problema original:** `page: -1` no da la última página real (`pagination.py:1240`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 187. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 257; la [tarea T12](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** page:-1 con 23 filas y tamaño 10. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"expect final page's 3 rows"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"actual tail window contains 10 rows (unchanged contract)"
```

**Cómo se llegó al resultado:**
1. No se cambió paginación por este alegato: page:-1 ya designa la ventana final de tamaño fijo, no el resto corto de la última página positiva. La equivalencia esperada era incorrecta.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: page:-1 significa una ventana final del tamaño solicitado, no el resto corto de la última página positiva; no se cambió ejecución.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_pagination_page_null_http.py](tests/test_pagination_page_null_http.py), `test_explicit_null_page_matches_omission_http` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert expected["totalCount"] == 5
   ```
   - [tests/test_pagination_page_null_http.py](tests/test_pagination_page_null_http.py): `test_explicit_null_page_matches_omission_http` (definición añadida); `test_existing_page_boundaries_http` (definición añadida); `test_omitted_nullable_variable_keeps_default_http` (definición añadida); `test_nested_null_page_reaches_materialized_list_without_optimizer` (definición añadida); `test_direct_page_null_normalizes_both_paths` (definición añadida).


### L-C9 — Orden de NULL distinto entre DB y memoria (pagination.py:112-123)

**Estado:** bounded-fixed

**Problema original:** Orden de NULL distinto entre DB y memoria (`pagination.py:112-123`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 188. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 258; la [tarea T12/R04f](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** ordenar columna nullable en memoria y base de datos. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"values": [null, 1], "order": "asc"}
```

**Antes (ilustrativo):**
```json
{"sqlite_ids": ["null", "one"]}
```

**Después (observado/actual):**
```json
{"covered_ids": ["one", "null"]}
```

**Cómo se llegó al resultado:**
1. La ordenación automática nullable fija NULL último en ascendente y primero en descendente en rutas cubiertas de BD y memoria. Expresiones ORM y cursores son independientes.
2. `ebeb63ab665f650551470b3db107f8c98f28e87a`: cambios de fuente en [django_graphex/fields.py](django_graphex/fields.py), [django_graphex/paginations/pagination.py](django_graphex/paginations/pagination.py).
3. Límite comprobado: Las columnas anulables automáticas ordenan NULL último ASC y primero DESC en rutas aprobadas; expresiones ORM explícitas y Cursor siguen aparte.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_pagination_null_order_parity.py](tests/test_pagination_null_order_parity.py), `test_nullable_queryset_and_materialized_pages_agree` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert [row.pk for row in queryset_page] == expected
   ```
   - [tests/test_pagination_null_order_parity.py](tests/test_pagination_null_order_parity.py): `test_nullable_queryset_and_materialized_pages_agree` (definición añadida); `test_nested_nullable_order_matches_window_and_plain_prefetch` (definición añadida); `test_explicit_orm_null_placement_remains_authoritative` (definición añadida); `test_multifield_priority_and_relation_name_remain_intact` (definición añadida); `test_malformed_prefix_is_not_normalized_into_a_valid_column` (definición añadida).


### L-C10 — Directivas declaradas en FRAGMENT_SPREAD/INLINE_FRAGMENT que se ignoran (directives/base.py:40)

**Estado:** bounded-fixed

**Problema original:** Directivas declaradas en `FRAGMENT_SPREAD`/`INLINE_FRAGMENT` que se ignoran (`directives/base.py:40`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 189. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 259; la [tarea T15/R03k](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** aplicar transformación sobre spread o fragment inline. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"query": "{ ...Words @uppercase } fragment Words on Query { text }", "directive_location": "FRAGMENT_SPREAD"}
```

**Antes (ilustrativo):**
```json
{"validation": "accepted", "transform": "ignored"}
```

**Después (observado/actual):**
```json
{"data": null, "validation_error": "@uppercase invalid on fragment spread", "resolver_calls": 0}
```

**Cómo se llegó al resultado:**
1. Las directivas de transformación declaran solo FIELD; la validación GraphQL rechaza su uso en spread o fragment inline antes del resolver. Un campo dentro de fragmento puede transformarse.
2. `03cd107e028dd096a759e95b5bbb4f98dde15c2c`: cambios de fuente en [django_graphex/directives/base.py](django_graphex/directives/base.py).
3. Límite comprobado: Las transformaciones se declaran solo en FIELD; un spread/inline fragment produce error de validación antes del resolver. Campos dentro de fragmentos siguen transformándose.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_directive_field_locations.py](tests/test_directive_field_locations.py), `test_transform_on_fragment_is_rejected_before_resolution` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data is None
   ```
   - [tests/test_directive_field_locations.py](tests/test_directive_field_locations.py): `test_transform_on_fragment_is_rejected_before_resolution` (definición añadida); `test_field_transform_inside_fragment_still_executes` (definición añadida); `test_spec_builtins_still_control_fragment_and_field_selection` (definición añadida); `test_library_locations_and_builtin_metadata_are_distinct` (definición añadida); `test_raw_third_party_directive_keeps_explicit_fragment_locations` (definición añadida); `test_field_transform_order_is_unchanged` (definición añadida); `test_invalid_fragment_transform_has_http_error_wire` (definición añadida); `test_guide_states_field_only_contract_with_fragment_migration` (definición añadida).


### L-C11 — Varios edge cases de @truncate, @title y @floor con inf

**Estado:** bounded-fixed

**Problema original:** Varios edge cases de `@truncate`, `@title` y `@floor` con `inf`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 190. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 260; la [tarea T15/R03l](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** @floor recibe NaN o Infinity. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"directive": "@floor", "value": "inf"}
```

**Antes (ilustrativo):**
```json
{"exception": "Python integer conversion detail"}
```

**Después (observado/actual):**
```json
{"errors": ["stable GraphQL field error"]}
```

**Cómo se llegó al resultado:**
1. La directiva floor traduce fallo de NaN e Infinity a error GraphQL estable. La supuesta @title no está registrada; @title_case y @truncate no cambiaron por este arreglo.
2. `5b1022bcb5649016afc1ebada00b8e941e713170`: cambios de fuente en [django_graphex/directives/numbers.py](django_graphex/directives/numbers.py).
3. Límite comprobado: @floor normaliza errores de NaN/Infinity; @title no está registrado, mientras @title_case y @truncate conservan su conversión a texto.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_floor_nonfinite_error.py](tests/test_floor_nonfinite_error.py), `test_floor_public_execution_returns_nullable_error` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data == {"value": None}
   ```
   - [tests/test_floor_nonfinite_error.py](tests/test_floor_nonfinite_error.py): `test_floor_directly_rejects_nonfinite_values` (definición añadida); `test_floor_public_execution_returns_nullable_error` (definición añadida); `test_floor_rejects_numeric_strings_that_coerce_to_nonfinite` (definición añadida); `test_floor_keeps_finite_and_boolean_values` (definición añadida); `test_floor_preserves_none_and_malformed_value_policy` (definición añadida); `test_floor_nonnull_error_uses_standard_bubbling` (definición añadida); `test_other_directives_and_floor_schema_metadata_remain_unchanged` (definición añadida).


### L-C12 — _inline_fragment_applies no reconoce uniones ni padres MTI, lo que provoca N+1 (utils.py:681-810)

**Estado:** partial

**Problema original:** `_inline_fragment_applies` no reconoce uniones ni padres MTI, lo que provoca N+1 (`utils.py:681-810`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 191. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 261; la [tarea T14/T14e](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** fragmento de wrapper union GFK con relación optimizable. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"rows": [1, 2, 3], "generic_fk_target_type": "Author"}
```

**Antes (ilustrativo):**
```json
{"target_fetches": 3}
```

**Después (observado/actual):**
```json
{"target_fetches": "one covered type batch"}
```

**Cómo se llegó al resultado:**
1. El optimizador GFK union reúne planes de relación de ramas en vez de perderlos en el wrapper, eliminando el N+1 ejercitado. Herencia multitabla fuera de esa forma no está probada.
2. `c8bb0dd2d7700eec80cadbab3ade0af4f3a655e8`: cambios de fuente en [django_graphex/utils.py](django_graphex/utils.py).
3. Límite comprobado: Se corrigió N+1 del envoltorio union GFK probado; herencia multi-tabla fuera de ese caso permanece sin demostración.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   - [tests/test_optimizer_phase_e.py](tests/test_optimizer_phase_e.py): `test_returns_hook_when_present` (definición sin cambios); `test_returns_none_when_absent` (definición sin cambios); `test_returns_none_when_gql_type_is_none` (definición sin cambios); `test_returns_none_when_no_graphene_type` (definición sin cambios); `test_camel_case_field_name_is_snake_cased` (definición sin cambios); `test_returns_qs_unchanged_when_hook_is_none` (definición sin cambios); `test_returns_hook_result_when_valid_queryset` (definición sin cambios); `test_hook_receives_filter_value_and_is_window_kwargs` (definición sin cambios); `test_non_queryset_return_emits_warning_and_returns_original` (definición sin cambios); `test_exception_propagates_when_safe_mode_false` (definición sin cambios); `test_exception_propagates_from_helper_even_when_safe_mode_true` (definición sin cambios); `test_ac1_window_hook_fires_with_is_window_true` (definición sin cambios); `test_ac5_hook_adds_distinct_falls_back_to_plain` (definición sin cambios); `test_ac6_hook_aliasing_gqx_rn_is_silently_overwritten_noop` (definición sin cambios); `test_ac2_filtered_plain_hook_fires_with_is_window_false` (definición sin cambios); `test_ac2b_unfiltered_top_level_hook_fires` (definición sin cambios); `test_ac2b_no_hook_is_noop` (definición sin cambios); `test_site_b_hook_fires_for_reroot_child` (definición sin cambios); `test_hook_fires_through_forward_fk_relation` (definición sin cambios); `test_multiple_children_and_multi_segment_hooks_all_fire` (definición sin cambios); `test_hook_fires_when_only_and_annotated_off` (definición sin cambios); `test_hook_does_not_fire_when_optimize_queryset_false` (definición sin cambios); `test_hooked_case_has_join_control_does_not` (definición sin cambios); `test_safe_mode_raising_hook_degrades_whole_resolve_coarsely` (definición sin cambios); `test_no_hook_no_error_and_no_behavior_change` (definición sin cambios).

**Límite pendiente:** Se corrigió N+1 del envoltorio union GFK probado; herencia multi-tabla fuera de ese caso permanece sin demostración.


### L-C13 — Fechas naive o sin hora se interpretan en hora local sin documentarlo (core/scalars.py:134-146)

**Estado:** contract

**Problema original:** Fechas naive o sin hora se interpretan en hora local sin documentarlo (`core/scalars.py:134-146`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 192. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 262; la [tarea T15](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** DateTime naive nativo frente a @date en zona activa. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"assumed both use same local-zone policy"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"scalar stays naive; @date uses active timezone"
```

**Cómo se llegó al resultado:**
1. La documentación separó parseo DateTime naive de formato @date en zona activa, incluso USE_TZ=False. No se cambió silenciosamente el scalar.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: La guía distingue DateTime nativo naive de interpretación @date en zona activa (incluido USE_TZ=False); no se cambió el scalar.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### L-E1 — except Exception en _model_derived_fields y en el fallback de get_fields(): las relaciones desaparecen del schema…

**Estado:** bounded-fixed

**Problema original:** `except Exception` en `_model_derived_fields` y en el fallback de `get_fields()`: las relaciones desaparecen del schema sin log (`types.py:195-219`, `output_compiler.py:899`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 195. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 263; la [tarea T14/T14f](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** get_fields del modelo lanza una excepción. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"model": "Book", "relation": "author", "get_fields": "raises RuntimeError"}
```

**Antes (ilustrativo):**
```json
{"schema": "author relation silently omitted"}
```

**Después (observado/actual):**
```json
{"error": "Book field introspection failed with cause"}
```

**Cómo se llegó al resultado:**
1. La enumeración de campos muestra modelo y causa de un fallo get_fields en lugar de ocultarlo y producir esquema incompleto. La ruta sana no cambia.
2. `0c5e32065fc43799b36872ea6bc1cdaf9f007af7`: cambios de fuente en [django_graphex/core/base.py](django_graphex/core/base.py), [django_graphex/core/output_compiler.py](django_graphex/core/output_compiler.py), [django_graphex/schema.py](django_graphex/schema.py), [django_graphex/types.py](django_graphex/types.py).
3. Límite comprobado: Un error de get_fields ahora muestra modelo y causa; la ruta sana no cambia.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_metadata_enumeration_failures.py](tests/core/test_metadata_enumeration_failures.py), `test_model_derived_fields_identifies_model_and_preserves_cause` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert caught.value.__cause__ is original
   ```
   - [tests/core/test_metadata_enumeration_failures.py](tests/core/test_metadata_enumeration_failures.py): `test_model_derived_fields_identifies_model_and_preserves_cause` (definición añadida); `test_output_compiler_identifies_model_and_preserves_cause` (definición añadida); `test_public_schema_rejects_relation_metadata_failure` (definición añadida); `test_eager_field_recompile_retains_original_cause` (definición añadida); `test_eager_field_recompile_keeps_uncaused_error_unchained` (definición añadida); `test_lazy_schema_keeps_uncaused_configuration_error` (definición añadida); `test_lazy_schema_leaves_generic_type_error_untouched` (definición añadida).


### L-E2 — getattr(root, source, None) oculta AttributeError dentro de properties (descriptors.py:~80)

**Estado:** bounded-fixed

**Problema original:** `getattr(root, source, None)` oculta `AttributeError` dentro de properties (`descriptors.py:~80`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 196. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 264; la [tarea T15/T15a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** property usada como source lanza AttributeError interno. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"source_property": "book.title", "getter": "raises AttributeError"}
```

**Antes (ilustrativo):**
```json
{"data": {"title": null}, "errors": []}
```

**Después (observado/actual):**
```json
{"data": {"title": null}, "errors": ["property failure"]}
```

**Cómo se llegó al resultado:**
1. Se expone AttributeError de una property source explícita en vez de tratarla como atributo ausente; un atributo opcional realmente ausente puede seguir en null.
2. `72fbcbdccecfb955ad71666b31ae7c02618803eb`: cambios de fuente en [django_graphex/core/descriptors.py](django_graphex/core/descriptors.py). Commits de seguimiento: `7fb4c121dca116d9e0192e87d744f555444c1c27`.
3. Límite comprobado: Se distingue propiedad source explícita que falla de atributo legítimamente ausente; se expone su AttributeError.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_source_property_attribute_error.py](tests/core/test_source_property_attribute_error.py), `test_wrapped_python_property_source_preserves_original_error` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert result.data == {"alias": None, "healthy": "visible"}
   ```
   - [tests/core/test_source_property_attribute_error.py](tests/core/test_source_property_attribute_error.py): `test_wrapped_python_property_source_preserves_original_error` (definición añadida); `test_source_property_attribute_error_surfaces_graphql_resolution_error` (definición añadida); `test_inherited_source_property_failure_preserves_required_propagation` (definición añadida); `test_source_absence_and_successful_dynamic_fallback_remain_nullable` (definición añadida); `test_absent_django_reverse_one_to_one_stays_nullable_through_property` (definición añadida); `test_custom_attribute_lookup_and_nested_required_propagation` (definición añadida); `test_unrelated_descriptor_and_dynamic_absence_keep_legacy_null` (definición añadida); `test_explicit_resolver_precedes_source_and_method_body_error_is_unchanged` (definición añadida); `test_source_property_failure_keeps_safe_http_diagnostics` (definición añadida).


### L-E3 — _merge_filtered_prefetches descarta en silencio el hook optimize_<field>, y podría devolver hijos sin scope…

**Estado:** partial

**Problema original:** `_merge_filtered_prefetches` descarta en silencio el hook `optimize_<field>`, y podría devolver hijos sin scope (`utils.py:~3175`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 197. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 265; la [tarea T07/T14](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** prefetch filtrado SITE-B con optimize_<field>. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"site": "SITE-B", "optimizer_hook": "filtered prefetch"}
```

**Antes (ilustrativo):**
```json
{"audit_prediction": "hook missing / hidden row leak"}
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
{"observed_hook_calls": 1, "returned_rows": "visible only", "other_branches": "not proved"}
```

**Cómo se llegó al resultado:**
1. El testigo SITE-B mostró optimize_<field> una vez, solo filas visibles y predicado agrupado intacto. No justificó parche del optimizador en esa ruta; otros sitios siguen sin medir.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: El testigo público SQLite SITE-B contradijo esa variante: hook una vez, filas visibles, predicado agrupado; otros sitios quedan abiertos.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   - [tests/test_optimizer_phase_e.py](tests/test_optimizer_phase_e.py): `test_returns_hook_when_present` (definición sin cambios); `test_returns_none_when_absent` (definición sin cambios); `test_returns_none_when_gql_type_is_none` (definición sin cambios); `test_returns_none_when_no_graphene_type` (definición sin cambios); `test_camel_case_field_name_is_snake_cased` (definición sin cambios); `test_returns_qs_unchanged_when_hook_is_none` (definición sin cambios); `test_returns_hook_result_when_valid_queryset` (definición sin cambios); `test_hook_receives_filter_value_and_is_window_kwargs` (definición sin cambios); `test_non_queryset_return_emits_warning_and_returns_original` (definición sin cambios); `test_exception_propagates_when_safe_mode_false` (definición sin cambios); `test_exception_propagates_from_helper_even_when_safe_mode_true` (definición sin cambios); `test_ac1_window_hook_fires_with_is_window_true` (definición sin cambios); `test_ac5_hook_adds_distinct_falls_back_to_plain` (definición sin cambios); `test_ac6_hook_aliasing_gqx_rn_is_silently_overwritten_noop` (definición sin cambios); `test_ac2_filtered_plain_hook_fires_with_is_window_false` (definición sin cambios); `test_ac2b_unfiltered_top_level_hook_fires` (definición sin cambios); `test_ac2b_no_hook_is_noop` (definición sin cambios); `test_site_b_hook_fires_for_reroot_child` (definición sin cambios); `test_hook_fires_through_forward_fk_relation` (definición sin cambios); `test_multiple_children_and_multi_segment_hooks_all_fire` (definición sin cambios); `test_hook_fires_when_only_and_annotated_off` (definición sin cambios); `test_hook_does_not_fire_when_optimize_queryset_false` (definición sin cambios); `test_hooked_case_has_join_control_does_not` (definición sin cambios); `test_safe_mode_raising_hook_degrades_whole_resolve_coarsely` (definición sin cambios); `test_no_hook_no_error_and_no_behavior_change` (definición sin cambios).

**Límite pendiente:** El testigo público SQLite SITE-B contradijo esa variante: hook una vez, filas visibles, predicado agrupado; otros sitios quedan abiertos.


### L-E4 — _cancel_operation hace except (CancelledError, Exception): pass (ws.py:753)

**Estado:** partial

**Problema original:** `_cancel_operation` hace `except (CancelledError, Exception): pass` (`ws.py:753`). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 198. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 266; la [tarea T08/T08c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** cancelación esperada y warning aclose de un grupo. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"source": "one subscribed group", "action": "cancel stream"}
```

**Antes (ilustrativo):**
```json
{"close": "RuntimeError warning leaked"}
```

**Después (observado/actual):**
```json
{"close": "warning handled on covered path"}
```

**Cómo se llegó al resultado:**
1. Se mantuvo la cancelación esperada; solo el warning aclose observado para un grupo recibió limpieza dirigida. Otras fases sin ejercitar no se marcan corregidas.
2. `e04394b6fcc4b4ac02e31793e7e6479fea785e9c`: cambios de fuente en [django_graphex/subscriptions/delivery.py](django_graphex/subscriptions/delivery.py).
3. Límite comprobado: La cancelación esperada es deliberada; solo se corrigió el warning aclose de un grupo. Otras rutas siguen abiertas.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_delivery_runtimeerror_diagnostic.py](tests/subscriptions/test_delivery_runtimeerror_diagnostic.py), `test_delivery_close_runtimeerror_warns_once_and_stays_idempotent` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert warnings[0].exc_info[1] is failure
   ```
   - [tests/subscriptions/test_delivery_runtimeerror_diagnostic.py](tests/subscriptions/test_delivery_runtimeerror_diagnostic.py): `test_client_complete_logs_suppressed_delivery_runtimeerror` (definición añadida); `test_client_complete_valueerror_keeps_existing_error_frame` (definición añadida); `test_delivery_close_runtimeerror_warns_once_and_stays_idempotent` (definición añadida).
   - [tests/subscriptions/test_source.py](tests/subscriptions/test_source.py): `test_all_actions_joins_exactly_three_groups` (localizador histórico fuera del inventario); `test_single_action_joins_exactly_one_group_1420_guard` (localizador histórico fuera del inventario); `test_context_manager_start_joins_groups` (localizador histórico fuera del inventario); `test_broadcast_to_joined_group_yields_flat_data_dict` (localizador histórico fuera del inventario); `test_serialize_instance_not_called_on_consumer_yield_path` (localizador histórico fuera del inventario); `test_assertNumQueries_zero_on_consumer_yield_path` (localizador histórico fuera del inventario); `test_non_matching_filter_event_dropped_pre_execute` (localizador histórico fuera del inventario); `test_no_filters_yields_every_event` (localizador histórico fuera del inventario); `test_aclose_group_discards_every_joined_group` (localizador histórico fuera del inventario); `test_aexit_group_discards_every_joined_group` (localizador histórico fuera del inventario); `test_aclose_releases_blocked_receive_promptly` (localizador histórico fuera del inventario); `test_aclose_idempotent` (localizador histórico fuera del inventario); `test_group_discard_runs_even_on_abnormal_teardown` (localizador histórico fuera del inventario); `test_aclose_discard_sweep_is_exception_isolated` (localizador histórico fuera del inventario); `test_external_cancellation_propagates` (localizador histórico fuera del inventario); `test_aclose_initiated_cancel_still_stops_cleanly` (localizador histórico fuera del inventario); `test_lookup_filter_without_verifier_drops_conservatively` (localizador histórico fuera del inventario); `test_lookup_filter_with_verifier_true_yields_false_drops` (localizador histórico fuera del inventario); `test_source_module_has_no_graphene_import` (localizador histórico fuera del inventario); `test_source_module_is_async_iterator` (localizador histórico fuera del inventario).

**Límite pendiente:** La cancelación esperada es deliberada; solo se corrigió el warning aclose de un grupo. Otras rutas siguen abiertas.


### L-M1 — _gdx_input_registry crece sin límite y produce un duplicado al redefinir

**Estado:** decision-deferred

**Problema original:** `_gdx_input_registry` crece sin límite y produce un duplicado al redefinir. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 201. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 267; la [tarea T14](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** redefinir clases dinámicas frente a reutilizar esquemas estáticos. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"audit predicts unbounded duplicates"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"bounded static reuse; dynamic churn unproven"
```

**Cómo se llegó al resultado:**
1. Tres esquemas estáticos reutilizaron clases sin crecimiento observado, pero churn dinámico carece de contrato de propiedad/evicción. No se cambió la vida útil del registro global.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Tres esquemas estáticos reutilizan clases sin crecimiento observado; churn dinámico necesita decisión de propiedad y vida útil.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_registry_compiler.py](tests/core/test_registry_compiler.py), `test_mutual_recursion_terminates` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert compiled_b.name == "NodeB"
   ```
   - [tests/core/test_registry_compiler.py](tests/core/test_registry_compiler.py): `test_mutual_recursion_terminates` (localizador histórico fuera del inventario); `test_mutual_recursion_thunks_resolve_correctly` (localizador histórico fuera del inventario); `test_self_referential_type_compiles` (localizador histórico fuera del inventario); `test_compile_all_raises_on_missing_gdx_extensions` (localizador histórico fuera del inventario); `test_compile_all_no_error_when_all_types_have_gdx` (localizador histórico fuera del inventario).

**Límite pendiente:** Tres esquemas estáticos reutilizan clases sin crecimiento observado; churn dinámico necesita decisión de propiedad y vida útil.


### L-M2 — _NATIVE_FIELD_IDENTITIES usa id(), que puede reciclarse

**Estado:** partial

**Problema original:** `_NATIVE_FIELD_IDENTITIES` usa `id()`, que puede reciclarse. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 202. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 268; la [tarea T14/T14g](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** ID de objeto Python reciclado tras morir un campo nativo. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"schemas": ["A", "B"], "field": "same live Python field identity"}
```

**Antes (ilustrativo):**
```json
{"internal_cache": "id-based stale reuse possible"}
```

**Después (observado/actual):**
```json
{"internal_cache": "lifetime-guarded for covered path"}
```

**Cómo se llegó al resultado:**
1. El seguimiento interno de identidad de campo conserva referencia al objeto vivo en vez de solo id(), evitando heredar un registro por ID reciclado. No se demostró impacto público.
2. `a2ff209469f1c642fff20ebf78c3c4019db1dd5b`: cambios de fuente en [django_graphex/core/mutation.py](django_graphex/core/mutation.py), [django_graphex/core/schema_compiler.py](django_graphex/core/schema_compiler.py), [django_graphex/mutation.py](django_graphex/mutation.py), [django_graphex/types.py](django_graphex/types.py).
3. Límite comprobado: Se corrigió el caso interno de identidad/vida útil; impacto público y Graphene no establecidos.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_native_field_identity_lifetime.py](tests/core/test_native_field_identity_lifetime.py), `test_native_field_marker_expires_when_field_dies` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert reference() is None
   ```
   - [tests/core/test_native_field_identity_lifetime.py](tests/core/test_native_field_identity_lifetime.py): `test_native_field_marker_expires_when_field_dies` (definición añadida); `test_live_native_field_survives_registry_slot_overwrite` (definición añadida); `test_current_registry_value_is_a_defensive_identity_source` (definición añadida); `test_stale_identity_key_cannot_admit_an_unrelated_field` (definición añadida); `test_modeltype_builder_tracks_its_actual_native_field` (definición añadida); `test_model_mutation_builder_tracks_its_actual_native_field` (definición añadida).

**Límite pendiente:** Se corrigió el caso interno de identidad/vida útil; impacto público y Graphene no establecidos.


### L-M3 — _TYPE_CACHE de enums sin lock

**Estado:** partial

**Problema original:** `_TYPE_CACHE` de enums sin lock. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 203. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 269; la [tarea T14/T14h](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** construir enums concurrentemente en GraphQLSchema directo. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"threads": 2, "enum": "same model choices"}
```

**Antes (ilustrativo):**
```json
{"constructions": 2}
```

**Después (observado/actual):**
```json
{"constructions": 1}
```

**Cómo se llegó al resultado:**
1. La creación de enums en GraphQLSchema directo se serializa durante el llenado de caché compartida. No se estableció carrera de solicitud pública.
2. `14720eab7d6662c4ce9f3ee56f1b7740133e1c08`: cambios de fuente en [django_graphex/converter.py](django_graphex/converter.py), [django_graphex/core/compiler.py](django_graphex/core/compiler.py), [django_graphex/registry.py](django_graphex/registry.py).
3. Límite comprobado: Se protegió la creación concurrente de enums en GraphQLSchema directo; exposición pública no demostrada.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_enum_cache_concurrency.py](tests/core/test_enum_cache_concurrency.py), `test_compile_enum_shares_one_object_after_contended_miss` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert len(constructed) == 1
   ```
   - [tests/core/test_enum_cache_concurrency.py](tests/core/test_enum_cache_concurrency.py): `test_compile_enum_shares_one_object_after_contended_miss` (definición añadida); `test_compile_type_shares_one_object_after_contended_miss` (definición añadida); `test_compile_schema_keeps_reset_and_build_in_one_transaction` (definición añadida); `test_native_choices_reuse_one_object_after_contended_miss` (definición añadida); `test_native_choices_reject_incompatible_concurrent_definition` (definición añadida); `test_native_choices_keep_serial_ambiguity_and_registry_isolation` (definición añadida).

**Límite pendiente:** Se protegió la creación concurrente de enums en GraphQLSchema directo; exposición pública no demostrada.


### L-M4 — get_global_registry / get_or_create_list_object_type hacen check-then-act sin lock

**Estado:** partial

**Problema original:** `get_global_registry` / `get_or_create_list_object_type` hacen check-then-act sin lock. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 204. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 270; la [tarea T14/T14i](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** crear tipo lista y registro global desde hilos distintos. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"threads": 2, "list_type": "same output leaf"}
```

**Antes (ilustrativo):**
```json
{"registrations": 2}
```

**Después (observado/actual):**
```json
{"registrations": 1}
```

**Cómo se llegó al resultado:**
1. El registro frío de tipos lista usa sincronización en vez de check-then-insert global inseguro. La prueba es construcción directa de esquema, no toda intercalación de servidor.
2. `13b2e6b4cdfd7489210267a5f6b5e3f35ec49ac4`: cambios de fuente en [django_graphex/registry.py](django_graphex/registry.py), [django_graphex/types.py](django_graphex/types.py).
3. Límite comprobado: Se protegió el registro de lista en GraphQLSchema directo; exposición pública no demostrada.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/core/test_registry_creation_concurrency.py](tests/core/test_registry_creation_concurrency.py), `test_global_registry_concurrent_cold_calls_share_one_instance` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert registry_module.get_global_registry() is first_result
   ```
   - [tests/core/test_registry_creation_concurrency.py](tests/core/test_registry_creation_concurrency.py): `test_global_registry_concurrent_cold_calls_share_one_instance` (definición añadida); `test_global_registry_failed_construction_retries_and_reset_isolated` (definición añadida); `test_concurrent_list_misses_share_class_graphql_object_and_cache` (definición añadida); `test_explicit_list_registration_keeps_last_registration_wins` (definición añadida); `test_list_creation_is_scoped_to_each_model_and_registry` (definición añadida).

**Límite pendiente:** Se protegió el registro de lista en GraphQLSchema directo; exposición pública no demostrada.


### L-S1 — SSE sin heartbeat ni tope de streams por usuario

**Estado:** partial

**Problema original:** SSE sin heartbeat ni tope de streams por usuario. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 207. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 271; la [tarea T08/R01e](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** heartbeat SSE y límite de streams por cuenta. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```http
GET /subscriptions/sse?query=subscription%20%7B...%7D
Accept: text/event-stream
```

**Antes (ilustrativo):**
```json
{"admission": "no account cap"}
```

**Después (observado/actual):**
```json
{"http_status": 429, "source_started": false}
```

**Cómo se llegó al resultado:**
1. Heartbeat y leases SSE por cuenta son opcionales y OFF por defecto. La implementación aceptada usa Lua Redis para concesión/denegación atómica en una instancia y libera al cerrar; particiones/failover y plazo total duro no están probados.
2. `7ec2264c763859cd840e1475e8f4cec9a47ed8fc`: cambios de fuente en [django_graphex/settings.py](django_graphex/settings.py), [django_graphex/subscriptions/transports/_sse_lease.py](django_graphex/subscriptions/transports/_sse_lease.py), [django_graphex/subscriptions/transports/sse.py](django_graphex/subscriptions/transports/sse.py).
3. Límite comprobado: Se incorporaron controles opt-in OFF por defecto (15 segundos/cinco streams), probados históricamente con Redis real en una instancia. Failover/partición y plazo total estricto siguen sin prueba.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [integration/live_redis/test_sse_live_redis.py](integration/live_redis/test_sse_live_redis.py), `test_real_lua_cross_process_cap` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert {entry["key"] for entry in results} == {key}
   ```
   - [integration/live_redis/test_sse_live_redis.py](integration/live_redis/test_sse_live_redis.py): `test_real_lua_cross_process_cap` (definición añadida); `test_real_lua_ownership_expiry_and_independent_accounts` (definición añadida); `test_real_lua_unknown_acquire_reply_releases_committed_token` (definición añadida); `test_real_lua_double_cancellation_waits_for_commit_then_releases` (definición añadida); `test_real_lua_crashed_owner_expires_without_release` (definición añadida); `test_public_sse_live_cap_and_cleanup` (definición añadida); `test_public_sse_live_backend_unavailable_is_503_before_source` (definición añadida); `test_public_sse_live_source_start_failure_releases_lease` (definición añadida); `test_public_sse_live_normal_source_completion_releases_lease` (definición añadida); `test_public_sse_live_midstream_loss_is_generic_and_closes` (definición añadida).
   - [tests/subscriptions/test_sse_lease_lifecycle.py](tests/subscriptions/test_sse_lease_lifecycle.py): `test_expired_initial_lease_never_delivers_application_data` (definición añadida); `test_ready_events_still_renew_overdue_lease` (definición añadida); `test_repeated_cancellation_settles_admission_before_release` (definición añadida); `test_backend_error_after_start_closes_source_before_503` (definición añadida); `test_cancelled_startup_revalidation_closes_source_and_lease` (definición añadida); `test_consumer_delay_rechecks_before_next_source_read` (definición añadida); `test_overdue_ready_result_is_withheld_on_backend_error` (definición añadida).
   - [tests/subscriptions/test_sse_controls.py](tests/subscriptions/test_sse_controls.py): `test_idle_heartbeat_keeps_one_source_alive` (definición añadida); `test_heartbeat_remains_off_by_default` (definición añadida); `test_second_account_stream_is_rejected_before_source` (definición añadida); `test_backend_failure_is_pre_stream_503` (definición añadida); `test_sixth_stream_is_429_and_existing_five_survive` (definición añadida); `test_anonymous_request_does_not_access_account_lease_backend` (definición añadida); `test_source_start_failure_releases_reserved_slot` (definición añadida); `test_renewal_failure_finishes_stream_without_backend_secret` (definición añadida); `test_expired_lease_cannot_be_resurrected` (definición añadida); `test_cancelled_unknown_admission_cleans_its_token` (definición añadida); `test_event_heartbeat_and_natural_completion_share_one_source` (definición añadida); `test_healthy_lease_renews_without_heartbeat` (definición añadida); `test_subscribe_result_releases_unused_lease` (definición añadida); `test_missing_persistent_account_id_is_refused` (definición añadida); `test_failed_release_is_bounded_by_expiry` (definición añadida); `test_cancelled_backend_failure_still_propagates_cancellation` (definición añadida); `test_controls_ship_disabled_with_independent_values` (definición añadida); `test_invalid_control_settings_fail_explicitly` (definición añadida).

**Límite pendiente:** Se incorporaron controles opt-in OFF por defecto (15 segundos/cinco streams), probados históricamente con Redis real en una instancia. Failover/partición y plazo total estricto siguen sin prueba.


### L-S2 — El connection_init payload se ignora: no hay hook on_connect para auth por token

**Estado:** bounded-fixed

**Problema original:** El `connection_init` payload se ignora: no hay hook `on_connect` para auth por token. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 208. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 272; la [tarea T08/R01d](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** autenticar connection_init antes de ACK WebSocket. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"connection_init": {"token": "valid"}, "callback_user": "Alice"}
```

**Antes (ilustrativo):**
```json
{"ack_user": "anonymous"}
```

**Después (observado/actual):**
```json
{"ack_user": "Alice", "schema_user": "Alice"}
```

**Cómo se llegó al resultado:**
1. Un on_connect asíncrono opcional corre antes del ACK WS y puede fijar usuario efectivo o denegar con cierre 4403. La denegación explícita no vuelve a sesión; no se añadió backend JWT universal.
2. `98956fa142bca0d6b78a7402ff626270d4295afc`: cambios de fuente en [django_graphex/subscriptions/transports/ws.py](django_graphex/subscriptions/transports/ws.py).
3. Límite comprobado: Un on_connect asíncrono opcional autentica antes de ACK y fija usuario efectivo; denegación cierra 4403 sin fallback de sesión. No JWT/backend general añadido.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_ws_on_connect.py](tests/subscriptions/test_ws_on_connect.py), `test_hook_receives_normalized_payload_and_blocks_ack` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert seen == [(communicator.scope, payload or {})]
   ```
   - [tests/subscriptions/test_ws_on_connect.py](tests/subscriptions/test_ws_on_connect.py): `test_default_ignores_nonmapping_init_payloads` (definición añadida); `test_hook_receives_normalized_payload_and_blocks_ack` (definición añadida); `test_hook_identity_replaces_session_for_provider_and_permissions` (definición añadida); `test_hook_denial_has_no_session_fallback_or_secret_output` (definición añadida); `test_hook_rejects_nonmapping_payload_without_invocation` (definición añadida); `test_pending_hook_retains_protocol_errors` (definición añadida); `test_pending_hook_times_out_and_cancels_without_late_ack` (definición añadida); `test_disconnect_cancels_pending_hook` (definición añadida); `test_late_callback_result_cannot_replace_identity_or_ack` (definición añadida); `test_documented_on_connect_callback_is_typed_and_explained` (definición añadida).


### L-S3 — Se acepta el subprotocolo aunque el cliente no lo ofrezca

**Estado:** bounded-fixed

**Problema original:** Se acepta el subprotocolo aunque el cliente no lo ofrezca. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 209. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 273; la [tarea T08/R01c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** cliente no ofrece subprotocolo WS requerido. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"client_subprotocols": ["wrong-protocol"]}
```

**Antes (ilustrativo):**
```json
{"accepted": true}
```

**Después (observado/actual):**
```json
{"accepted": false, "registry_additions": 0}
```

**Cómo se llegó al resultado:**
1. El servidor WS valida que el subprotocolo requerido figure en la oferta antes de accept. Oferta ausente, vacía o solo errónea cierra; el protocolo correcto entre alternativas se acepta.
2. `ef598a7d3dca3b76974bdd0829991db895d984c1`: cambios de fuente en [django_graphex/subscriptions/transports/ws.py](django_graphex/subscriptions/transports/ws.py).
3. Límite comprobado: La oferta ausente, vacía o solo incorrecta se rechaza antes de accept; la oferta exacta entre alternativas se acepta. No cambio de autenticación.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_ws_subprotocol.py](tests/subscriptions/test_ws_subprotocol.py), `test_unoffered_subprotocol_is_rejected_before_accept` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert ws.get_live_consumer(communicator.scope) is None
   ```
   - [tests/subscriptions/test_ws_subprotocol.py](tests/subscriptions/test_ws_subprotocol.py): `test_unoffered_subprotocol_is_rejected_before_accept` (definición añadida); `test_required_subprotocol_is_accepted_among_alternatives` (definición añadida).


### L-S4 — Se envía complete antes de liberar el id, lo que puede dar un 4409 espurio

**Estado:** bounded-fixed

**Problema original:** Se envía `complete` antes de liberar el id, lo que puede dar un 4409 espurio. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 210. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 274; la [tarea T08/R01a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** reutilizar ID WS inmediatamente después de complete. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"operation_id": "op1", "frames": ["complete", "subscribe op1"]}
```

**Antes (ilustrativo):**
```json
{"second_subscribe": "duplicate / 4409"}
```

**Después (observado/actual):**
```json
{"second_subscribe": "admitted after cleanup"}
```

**Cómo se llegó al resultado:**
1. El ID de operación WS se retira de slots activos antes de emitir complete, permitiendo suscripción inmediata con el mismo ID. Otras carreras de ciclo de vida son distintas.
2. `9268da4033901e5a76daf6a3c84ac34c860dae0f`: cambios de fuente en [django_graphex/subscriptions/transports/ws.py](django_graphex/subscriptions/transports/ws.py).
3. Límite comprobado: Se libera el slot antes de emitir complete; reutilizar el ID de inmediato funciona. Otras fases del ciclo de vida siguen aparte.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/subscriptions/test_ws_completion_reuse.py](tests/subscriptions/test_ws_completion_reuse.py), `test_complete_waits_for_teardown_then_reuses_same_id` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert second.source.joined_groups
   ```
   - [tests/subscriptions/test_ws_completion_reuse.py](tests/subscriptions/test_ws_completion_reuse.py): `test_complete_waits_for_teardown_then_reuses_same_id` (definición añadida); `test_teardown_error_keeps_existing_terminal_frame_sequence` (definición añadida).


### Q1 — ruff check / ruff format --check: limpios. mypy django_graphex: 0 errores

**Estado:** contract

**Problema original:** `ruff check` / `ruff format --check`: limpios. `mypy django_graphex`: 0 errores. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 15–18, 217. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 275; la [tarea T01/T16](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** entorno local graphql-core 3.2.13 frente a 3.3 soportado. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"ambient result treated as supported proof"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"use isolated 3.3 evidence; root remains unsupported"
```

**Cómo se llegó al resultado:**
1. Dependencias, lock, tox y CI especifican graphql-core 3.3; el 3.2.13 ambiente no está soportado y no se reinstaló. Desajuste de entorno no es arreglo de tox.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Proyecto/lock/tox/CI exigen 3.3; el entorno raíz 3.2.13 no se actualizó y no demuestra un defecto de configuración tox.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/test_tox_dependency_contract.py](tests/test_tox_dependency_contract.py), `test_tox_tool_ranges_match_declared_dev_compatibility` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert TOX_TOOL_NAMES <= seen
   ```
   - [tests/test_tox_dependency_contract.py](tests/test_tox_dependency_contract.py): `test_tox_tool_ranges_match_declared_dev_compatibility` (localizador histórico fuera del inventario); `test_diff_cover_has_a_deliberate_dev_range` (localizador histórico fuera del inventario); `test_security_gate_audits_the_locked_runtime_dependencies` (localizador histórico fuera del inventario); `test_security_gate_runtime_target_is_documented` (localizador histórico fuera del inventario); `test_ruff_range_stays_with_formatter_compatible_minor` (localizador histórico fuera del inventario).


### Q2 — Test de provenance de benchmarks frágil: benchmarks/run_publish.py:92 hace glob(".json") sobre…

**Estado:** bounded-fixed

**Problema original:** Test de provenance de benchmarks frágil: `benchmarks/run_publish.py:92` hace `glob("*.json")` sobre `benchmarks/results/`, que contiene JSON locales ignorados por git (`rep_*`, `2x_summary.json`, `graphex_after*.json`…). Falla en cualquier checkout que haya ejecutado benchmarks. Validar solo `CANONICAL_RESULTS` o `git ls-files`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 218. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 276; la [tarea T01/T16a](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** lector de benchmark encuentra JSON antiguo no canónico. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"result_dir": ["case1.json", "unrelated.json"], "canonical_expected_count": 8}
```

**Antes (ilustrativo):**
```json
{"reader": "glob includes unrelated.json"}
```

**Después (observado/actual):**
```json
{"reader": "exact eight canonical names"}
```

**Cómo se llegó al resultado:**
1. El lector de procedencia selecciona ocho JSON canónicos y rechaza faltantes o inválidos, no toma cualquier JSON antiguo. No se regeneraron tiempos de benchmark.
2. `e31333468774344e176031d1241e25c2d1642dd3`: cambios de fuente en [benchmarks/run_publish.py](benchmarks/run_publish.py).
3. Límite comprobado: El lector selecciona exactamente ocho archivos canónicos; faltantes/inválidos siguen fallando. No se regeneraron tiempos.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   Aserción concreta actual de [tests/benchmarks/test_core33_results.py](tests/benchmarks/test_core33_results.py), `test_core33_bundle_has_exactly_eight_portable_artifacts` (extracto breve de fuente, no fallo reconstruido):
   ```python
   assert {path.name for path in RESULTS.iterdir()} == set(FILENAMES.values())
   ```
   - [tests/benchmarks/test_canonical_provenance.py](tests/benchmarks/test_canonical_provenance.py): `test_copy_canonical_fixture_ignores_diagnostics` (definición añadida); `test_missing_canonical_file_still_fails_with_diagnostics` (definición añadida); `test_validator_ignores_unrelated_diagnostic_json` (definición añadida).
   - [tests/benchmarks/test_core33_results.py](tests/benchmarks/test_core33_results.py): `test_core33_bundle_has_exactly_eight_portable_artifacts` (localizador histórico fuera del inventario); `test_core33_artifact_matches_accepted_portable_contract` (localizador histórico fuera del inventario).


### Q3 — ResourceWarning: hay temporales multipart sin cerrar en tests que llaman a la vista sin handler…

**Estado:** bounded-fixed

**Problema original:** `ResourceWarning`: hay temporales multipart sin cerrar en tests que llaman a la vista sin handler (`test_views_multipart_body_bound.py`, `test_view_layer_audit.py`). Es higiene de tests. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 219. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 277; la [tarea T16/R09c](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** prueba de vista directa deja temporal multipart sin cerrar. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Solicitud/preparación concreta reducida:**
```json
{"test": "direct view", "exception": "during assertion", "temporary_file": "owned by test"}
```

**Antes (ilustrativo):**
```json
{"file_closed": false}
```

**Después (observado/actual):**
```json
{"file_closed": true, "mechanism": "finally cleanup"}
```

**Cómo se llegó al resultado:**
1. Las pruebas directas de upload/ASGI cierran sus temporales en rutas sanas y excepcionales. El warning observado era propiedad del test, no fuga de producción demostrada.
2. El resultado aceptado consta, pero no se estableció un único commit causal de producción para toda esta fila compuesta; un test modificado no lo demuestra por sí solo.
   La corrección de propiedad de temporales pertenece solo a tests: commit `e1f29e9430725efa2d1f240140b5ee5ab6ae4882`; no demuestra fuga de producción.
3. Límite comprobado: Los tests cierran sus propios temporales incluso ante excepción; no se observó ResourceWarning ni se probó una fuga de producción.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   - [tests/test_views_multipart_body_bound.py](tests/test_views_multipart_body_bound.py): `test_asgi_chunked_multipart_over_the_cap_is_refused` (definición modificada en AST); `test_wsgi_undeclared_multipart_is_refused` (definición sin cambios); `test_declared_multipart_under_the_cap_still_runs` (definición sin cambios); `test_asgi_spoofed_low_content_length_is_refused` (definición sin cambios); `test_wsgi_spoofed_low_content_length_never_reaches_the_view` (definición sin cambios); `test_asgi_undeclared_multipart_under_the_cap_is_not_a_length_refusal` (definición sin cambios); `test_undeclared_multipart_is_untouched_when_the_guard_is_off` (definición sin cambios).


### Q4 — Tests que faltan (agrupados por hallazgo)

**Estado:** recommendation

**Problema original:** Tests que faltan (agrupados por hallazgo) [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 221–233. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 278; la [tarea T03–T16](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** matriz de regresión propuesta repite otros ID. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"interpreted as new independent defects"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"mapped as coverage work under existing IDs"
```

**Cómo se llegó al resultado:**
1. La matriz de regresión se vinculó a IDs de comportamiento existentes; un título de cobertura no exige parche runtime independiente. Los tests añadidos se atribuyen a cada caso.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Se trazó la matriz a hallazgos existentes sin crear ID de bug adicional; cobertura nueva solo se atribuye cuando existe prueba concreta.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### Q5 — Organización de tests: 32 archivos se nombran por la historia del proceso (test_nested_child_round4..7,…

**Estado:** recommendation

**Problema original:** Organización de tests: 32 archivos se nombran por la historia del proceso (`test_nested_child_round4..7`, `test_track2_*`, `test_optimizer_phase_c/d/e`, `test_wu13_*`, `test_audit_*`, `test_v130_cover_gaps`…) y no por comportamiento. Consolidarlos por feature facilita encontrar la cobertura de algo concreto. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 235. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 279; la [tarea T16](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** nombres históricos de tests dificultan descubrimiento. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"name considered a defect"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"no runtime change; naming review pending"
```

**Cómo se llegó al resultado:**
1. No se renombraron tests históricos solo por descubribilidad: un rename puede romper referencias de colección sin cambiar comportamiento. La organización queda aparte.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: No se renombraron archivos por estética durante la reparación; la sugerencia de organización queda para revisión separada.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### Q6 — Mega-módulos: types.py (4.142 líneas), utils.py (3.938), views.py (2.475), pagination.py (2.058) y…

**Estado:** recommendation

**Problema original:** Mega-módulos: `types.py` (4.142 líneas), `utils.py` (3.938), `views.py` (2.475), `pagination.py` (2.058) y `native_schema.py` (1.790). Propuesta: `types/{object,list,input,model,polymorphic}.py`, `optimizer/{only,prefetch,windows}.py`, `views/{base,cache,auth}.py`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 238. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 280; la [tarea T16](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** módulo largo sin fallo conductual demostrado. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"assume split required for correctness"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"no split adopted on size alone"
```

**Cómo se llegó al resultado:**
1. La longitud de módulos no justificó extracción amplia de rutas sensibles a compatibilidad. No se dividieron en masa sin alcance y prueba de conservación.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: No se hizo una refactorización masiva sin alcance ni regresión demostrada; tamaños históricos son contexto, no autorización.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### Q7 — Duplicación

**Estado:** recommendation

**Problema original:** Duplicación: [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 239–242. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 281; la [tarea T02/T05/T10/T16](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** duplicación sugerida de walkers, mutaciones y vistas. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"delete/merge as obvious dead duplication"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"retain pending caller/contract review"
```

**Cómo se llegó al resultado:**
1. Los candidatos de walkers y vistas/mutaciones se asociaron a arreglos C2, A9, A1 y L-C3, no se fusionó toda duplicación. Abstracciones restantes exigen análisis de llamadores.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Las duplicaciones se relacionaron con C2/A9/A1/L-C3; no se fusionaron rutas sin verificar llamadores y compatibilidad.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### Q8 — Código muerto

**Estado:** negative-limited

**Problema original:** Código muerto: [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 243–248. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 282; la [tarea T16](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** lista de símbolos supuestamente muertos. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"remove without caller check"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"live view path retained; other symbols unproved"
```

**Cómo se llegó al resultado:**
1. MUTATION_ERRORS_FLAG supuestamente muerto conserva ruta viva de rollback en GraphQLView. No se borró ningún símbolo por lista especulativa; otras eliminaciones necesitan prueba de llamadas y compatibilidad.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: MUTATION_ERRORS_FLAG tiene ruta viva; las demás eliminaciones requieren análisis de referencias y compatibilidad. No se borró código por sospecha.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** MUTATION_ERRORS_FLAG tiene ruta viva; las demás eliminaciones requieren análisis de referencias y compatibilidad. No se borró código por sospecha.


### Q9 — Nombres y comentarios heredados de graphene (graphene_cls, "graphene parity") en código que ya no depende de…

**Estado:** recommendation

**Problema original:** Nombres y comentarios heredados de graphene (`graphene_cls`, "graphene parity") en código que ya no depende de graphene. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 249. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 283; la [tarea T16](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** nombres heredados de Graphene en superficie compatible. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"assume rename is mandatory fix"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"no compatibility name removed"
```

**Cómo se llegó al resultado:**
1. Los nombres históricos de Graphene permanecen porque su compatibilidad no se deduce muerta por el nombre. Limpiar comentarios no autorizó rename público incompatible.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Los nombres históricos permanecen; limpiar comentarios no justifica romper nombres públicos o pruebas heredadas.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### Q10 — Nulabilidad: todos los campos no-relación salen nullable aunque sean null=False. Ofrecer un opt-in para derivar !

**Estado:** decision-deferred

**Problema original:** Nulabilidad: todos los campos no-relación salen nullable aunque sean `null=False`. Ofrecer un opt-in para derivar `!`. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 250. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 284; la [tarea T16](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** propuesta SDL non-null desde Django null=False. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"GraphQL output still nullable"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"unchanged until SDL policy approved"
```

**Cómo se llegó al resultado:**
1. El SDL no deriva GraphQLNonNull automáticamente de Django null=False. Proyectarlo en general cambia propagación de errores; sigue siendo decisión opt-in.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: El SDL no cambia automáticamente; hacer campos non-null puede propagar errores y necesita decisión explícita de compatibilidad.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** El SDL no cambia automáticamente; hacer campos non-null puede propagar errores y necesita decisión explícita de compatibilidad.


### P1 — 1. Antes de publicar 4.0.0: arreglar C1 (Decimal) con su test, y ejecutar uv sync en local

**Estado:** recommendation

**Problema original:** 1. Antes de publicar 4.0.0: arreglar C1 (Decimal) con su test, y ejecutar `uv sync` en local. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 256–265. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 285; la [tarea T01–T17](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** lista de prioridades y sugerencias de publicación. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"reat each plan item as new finding"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"no extra ID or release action"
```

**Cómo se llegó al resultado:**
1. Las prioridades se vincularon a IDs existentes, sin autorizar uv sync, release/publicación, predeterminados nuevos ni otro conteo de bugs. La entrega quedó fuera.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Las prioridades se vincularon a IDs previos; no crean bugs nuevos ni autorizan uv sync, publicación o cambio de predeterminados.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### N1 — La caché de firmas de permisos no se comparte entre usuarios: la clave incluye id(full) y el conjunto de permisos,…

**Estado:** negative-limited

**Problema original:** La caché de firmas de permisos no se comparte entre usuarios: la clave incluye `id(full)` y el conjunto de permisos, y el guard de reciclado de id funciona. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 269. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 286; la [tarea T17](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** firma de permisos compartida frente a aislamiento por usuario. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"audit claims never share cache entry"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"schema signature may match; response cache separate"
```

**Cómo se llegó al resultado:**
1. La caché de esquema usa firma efectiva de permisos, no objeto único por usuario. Se acotó la afirmación negativa universal; aquí no se probó aislamiento de caché de respuesta.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: La caché de esquema usa firma efectiva de permisos, no identidad única; no se infiere aislamiento universal de caché de respuesta.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** La caché de esquema usa firma efectiva de permisos, no identidad única; no se infiere aislamiento universal de caché de respuesta.


### N2 — Las permission classes fallan cerradas con anónimos y con resultados falsy; update/delete resuelven la fila vía…

**Estado:** negative-limited

**Problema original:** Las permission classes fallan cerradas con anónimos y con resultados falsy; `update`/`delete` resuelven la fila vía `get_queryset`/`filter_queryset` antes de escribir. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 270. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 287; la [tarea T17](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** afirmación global fail-closed de permisos y mutaciones. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"assume all paths proven fail-closed"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"bounded paths only; universal guarantee unproven"
```

**Cómo se llegó al resultado:**
1. Las pruebas cubiertas no establecen toda identidad anónima/falsy ni cadena arbitraria update/delete. No se afirmó garantía fail-closed global desde ese subconjunto.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: No se declaró una prueba universal de permisos anónimos/falsy ni de toda cadena update/delete; se conserva evidencia limitada.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** No se declaró una prueba universal de permisos anónimos/falsy ni de toda cadena update/delete; se conserva evidencia limitada.


### N3 — La introspección anidada está bloqueada por MaxIntrospectionDepthRule de graphql-core

**Estado:** negative-limited

**Problema original:** La introspección anidada está bloqueada por `MaxIntrospectionDepthRule` de graphql-core. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 271. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 288; la [tarea T17](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** una consulta de introspección anidada rechazada. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"assume no DoS possible"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"one bounded query rejected; universal claim withheld"
```

**Cómo se llegó al resultado:**
1. Un rechazo de introspección anidada provino de validación graphql-core; MAX_QUERY_DEPTH de la biblioteca es otro límite. Una garantía DoS universal exige más pruebas.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: La regla de graphql-core rechazó una consulta acotada; MAX_QUERY_DEPTH propio es otro límite y no prueba seguridad universal.
4. Pruebas reales localizadas y procedencia de definiciones frente a la base:
   - [tests/test_depth_limit.py](tests/test_depth_limit.py): `test_within_limit_passes` (localizador histórico fuera del inventario); `test_exceeding_per_type_limit_errors` (localizador histórico fuera del inventario); `test_scalars_do_not_count` (localizador histórico fuera del inventario); `test_max_depth_zero_blocks_any_nesting` (localizador histórico fuera del inventario); `test_fragment_spread_does_not_bypass` (localizador histórico fuera del inventario); `test_inline_fragment_is_counted` (localizador histórico fuera del inventario); `test_most_restrictive_constraint_wins` (localizador histórico fuera del inventario); `test_global_default_from_setting` (localizador histórico fuera del inventario); `test_no_limit_configured_is_noop` (localizador histórico fuera del inventario); `test_object_type_stores_max_depth` (localizador histórico fuera del inventario); `test_list_type_stores_max_depth` (localizador histórico fuera del inventario); `test_serializer_type_forwards_max_depth_to_output_type` (localizador histórico fuera del inventario); `test_view_includes_depth_rule_with_standard_rules` (localizador histórico fuera del inventario); `test_each_operation_type_is_named_in_its_own_refusal` (localizador histórico fuera del inventario).

**Límite pendiente:** La regla de graphql-core rechazó una consulta acotada; MAX_QUERY_DEPTH propio es otro límite y no prueba seguridad universal.


### N4 — Las cachés de utils.py son de ámbito de petición: no hay memo global sin límite

**Estado:** contract

**Problema original:** Las cachés de `utils.py` son de ámbito de petición: no hay memo global sin límite. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 272. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 289; la [tarea T17](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** metadatos GFK cacheados por proceso. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"audit says request-local cache"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"process-global class metadata cache exists"
```

**Cómo se llegó al resultado:**
1. Los metadatos de tipo GenericForeignKey se cachean por proceso/clase, no por petición. Se corrigió la descripción sin reescribir otras cachés.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: Se corrigió la descripción: GFK usa metadatos de clase globales al proceso; no se cambiaron todas las cachés.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.


### N5 — La regex de format_graphql_error no es explotable (graphql-core trunca los valores)

**Estado:** negative-limited

**Problema original:** La regex de `format_graphql_error` no es explotable (graphql-core trunca los valores). [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 273. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 290; la [tarea T17](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** prueba finita de regex en format_graphql_error. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"assume all hostile strings safe"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"bounded result only; universal claim withheld"
```

**Cómo se llegó al resultado:**
1. Una prueba finita de regex en format_graphql_error no demuestra seguridad para toda cadena y forma de backtracking. Se conserva el caso ejercitado sin garantía global.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: No se confirmó una garantía universal de regex; una prueba finita solo respalda el caso ejercitado.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** No se confirmó una garantía universal de regex; una prueba finita solo respalda el caso ejercitado.


### N6 — Lint, tipos y el resto de la suite: limpios

**Estado:** negative-limited

**Problema original:** Lint, tipos y el resto de la suite: limpios. [Auditoría original](auditoria-django-graphex-4.0.0.md), líneas 274. La [guía](docs/audit-4.0.0.md) indexa el caso en la línea 291; la [tarea T17/R09a/R09b](odd/tasks/audit-400-remediation.md) fija el alcance.

**Contexto del ejemplo:** resultado local de lint/tipos/tests generalizado a CI. Los valores emparejados son ilustraciones reducidas, no salida recién ejecutada:

**Antes (ilustrativo):**
```json
"claim CI entirely clean"
```

**Después (observado/actual):** No se implementó un cambio para este alegato.
```json
"local zero only; historical ignored originals unknown"
```

**Cómo se llegó al resultado:**
1. La exploración local estricta acabó limpia tras atender hallazgos rastreados e históricamente ignorados. Faltan preimágenes originales y CI para afirmación histórica universal.
2. No se aceptó un cambio de producción para este alegato; se documenta el comportamiento vigente, la premisa contradicha o la política propuesta, no un arreglo ficticio.
3. Límite comprobado: La exploración local estricta quedó en cero tras arreglar 23 hallazgos rastreados y siete del perfil ignorado; imágenes originales y CI siguen desconocidas.
4. El índice congelado no ofrece una prueba primaria con nombre. Es una laguna de procedencia, no prueba de que no existan tests.

**Límite pendiente:** La exploración local estricta quedó en cero tras arreglar 23 hallazgos rastreados y siete del perfil ignorado; imágenes originales y CI siguen desconocidas.


## Qué se descartó, acotó o difirió deliberadamente

Una **premisa contradicha** no es lo mismo que una **política rechazada** o un **subcaso sin probar**. Las decisiones sin cambio conservan el contrato vigente; no deben contarse como arreglos invisibles ni llamarse automáticamente falsos positivos.

1. **Premisa contradicha o excesiva:** `L-E3` SITE-B mostró públicamente que el hook se ejecutó una vez y devolvió solo filas visibles; esa variante exacta no se reprodujo, sin probar otros caminos. `L-C8` esperaba que `page:-1` fuese la última página positiva corta, pero el contrato es una ventana final de tamaño fijo. `N4` «todas las cachés son por petición» era inexacto por los metadatos GFK globales al proceso. `Q8` no permite borrar `MUTATION_ERRORS_FLAG`: tiene ruta viva. `L-C11` nombraba `@title`, no registrado; ese hallazgo no demostró defecto en `@title_case` ni `@truncate`.
2. **Contrato documentado, no arreglo general:** `M-D5` separa la cadena JSONField del scalar `JSONString` que decodifica por diseño; `M-U4` separa señales automáticas tras commit de broadcast manual inmediato y operaciones bulk sin señal; `L-C6` distingue miss, hit y petición con cookie; `L-C13` separa DateTime naive de `@date` en zona activa; `M-S3` explica middleware de introspección opt-in. No implican cambio de predeterminado.
3. **Política incompatible sin aprobar:** no se creó `strict_scope` global ni system check (`SD6`), `full_clean()`/upsert general (`A10`), rollback por `ok:false` o transacción entre bases (`A1`), `update_fields` universal (`M-D1`), nueva identidad Boolean vacía (`M-F3`), non-null SDL automático por `null=False` (`Q10`) ni ciclo de vida/evicción de registro dinámico (`L-M1`). Cada tema necesita decisión específica. Rechazar una política no significa que el riesgo original fuese imaginario.
4. **Recomendación, no defecto:** `Q4–Q7`, `Q9` y `P1` son cobertura, organización, refactorización y prioridad. No autorizan renombrar símbolos compatibles, dividir módulos por tamaño, ejecutar `uv sync`, publicar ni cambiar runtime de más.

## Descubrimientos adicionales fuera de los 100 ID originales

- **R09d — efecto de salida de producción:** una mutación generada rechazada podía dejar una salida visible en el registro según orden de declaración. La corrección acotada distinta es `b84d359` (identidad completa en Git local); no es solo el conflicto `A4` ni rediseño global del registro.
- **T16g — fuga de fixture, no defecto de producto:** el par de esquemas cacheado por defecto se filtraba entre tests aislados, reproducido en la base con semilla `1823552487`. `3cefed7131c6` lo restituyó después del scope. Afecta fiabilidad de prueba, no añade un bug original.
- **L-S1 F1–F3 — candidato intermedio frente a estado final:** un traspaso anterior estaba sin commit entonces; después `7ec2264c763859cd840e1475e8f4cec9a47ed8fc` y `1d26aa6478e2dd7e39585c349a466a34f41c1175` quedaron en el snapshot. La suite Redis histórica de una instancia aprobó **10 tests**, Lua y **ocho procesos** para una cuenta (**cinco concesiones, tres negativas**). Siete definiciones de ciclo de vida son ocho casos pytest porque una se parametriza dos veces. Controles tiene 18 definiciones y Playground añadió la prueba del predeterminado OFF. No hay prueba de HA/failover/partición, conteo global estricto ni plazo total duro; no se repitió Redis aquí.
- **R08m Float-set F1 — corrección local al campo:** `aeb74b8` corrigió overflow observado en la ruta exacta de conjuntos Float; no aprobó serialización Float global ni política de no finitos.
- **Predeterminados y premisas:** `M-S2` debe reconocer el tamaño de página 100 ya aceptado; `Q1` diferencia entorno raíz 3.2.13 obsoleto de 3.3.0 soportado. Son descripciones corregidas, no bugs adicionales. Fallos del harness y estados PARTIAL intermedios quedan como salvedades, no nuevos hallazgos de biblioteca.

### R09d: una declaración rechazada no debe reservar salida

Antes, una mutación generada con operación inválida ya había creado y registrado una salida; otra salida pública válida del mismo modelo podía chocar con ese efecto residual. `b84d359` movió la búsqueda/creación de salida **después** de validar operaciones en `django_graphex/mutation.py`: el rechazo deja libre el hueco. `tests/core/test_invalid_mutation_registry_side_effect.py` documenta este límite de declaración. Es un defecto de orden de producción, no rediseño global de Registry ni la guarda A4.

```json
{"request": "generate mutation with unknown operation", "before": {"error": true, "output_registered": true}, "current": {"error": true, "output_registered": false}}
```

### T16g: fixture de pruebas, no comportamiento de biblioteca

El helper de tests sustituía Registry y el registro de salida global, pero conservaba `_default_schema_registries` cacheado. Un test posterior podía recibir el par temporal; la semilla `1823552487` lo reprodujo en la base. `3cefed7` borra el par cacheado al entrar en `isolated_default_pair()` y restituye el mismo objeto anterior en `finally`, también con excepciones y scopes anidados. `tests/core/test_schema_isolation.py` prueba esos caminos. No implica arreglo de producto ni nuevo bug de la auditoría.

```json
{"setup": "two isolated tests share process", "before": {"cached_pair": "temporary prior-test pair"}, "current": {"cached_pair": "exact pre-scope pair restored"}}
```

### L-S1 F1–F3: tres carreras del candidato corregidas antes de aceptación

F1: un lease adquirido antes de arrancar lentamente la fuente podía caducar antes del HTTP 200/primer frame, pero el candidato aún podía entregar datos. La ruta aceptada renueva tras arrancar la fuente y otra vez antes de leer el cuerpo; al perder propiedad cierra fuente y lease, con 503 previo al stream o error terminal seguro tras 200. `test_expired_initial_lease_never_delivers_application_data` parametriza arranque y primera lectura.

F2: un stream de resultados siempre listos podía saltarse la renovación ligada al timeout y emitir tras caducar. El bucle comprueba el plazo antes de esperar y después de cada espera, incluso si ya hay resultado; si falla la renovación lo retiene. `test_ready_events_still_renew_overdue_lease` y `test_overdue_ready_result_is_withheld_on_backend_error` cubren ese camino.

F3: cancelaciones repetidas durante una admisión Redis/Lua en curso podían liberar antes de confirmar el alta y dejar un token huérfano. `_acquire` espera a que termine la admisión subyacente y entonces libera el token propio; `test_repeated_cancellation_settles_admission_before_release` verifica el orden. Son correcciones aceptadas del candidato, no trabajo Redis ausente del snapshot. Las pruebas están en `tests/subscriptions/test_sse_lease_lifecycle.py`; las diez pruebas Redis reales son históricas y de una sola instancia.

```json
{"lease": {"backend": "empty fake Redis", "capacity": 1, "admission": "paused before Lua acquire commits", "cancellations": 2}, "before": {"release_before_acquire_commit": true, "orphan_slot_possible": true}, "current": {"acquire_commits_before_release": true, "remaining_slots": 0}}
```

### R08m F1: literal Float con overflow, solo en el campo

La coerción nativa de variables `GraphQLFloat` rechazaba valores no finitos, pero la ruta literal podía convertir `1e999` en infinito. Para `set[float]`/`typing.Set[float]` exactos, `aeb74b8` conserva los alias de campo supervivientes y comprueba con `math.isfinite` los elementos de lista **suministrados** antes del resolver y de las fábricas; overflow produce error del campo. Los defaults/fábricas fijos históricos omitidos conservan identidad y comportamiento anteriores. `tests/core/test_float_set_input.py::test_literal_overflow_rejects_even_with_malformed_legacy_defaults` compara ambos casos. No se cambió el escalar Float global ni toda política no finita.

```graphql
mutation { echo(payload: {amounts: 1e999}) { result } }
```
Resultado actual: error GraphQL del campo antes de `echo`; no se fabrica en silencio un conjunto finito.

## Pendientes y límites de prueba

Siguen abiertas quince áreas principales T03–T17. Las filas principales pendientes/limitadas de abajo **no** equivalen a bugs ni tareas. Nuevos predeterminados públicos, garantías globales de seguridad, semántica entre bases, SSE distribuido y publicación requieren autorización humana. La tabla muestra la pregunta acotada, no aprobación automática.

| Estado | ID y límite actual |
|---|---|
| `partial` | `A1`, `A2`, `A10`, `A13`, `SD1`, `SD2`, `M-S2`, `M-D1`, `M-D2`, `M-D3`, `M-D4`, `M-D6`, `M-F3`, `M-H4`, `M-U1`, `M-U2`, `M-U3`, `M-U6`, `L-C12`, `L-E3`, `L-E4`, `L-M2`, `L-M3`, `L-M4`, `L-S1` |
| `decision-deferred` | `L-M1`, `Q10` |
| `negative-limited` | `Q8`, `N1`, `N2`, `N3`, `N5`, `N6` |

Temas seleccionados: bytes retenidos de AST/caché y memoria agregada (`A2`); `ok:false`/multibase/sobrescritura (`A1`, `M-D1`, `M-D2`); relaciones y scope personalizados (`SD1`, `SD2`, `SD6`, `L-E3`); Boolean vacío (`M-F3`); SSE distribuido (`L-S1`); registros dinámicos (`L-M1`); contratos Float/JSON/DateTime y anotaciones (`M-D4`, `M-D6`, `M-U3`, `M-U6`, `M-D10`); afirmaciones negativas/de seguridad universales (`N1–N6`). Aunque exista prueba o corte aceptado, la pregunta principal conserva su propia revisión.

### Límites de evidencia que deben acompañar al informe

- Las cifras históricas de tests/cobertura corresponden a `8d93483`, no a una ejecución nueva ni gate de publicación. Los 10 Redis passed pertenecen al commit L-S1 aceptado antes; no se ejecutó Redis al redactar. Una instancia no demuestra failover/partición.
- El apéndice de pruebas compara definiciones AST entre base y snapshot, no casos pytest recolectados ni aprobación universal de cada test en cada corrida. Los nombres eliminados son diferencias históricas, no tests actuales. Para los 21 registros sin prueba primaria en el índice se buscaron cierres específicos cuando fue posible (`L-S1`, `M-U6`); falta de localizador no significa falta de cobertura.
- El índice anterior contiene narrativas profundas de diff para `C1`, `C2` y `A5`; este informe cotejó además ascendencia y rutas de producción para los commits de implementación asociados a cada capítulo y comprobó tests con nombre. Compartir un archivo de prueba no demuestra que se corrigiera todo subcaso original. Los casos sin commit causal único lo indican expresamente.
- No se infiere URL GitHub, prueba privada externa, tiempos de benchmark, resultado CI, aprobación de API, PR, push, tag ni publicación. Este complemento no forma parte del sitio publicado. El informe original sin rastrear y el seguimiento existente no se editaron.


## Apéndice A: cronología de commits

Los 167 commits con cambios de fuente o pruebas aparecen en orden de ascendencia desde la base de la función hasta el snapshot. Asuntos y rutas técnicas se conservan literalmente. Son commits históricos, no cambios hechos al redactar este informe. Coincidir en un commit no demuestra causalidad. El cierre final solo documental aparece aparte.

| Commit | Hora local (-04:00) | Asunto y rutas modificadas |
|---|---|---|
| `e31333468774344e176031d1241e25c2d1642dd3` | `2026-10-13T19:18:30-04:00` | fix(benchmarks): validate only canonical results; production: none; tests: tests/benchmarks/test_canonical_provenance.py. |
| `2943f4544fe0c56064895a35b8606effe50013be` | `2026-10-13T19:50:53-04:00` | fix(validation): reject cyclic fragment graphs before expansion; production: django_graphex/_fragment_cycles.py, django_graphex/cost.py, django_graphex/validation.py; tests: tests/test_cost_edges.py, tests/test_fragment_cycles.py, tests/test_fragment_fanout.py. |
| `c57485594f83244f0dd4fcfdc71165cfb7d4da02` | `2026-10-13T20:03:58-04:00` | docs(audit): complete C3 test docstring contract; production: none; tests: tests/test_fragment_cycles.py. |
| `92b1358f31a2973abe7a817b820d54775a9067a6` | `2026-10-13T20:26:38-04:00` | fix(optimizer): bound repeated fragment planning; production: django_graphex/utils.py; tests: tests/test_optimizer_fragment_fanout.py. |
| `7bec957180edcf138d50256777a9e1bfb196f2b5` | `2026-10-13T20:45:23-04:00` | fix(optimizer): replay ordered fragment effects; production: django_graphex/utils.py; tests: tests/test_optimizer_fragment_fanout.py. |
| `bd45a6546cbb70a3e4151b087ff51110eed00706` | `2026-10-13T21:04:05-04:00` | fix(output): serialize auto-derived decimal fields; production: django_graphex/core/output_compiler.py; tests: tests/core/test_decimal_output.py. |
| `dbabfde2f1367f869c88ed22cfe91ce267ba02ca` | `2026-10-13T21:22:17-04:00` | fix(output): retain decimal primary key nullability; production: django_graphex/core/output_compiler.py; tests: tests/core/test_decimal_output.py. |
| `ca6cfb72bb388783e02bec20e4b29795b78e3abf` | `2026-10-13T21:23:37-04:00` | test(converter): register relation target locally; production: none; tests: tests/test_converter.py. |
| `8f86dc8927eb66a62dcdcf8936c40b659d6e6ead` | `2026-10-13T21:58:46-04:00` | feat(bigint)!: use decimal strings for model big integers; production: django_graphex/core/__init__.py, django_graphex/core/fields.py, django_graphex/core/input_compiler.py, django_graphex/core/output_compiler.py, django_graphex/core/scalars.py, django_graphex/filtering/native_schema.py; tests: tests/core/test_bigint.py, tests/core/test_s_roots_d_converter_native_aware.py, tests/core/test_scalars.py. |
| `12a7506a8b83c75ee211e1174dca9c3fbdf748c2` | `2026-10-13T22:36:55-04:00` | fix(bigint): preserve relation ID and choice validation; production: django_graphex/core/fields.py; tests: tests/core/test_bigint.py. |
| `d27832188f55e72d88551c16e077032d633c9875` | `2026-10-13T23:43:46-04:00` | feat(output)!: preserve decimal precision by default; production: django_graphex/core/output_compiler.py; tests: tests/core/test_decimal_output.py, tests/core/test_s_roots_d_converter_native_aware.py, tests/test_converter.py, tests/test_converter_branches.py. |
| `4cc048bb02e5258ef30e8fe86d902a0ec356ac1e` | `2026-10-14T00:17:04-04:00` | docs(scalars): describe shared decimal output scalar; production: django_graphex/core/scalars.py; tests: none. |
| `84369e41431e16a6ebe53159c2b7b6fd3401b1db` | `2026-10-14T00:32:34-04:00` | fix(views): enforce body cap before response-cache work; production: django_graphex/views.py; tests: tests/test_views_body_cap_cache.py. |
| `441899a520778e03518d81816eef0ddbd00dab8a` | `2026-10-14T01:03:57-04:00` | feat(directives)!: cap replace output before allocation; production: django_graphex/directives/string.py, django_graphex/settings.py; tests: tests/test_replace_output_limit.py. |
| `f91022e7a00deda481e63c5b316cc9db003ae1a5` | `2026-10-14T01:42:01-04:00` | fix(view): roll back atomic mutations on GraphQL errors; production: django_graphex/views.py; tests: tests/test_views_atomic_errors.py. |
| `cc67be504f595053257e237b1296ad16d202f536` | `2026-10-14T02:01:53-04:00` | fix(docs): restore core settings table rows; production: none; tests: tests/test_settings_tables_contract.py. |
| `65e99d35bd3392a640619a089307a7977627b57f` | `2026-10-14T08:58:22-04:00` | fix(registry)!: reject conflicting public model outputs; production: django_graphex/registry.py, django_graphex/types.py; tests: tests/_schema_isolation.py, tests/core/test_decimal_output.py, tests/core/test_factory.py, tests/core/test_fg2_native_schema_compiler.py, tests/core/test_fields.py, tests/core/test_filter_input_name_pascalcase.py, tests/core/test_list_output_type.py, tests/core/test_native_root_compiler.py, tests/core/test_native_schema_assembly.py, tests/core/test_output_identity_invariant.py, tests/core/test_s8c_field_descriptor_graphene_free.py, tests/core/test_s_roots_a_descriptors.py, tests/core/test_s_roots_c_ok_errors_native.py, tests/core/test_s_roots_d_converter_native_aware.py, tests/core/test_s_roots_h_native_mutation_payload.py, tests/core/test_s_roots_j_filter_input_collision.py, tests/core/test_schema_lazy_fork.py, tests/core/test_schema_scoped_registry.py, tests/core/test_subscription_native_build.py, tests/core/test_types_objecttype.py, tests/core/test_window_prefetch_native.py, tests/core/test_wu12_schema_compiler_coverage.py, tests/core/test_wu9_modeltype_mutation_execution.py, tests/core/test_wu9_mutation_execution.py, tests/subscriptions/_transport_schema.py, tests/subscriptions/test_audit_defects.py, tests/subscriptions/test_capability_parity.py, tests/test_docs_types_samples.py, tests/test_optimizer_coverage.py, tests/test_optimizer_phase_c.py, tests/test_optimizer_phase_e.py, tests/test_ordering_provenance.py, tests/test_output_registration_conflict.py, tests/test_registry.py. |
| `ff4741e6f8c7b1787933a32fb902f692b03f8b41` | `2026-10-14T09:19:34-04:00` | docs(types): clarify canonical output registration; production: django_graphex/types.py; tests: none. |
| `93edfdd1773c7eb4f5ee0058a563d6ef5c1df07b` | `2026-10-14T09:46:49-04:00` | test(registry): isolate serializer conflict fixture; production: none; tests: tests/test_serializer_type_custom_fields.py. |
| `edb82a30dae7bd96b5a56627963746d6e87b00cd` | `2026-10-14T09:53:50-04:00` | fix(types): validate public output field selectors; production: django_graphex/types.py; tests: tests/test_output_selector_validation.py. |
| `a2f329d8bdeb84499c669b01e82c28bf88d971d7` | `2026-10-14T10:29:35-04:00` | fix(output): preserve reverse accessor selectors; production: django_graphex/types.py; tests: tests/test_output_selector_validation.py. |
| `4643f9aee80fbea833e637460c2576e9327a8604` | `2026-10-14T10:29:49-04:00` | test(cost): isolate view wiring schema; production: none; tests: tests/test_query_cost.py. |
| `34b37e6f014c8c6d3308dabc1427fbd68748eac6` | `2026-10-14T12:50:13-04:00` | fix(types)!: reject incompatible generated enum collisions; production: django_graphex/converter.py, django_graphex/core/compiler.py; tests: tests/core/test_choices_enum_name_collisions.py. |
| `0b267dab424c506ed85b080b2754a496c39ee6c1` | `2026-10-14T13:10:31-04:00` | fix(types): reuse equivalent choices enums regardless of order; production: django_graphex/converter.py; tests: tests/core/test_choices_enum_name_collisions.py. |
| `c3a35a741a769cbb90bc6846062f0800b1199f9b` | `2026-10-14T13:58:10-04:00` | fix(choices)!: reject ambiguous enum member names; production: django_graphex/converter.py; tests: tests/core/test_choices_enum_member_ambiguity.py, tests/test_converter_choices.py. |
| `da31d910ea45968a823fd0a32a5fe9a4f230fa32` | `2026-10-14T14:14:13-04:00` | docs(choices): document both enum build failures; production: django_graphex/converter.py; tests: none. |
| `a96ca179b90714f39c4b69a79ebb24255aa17578` | `2026-10-14T16:10:42-04:00` | feat(mutations)!: scope generated relation ID links; production: django_graphex/nested.py, django_graphex/utils.py; tests: tests/test_destination_link_scope.py, tests/test_nested_child_permissions.py. |
| `6c100c8515d5fe75a34bce090ae6712ac9efa28a` | `2026-10-14T16:15:13-04:00` | docs(mutations): clarify scoped nested link comments; production: django_graphex/nested.py; tests: none. |
| `6275b6ee351a23f4f6c395f14c0ac587e59b8cb8` | `2026-10-14T16:42:23-04:00` | fix(nested): preserve valid destination scope querysets; production: django_graphex/nested.py; tests: tests/test_destination_link_compatibility.py. |
| `dcdd25bc3b837593eab1c8784702848d958e9451` | `2026-10-14T16:44:15-04:00` | test(nested): cover malformed scoped relation identifiers; production: none; tests: tests/test_destination_link_compatibility.py. |
| `bb592ddb7c1e90e0300ee4be8f30252b2c19d6a6` | `2026-10-14T19:06:48-04:00` | fix(nested)!: require child update host for orphan adoption; production: django_graphex/nested.py; tests: tests/test_nested_sd4_orphan_scope.py. |
| `8521c023731cae50617d605bc294e6071a483074` | `2026-10-14T19:24:58-04:00` | docs(nested): complete child-link exception contract; production: django_graphex/nested.py; tests: none. |
| `f0b3126260224c62ff1422e1e8e86ba5d8bf11bb` | `2026-10-14T20:16:22-04:00` | fix(security): redact flat GFK targets in pruned schemas; production: django_graphex/core/_flat_gfk_scope.py, django_graphex/core/output_compiler.py, django_graphex/core/permission_signature_cache.py, django_graphex/core/schema_pruner.py, django_graphex/views.py; tests: tests/test_flat_gfk_pruned_security.py. |
| `ac72aa7b9ca4b4532c26535f43e569c1cda0503e` | `2026-10-14T20:54:26-04:00` | fix(subscriptions): resolve schema providers off the event loop; production: django_graphex/subscriptions/transports/sse.py, django_graphex/subscriptions/transports/ws.py; tests: tests/subscriptions/test_transport_cold_permissions.py. |
| `901c35bd9b754f6b21b6f61715c0f62ea0604d15` | `2026-10-14T21:39:56-04:00` | fix(subscriptions)!: isolate automatic notification failures; production: django_graphex/subscriptions/bindings.py; tests: tests/subscriptions/test_automatic_best_effort.py. |
| `c3edeb3f4082f7f3dac79bc7cd34864290ff75d2` | `2026-10-14T22:08:36-04:00` | docs(subscriptions): document propagated notification errors; production: django_graphex/subscriptions/bindings.py; tests: none. |
| `eee1a6dd2b7743763066d81f544e709c7c76d180` | `2026-10-14T22:58:41-04:00` | feat(input)!: evaluate factories per coerced object; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_input_compiler_lists_defaults.py, tests/core/test_input_factory_per_object.py. |
| `ef7f6b5ad5b9e711d36ab7d3c45694fc3c987906` | `2026-10-14T23:23:09-04:00` | fix(input): ignore factories of overwritten aliases; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_factory_per_object.py. |
| `480167af7d17354d477041f76a4a662b1814604e` | `2026-10-14T23:55:19-04:00` | fix(mutations): preserve reserved Django field names; production: django_graphex/core/backend.py, django_graphex/core/fields.py, django_graphex/core/input_compiler.py, django_graphex/core/validators.py; tests: tests/core/test_reserved_model_fields.py. |
| `9e36576513cf1e0ced46ad96a799666caa39a3f0` | `2026-10-15T00:20:43-04:00` | fix(inputs): preserve inherited hooks on reserved model fields; production: django_graphex/core/fields.py, django_graphex/core/validators.py; tests: tests/core/test_reserved_model_fields.py. |
| `0ea68ac4f120bc2bfedfde65c6e3fb7c97a7111e` | `2026-10-15T00:52:40-04:00` | fix(types)!: honor explicit interface field names; production: django_graphex/core/polymorphic_compiler.py, django_graphex/types.py; tests: tests/core/test_audit_forked_pair_and_field_names.py, tests/test_output_selector_validation.py. |
| `a64d7f58adc370ac250a4c61fc2c82e84eeb7c01` | `2026-10-15T01:11:12-04:00` | fix(types): scope explicit interface names to implementors; production: django_graphex/core/polymorphic_compiler.py, django_graphex/types.py; tests: tests/test_output_selector_validation.py. |
| `74146dd55f74108b9b3c4b5d913c2a21b36c550a` | `2026-10-15T08:23:19-04:00` | fix(mutations): redact blocked generated delete errors; production: django_graphex/mutation.py, django_graphex/types.py; tests: tests/test_generated_delete_security.py. |
| `54f68e53e1db6f8c20296e10b2f4d336a97a0880` | `2026-10-15T08:45:45-04:00` | docs(types): complete generated delete error contract; production: django_graphex/types.py; tests: none. |
| `4ec40e8403549b71531fb7d38cf884b6c90a6fbb` | `2026-10-15T09:08:47-04:00` | test: isolate reverse one-to-one classifier fixture; production: none; tests: tests/test_nested_edges.py. |
| `81f79492a3b5906687194cbf143ca483c80cfee9` | `2026-10-15T09:52:00-04:00` | feat(inputs): validate generated email fields; production: django_graphex/core/fields.py; tests: tests/core/test_email_input_validation.py. |
| `610162956ca645d85bf7e7749a19ada81aac055f` | `2026-10-15T10:12:20-04:00` | fix(inputs): validate email choice values without changing enum inputs; production: django_graphex/core/fields.py; tests: tests/core/test_email_input_validation.py. |
| `6bd37b2d9dcac7359f3f0c94fc47f65a350bac5f` | `2026-10-15T10:43:41-04:00` | fix(inputs): validate positive integer values before persistence; production: django_graphex/core/fields.py; tests: tests/core/test_positive_input_validation.py. |
| `ebe32b0a74ad388f66f8b9c66f73513ff6c28bde` | `2026-10-15T11:17:14-04:00` | fix(inputs): retain nullable positive choice enums; production: django_graphex/core/fields.py; tests: tests/core/test_positive_input_validation.py. |
| `8db3083585f44e65cbf5f7eba496f3b4e004e728` | `2026-10-15T12:02:41-04:00` | fix(mutations): redact unmapped integrity errors; production: django_graphex/mutation.py, django_graphex/nested.py, django_graphex/types.py; tests: tests/test_generated_delete_security.py, tests/test_generated_integrity_error_redaction.py. |
| `c4273e2b09624cfdd615e8f908abcb30ad2efb54` | `2026-10-15T12:56:08-04:00` | fix(filters): match explicit exact null against SQL NULL; production: django_graphex/filtering/translate.py; tests: tests/test_exact_null_filtering.py. |
| `53b3481fff2eed6eb1a0a7d5ee07cd85f8f975e8` | `2026-10-15T13:48:50-04:00` | fix(filtering): type numeric date parts as Int inputs; production: django_graphex/filtering/native_schema.py; tests: tests/test_datepart_filtering.py. |
| `342a4ab92b2797e142a325d11311495cfc5808e2` | `2026-10-15T14:38:44-04:00` | fix(filtering): match explicit AND branches across related rows; production: django_graphex/filtering/backend.py; tests: tests/test_and_many_filtering.py. |
| `4c3e4bbd0df9948c53eb3d2d4846064571934d10` | `2026-10-15T15:05:22-04:00` | fix(filtering): correlate nested to-many AND branches; production: django_graphex/filtering/backend.py; tests: tests/test_and_many_filtering.py. |
| `e18f02b8b15b7cdfaf1fad06adc545527f1f8026` | `2026-10-15T15:37:46-04:00` | fix(pagination): resume typed nested cursors; production: django_graphex/paginations/pagination.py; tests: tests/test_pagination_cursor_typed_http.py. |
| `55287677ba38739aa3885379e952b975b2640d24` | `2026-10-15T15:38:52-04:00` | test(pagination): cover typed cursor fallback branches; production: none; tests: tests/test_pagination_cursor_typed_http.py. |
| `c3a063aeaaa0e765d9b3d3dc7749168ec6f2c842` | `2026-10-15T16:17:35-04:00` | fix(pagination): reject invalid typed cursor values; production: django_graphex/paginations/pagination.py; tests: tests/test_pagination_cursor_typed_http.py. |
| `9ab95cb26b95af0fb2baae04c79108bdcbd1765f` | `2026-10-15T17:01:08-04:00` | fix(pagination): treat null page as first page; production: django_graphex/paginations/pagination.py; tests: tests/test_pagination_page_null_http.py. |
| `954a2036b53a540e4db9829b6373eb66b2570474` | `2026-10-15T17:37:56-04:00` | fix(filtering): disambiguate nested relation and primary-key lookups; production: django_graphex/filtering/translate.py; tests: tests/test_exact_null_filtering.py, tests/test_filtering_internals.py, tests/test_native_filtering.py, tests/test_relation_lookup_name_collision.py. |
| `5faeef718816e9e3fda12472f588da92ade02edf` | `2026-10-15T19:21:10-04:00` | fix(pagination): default omitted page sizes to 100; production: django_graphex/paginations/pagination.py, django_graphex/settings.py; tests: tests/core/_sdl_parity_seed.py, tests/core/test_relation_gfk_native.py, tests/core/test_relation_to_many_native.py, tests/core/test_relation_to_one_native.py, tests/test_default_page_size_http.py, tests/test_optimizer_coverage.py, tests/test_optimizer_perf.py, tests/test_optimizer_phase_c.py, tests/test_optimizer_phase_d.py, tests/test_optimizer_phase_e.py, tests/test_pagination_default_ordering.py, tests/test_query_cost.py, tests/test_query_optimization.py, tests/test_settings.py, tests/test_skip_include_directives.py, tests/test_track2_optimizer.py. |
| `7249e5e40b9a5cc225edac8dfc09b685889f9e73` | `2026-10-15T19:49:09-04:00` | docs(playground): align cursor default with app settings; production: none; tests: tests/test_playground_310_contract.py. |
| `c75ea72fb0576fb86b1dbe829d6e4b3f42c93933` | `2026-10-15T20:44:18-04:00` | fix(pagination): fail closed when negative-page count fails; production: django_graphex/paginations/pagination.py, django_graphex/paginations/utils.py; tests: tests/test_negative_page_count_error_http.py. |
| `f6e88d446f492324b5ec09f72c880c88842acb6d` | `2026-10-15T21:59:22-04:00` | fix(pagination): stabilize bounded model ties by primary key; production: django_graphex/fields.py, django_graphex/paginations/pagination.py; tests: tests/test_pagination_pk_tiebreak.py. |
| `d1a6a18c167451546f8cf8bb4c91614cbd18c492` | `2026-10-15T22:38:12-04:00` | fix(pagination): preserve effective queryset order before PK tie-break; production: django_graphex/fields.py, django_graphex/paginations/pagination.py; tests: tests/test_pagination_pk_tiebreak.py, tests/test_pagination_server_order.py. |
| `96e1f9efb0569d27a08235c84656cf6be100caf1` | `2026-10-16T00:02:16-04:00` | fix: enforce bound query cost before execution; production: django_graphex/views.py; tests: tests/test_cost_variable_http.py. |
| `bcd66860ced0d219ce5b64e618907078dd40a1fc` | `2026-10-16T00:27:03-04:00` | fix(cost): preserve cache on pre-execution mutation refusal; production: django_graphex/views.py; tests: tests/test_cost_mutation_cache.py. |
| `d9d2c40f7bb4af2fc2125f76d344c124f8a3df74` | `2026-10-16T01:10:50-04:00` | fix(cache): frame response cache request components; production: django_graphex/views.py; tests: tests/test_views_cache_key_framing.py. |
| `a401f9e25e6989ccb28571815931fc6baf624593` | `2026-10-16T02:31:11-04:00` | fix(http): classify unexpected production GraphQL errors; production: django_graphex/views.py; tests: tests/_native330_runtime_guard.py, tests/test_cost_mutation_cache.py, tests/test_generated_integrity_error_redaction.py, tests/test_http_internal_error_diagnostics.py. |
| `407060eb8f7a67373ae9a0bfaa50520457a95e4f` | `2026-10-16T02:39:31-04:00` | test(http): remove local audit runtime guard; production: none; tests: tests/_native330_runtime_guard.py, tests/test_http_internal_error_diagnostics.py. |
| `3e3af998e38dc2fe5630ee775acc5c91166c8e3f` | `2026-10-16T03:25:21-04:00` | test(security): remove checkout-bound runtime guards; production: none; tests: tests/test_generated_delete_security.py, tests/test_generated_integrity_error_redaction.py, tests/test_generated_security_test_portability.py. |
| `043811eefaec7c4662eb53672b994ec65f9ac545` | `2026-10-16T10:15:59-04:00` | fix(response): preserve zero and false during cleaning; production: django_graphex/utils.py; tests: tests/test_clean_response_http.py, tests/test_utils.py. |
| `cbfb9fb11ca45f6be45ef41e864f2f5fefa59e90` | `2026-10-16T10:34:30-04:00` | test(response): clarify cleaning regression docstrings; production: none; tests: tests/test_clean_response_http.py, tests/test_utils.py. |
| `69d326eecee9c71ffe19db64e9019812297c74a1` | `2026-10-16T11:21:55-04:00` | fix(cache): skip failed GraphQL response entries; production: django_graphex/views.py; tests: tests/test_success_response_cache.py, tests/test_views_cache_isolation.py. |
| `23c06e0b6b7d86f2b082b86a50e4a6d715a3e78e` | `2026-10-16T12:20:57-04:00` | fix(views): reject unsupported async HTTP execution; production: django_graphex/views.py; tests: tests/test_sync_async_http.py. |
| `e8d0cf9eb5e40c03d9a1b2ee8fb3a9d42e63f3e6` | `2026-10-16T12:50:39-04:00` | fix(http): close nested middleware coroutines on async refusal; production: django_graphex/views.py; tests: tests/test_sync_async_http.py. |
| `dd1cf898dd94d01e44ff7672e764ea6807cf2f7b` | `2026-10-16T13:14:28-04:00` | fix(http): preserve ignored middleware entries during async guard; production: django_graphex/views.py; tests: tests/test_sync_async_http.py. |
| `11bd843f010dce28a4a10af788d54ad058ecef5d` | `2026-10-16T13:42:31-04:00` | docs: clarify introspection middleware opt-in; production: none; tests: tests/test_introspection_docs.py. |
| `347b2ff7ac383bf791b795b6c51d9f825236ceeb` | `2026-10-16T14:25:21-04:00` | fix: preserve partial results on batch HTTP 400; production: django_graphex/views.py; tests: tests/test_batch_http_error_partial.py. |
| `9c431f68576d52d7fa263a0921d9cbb5ba7833dd` | `2026-10-16T14:55:25-04:00` | test(datepart): remove checkout-bound runtime guards; production: none; tests: tests/test_datepart_filtering.py, tests/test_datepart_test_portability.py. |
| `9fec11da77a76f697ff6365a6c0bc5ed6c33f4d7` | `2026-10-16T15:26:34-04:00` | fix: preserve view configuration validation under optimization; production: django_graphex/views.py; tests: tests/test_view_base.py. |
| `408e2aada51a39265fee6df727cdf33457d2447f` | `2026-10-16T16:01:03-04:00` | fix(views): classify fragmented introspection roots; production: django_graphex/views.py; tests: tests/test_introspection_fragments.py. |
| `bbc8e9ac28e180070b60ed254d0ca262bd9c843b` | `2026-10-16T16:03:22-04:00` | test(views): cover malformed introspection roots; production: none; tests: tests/test_introspection_fragments.py. |
| `0606b34613a5abd76d2df428da1ba8c3eb5ac625` | `2026-10-16T17:03:18-04:00` | docs(cache): clarify GET request body key hashing; production: django_graphex/views.py; tests: tests/test_views_cache_key_framing.py. |
| `0d4f3b7427360b894da40c0df91e613cb0ed5469` | `2026-10-16T17:55:26-04:00` | docs(pagination): clarify explicit None fallbacks; production: none; tests: tests/test_pagination_none_docs_contract.py. |
| `da9c3c4443dae605710b620b1d095f738d13ef53` | `2026-10-16T18:20:07-04:00` | docs(pagination): name configured startup default; production: none; tests: tests/test_pagination_none_docs_contract.py. |
| `316844e376f9585f873903a60d73eb25a39aeb58` | `2026-10-16T18:53:06-04:00` | fix(optimizer): plan merged root field nodes together; production: django_graphex/utils.py; tests: tests/test_optimizer_merged_field_nodes.py. |
| `961c018e2d089962679c65329ebdb6bff765ba26` | `2026-10-16T19:39:46-04:00` | fix(permissions): serve warm schemas during cold pruning; production: django_graphex/core/permission_signature_cache.py; tests: tests/test_permission_cache_lock_split.py. |
| `4df64c4ff7dadb0c61b82fb72324f72179af4fc0` | `2026-10-16T20:24:11-04:00` | fix(schema): isolate concurrent fork registration state; production: django_graphex/core/base.py, django_graphex/schema.py; tests: tests/core/test_schema_fork_threads.py. |
| `088b729a592bc4baae199f6ebacd15a0df129cfa` | `2026-10-16T20:34:02-04:00` | docs(tests): clarify fork regression contract; production: none; tests: tests/core/test_schema_fork_threads.py. |
| `3cefed7131c6d52f89a082a631df29ebc2228945` | `2026-10-16T21:27:54-04:00` | test(registry): restore cached default pair after isolated scopes; production: none; tests: tests/_schema_isolation.py, tests/core/test_schema_isolation.py. |
| `c8bb0dd2d7700eec80cadbab3ade0af4f3a655e8` | `2026-10-16T22:18:15-04:00` | fix(optimizer): batch GFK targets inside union fragments; production: django_graphex/utils.py; tests: tests/test_track2_optimizer.py. |
| `0c5e32065fc43799b36872ea6bc1cdaf9f007af7` | `2026-10-17T10:25:09-04:00` | fix: fail fast on model metadata enumeration errors; production: django_graphex/core/base.py, django_graphex/core/output_compiler.py, django_graphex/schema.py, django_graphex/types.py; tests: tests/core/test_metadata_enumeration_failures.py, tests/core/test_output_compiler_coverage.py. |
| `72fbcbdccecfb955ad71666b31ae7c02618803eb` | `2026-10-17T11:26:02-04:00` | fix(fields): surface source property getter errors; production: django_graphex/core/descriptors.py; tests: tests/core/test_source_property_attribute_error.py. |
| `18f4a67a947822047b5423e597d3c53d8dec0498` | `2026-10-17T11:28:31-04:00` | test(fields): keep non-property source absence nullable; production: none; tests: tests/core/test_source_property_attribute_error.py. |
| `7fb4c121dca116d9e0192e87d744f555444c1c27` | `2026-10-17T11:50:38-04:00` | fix(fields): recognize wrapped Python property failures; production: django_graphex/core/descriptors.py; tests: tests/core/test_source_property_attribute_error.py. |
| `e04394b6fcc4b4ac02e31793e7e6479fea785e9c` | `2026-10-17T13:25:40-04:00` | fix(subscriptions): log suppressed delivery close errors; production: django_graphex/subscriptions/delivery.py; tests: tests/subscriptions/test_delivery_runtimeerror_diagnostic.py. |
| `a2ff209469f1c642fff20ebf78c3c4019db1dd5b` | `2026-10-17T18:14:47-04:00` | fix(mutation): track native field identity by live instance; production: django_graphex/core/mutation.py, django_graphex/core/schema_compiler.py, django_graphex/mutation.py, django_graphex/types.py; tests: tests/core/test_native_field_identity_lifetime.py. |
| `14720eab7d6662c4ce9f3ee56f1b7740133e1c08` | `2026-10-17T19:06:10-04:00` | fix(enum): synchronize cached enum construction; production: django_graphex/converter.py, django_graphex/core/compiler.py, django_graphex/registry.py; tests: tests/core/test_enum_cache_concurrency.py. |
| `13b2e6b4cdfd7489210267a5f6b5e3f35ec49ac4` | `2026-10-17T21:52:18-04:00` | fix(registry): serialize cold registry and list creation; production: django_graphex/registry.py, django_graphex/types.py; tests: tests/core/test_registry_creation_concurrency.py. |
| `9268da4033901e5a76daf6a3c84ac34c860dae0f` | `2026-10-17T22:42:12-04:00` | fix(subscriptions): release WebSocket ID before complete; production: django_graphex/subscriptions/transports/ws.py; tests: tests/subscriptions/test_ws_completion_reuse.py. |
| `fe545832513244bdddf2d35cea4cc845fc34cad9` | `2026-10-17T23:12:47-04:00` | fix(subscriptions): clean up groups after cancelled startup; production: django_graphex/subscriptions/source.py; tests: tests/subscriptions/test_startup_cleanup.py. |
| `514def143c42d6dad082e4590fb9edce813c90d6` | `2026-10-17T23:24:11-04:00` | fix(subscriptions): preserve retry after failed group join; production: django_graphex/subscriptions/source.py; tests: tests/subscriptions/test_startup_cleanup.py. |
| `ace6638e65f70843d123263f7ea09b7c780a595b` | `2026-10-17T23:57:16-04:00` | fix(directives): await resolver values before transformation; production: django_graphex/middleware.py; tests: tests/test_async_directive_middleware.py. |
| `031299c46e3127c080a3554f0c708b01147ad7a2` | `2026-10-18T00:16:53-04:00` | fix(directives): defer async wrapper allocation until awaited; production: django_graphex/middleware.py; tests: tests/test_async_directive_middleware.py. |
| `7a1dfe3b8406a15fc1fdd2b7221196181449e350` | `2026-10-18T00:39:45-04:00` | fix(inputs): warn on unsupported typing fallbacks; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py. |
| `34e03d39838fb6251322b32001266f9ec97cf814` | `2026-10-18T01:19:28-04:00` | docs(tests): complete tracked regression docstrings; production: none; tests: tests/core/test_metadata_enumeration_failures.py, tests/core/test_schema_fork_threads.py, tests/core/test_schema_isolation.py, tests/core/test_source_property_attribute_error.py, tests/test_optimizer_merged_field_nodes.py, tests/test_permission_cache_lock_split.py, tests/test_track2_optimizer.py. |
| `bf1163e639b680d76c4101f7524c949b7f411992` | `2026-10-18T02:03:53-04:00` | fix(subscriptions): bind automatic notifications to write alias; production: django_graphex/subscriptions/bindings.py; tests: tests/subscriptions/test_routed_on_commit.py. |
| `c408989f75d4d4f5729edd5296d93c36108f8efe` | `2026-10-18T02:33:24-04:00` | fix(nested): use parent write alias for atomic writes; production: django_graphex/nested.py; tests: tests/test_routed_nested_atomic.py. |
| `41fbeec734249c6e14c3402703e784c6cce3d490` | `2026-10-18T03:00:10-04:00` | docs(nested): qualify routed rollback contract; production: django_graphex/nested.py; tests: tests/test_routed_nested_atomic.py. |
| `6983455ea0eedb16f5a7f582604c8340bcc6a09c` | `2026-10-18T03:36:52-04:00` | fix(subscriptions): match Decimal filters against event snapshots; production: django_graphex/subscriptions/mixins.py; tests: tests/subscriptions/test_decimal_snapshot_filter.py. |
| `6df731e0d01b67997bf2fa6de457c372f4a33855` | `2026-10-18T04:06:31-04:00` | fix(subscriptions): match valid wide Decimal snapshots; production: django_graphex/subscriptions/mixins.py; tests: tests/subscriptions/test_decimal_snapshot_filter.py. |
| `e1f29e9430725efa2d1f240140b5ee5ab6ae4882` | `2026-10-18T04:44:45-04:00` | test(uploads): close direct-view request resources; production: none; tests: tests/test_view_layer_audit.py, tests/test_views_multipart_body_bound.py. |
| `73b8f4ea976b994b50b469f93665af9a36a19c61` | `2026-10-18T05:09:43-04:00` | docs: clarify current GraphEx behavior boundaries; production: none; tests: tests/test_docs_current_behavior_boundaries.py. |
| `5eb905db4dc0014c79ae4347201b36be79871f99` | `2026-10-18T05:27:31-04:00` | docs: distinguish cache misses from cookie-free hits; production: none; tests: tests/test_docs_current_behavior_boundaries.py. |
| `32f2533ba0ad97fc97cf6e5680783c4323e26aa4` | `2026-10-18T05:58:05-04:00` | docs: publish bounded 4.0.0 audit disposition; production: none; tests: tests/test_audit_400_report_contract.py. |
| `22a284875e79257a27bbff0007c7fb517a554a75` | `2026-10-18T06:31:49-04:00` | docs: clarify bounded audit claim dispositions; production: none; tests: tests/test_audit_400_report_contract.py. |
| `a5f3a8382620464105375e21f7241107dc9f69fe` | `2026-10-18T06:52:58-04:00` | docs: correct four audit examples; production: none; tests: tests/test_audit_400_report_contract.py. |
| `73a85abbad61517dc62e05bb34d22ce9464db368` | `2026-10-18T13:20:45-04:00` | fix(scope): enforce destination querysets on automatic FK reads; production: django_graphex/core/output_compiler.py, django_graphex/fields.py, django_graphex/utils.py; tests: tests/test_relation_scope_hatch.py, tests/test_sd1_relation_read_scope.py, tests/test_sd1_reverse_accessor_scope.py. |
| `603a117f67a41502f93d6551dbc5355c592b23ca` | `2026-10-18T14:26:14-04:00` | fix(filters): scope forward FK traversals to visible destinations; production: django_graphex/fields.py, django_graphex/filtering/backend.py, django_graphex/filtering/translate.py, django_graphex/types.py; tests: tests/test_sd2_forward_fk_filter_scope.py. |
| `98ee5455268077c2bd63ffe0be683a1d56917fb3` | `2026-10-18T15:56:33-04:00` | fix(filters): scope reverse FK witnesses to visible children; production: django_graphex/filtering/backend.py, django_graphex/filtering/native_schema.py, django_graphex/filtering/translate.py; tests: tests/test_sd2_reverse_fk_filter_scope.py. |
| `39dc696ba1664256e5b921003a4421133899d127` | `2026-10-18T16:53:19-04:00` | fix(filtering): scope many-to-many destination witnesses; production: django_graphex/filtering/backend.py, django_graphex/filtering/native_schema.py, django_graphex/filtering/translate.py; tests: tests/test_sd2_m2m_filter_scope.py. |
| `0f64533aff4210b77f4b4659d74fa264f46cf283` | `2026-10-18T17:31:56-04:00` | fix(filtering): scope forward one-to-one destinations; production: django_graphex/filtering/backend.py; tests: tests/test_sd2_forward_o2o_filter_scope.py. |
| `8ebfd43fce7071660795398e70f90ed0e2359054` | `2026-10-18T18:24:01-04:00` | fix(security): scope automatic one-to-one output reads; production: django_graphex/core/output_compiler.py, django_graphex/types.py, django_graphex/utils.py; tests: tests/test_sd1_o2o_output_scope.py. |
| `0ee46b94bb391bb59c599f9e88af46ce0a8f0f1b` | `2026-10-18T19:43:58-04:00` | fix(security): scope automatic many-to-many outputs and counts; production: django_graphex/converter.py, django_graphex/fields.py, django_graphex/utils.py; tests: tests/test_sd1_m2m_output_scope.py. |
| `57e0aaba2de6954f6aa1dc10b4ea690d4e16a686` | `2026-10-18T21:48:22-04:00` | fix(nested): keep instance-routed creates atomic; production: django_graphex/nested.py; tests: tests/test_routed_nested_atomic.py. |
| `33ff8786e03901ef1ca9bf0e7f34c82ab2b0a0b5` | `2026-10-19T08:48:49-04:00` | fix(subscriptions): preserve native DateTime snapshots; production: django_graphex/subscriptions/mixins.py, django_graphex/subscriptions/resolvers.py, django_graphex/subscriptions/subscription.py; tests: tests/subscriptions/test_datetime_snapshots.py. |
| `f931cb95946dc7704714097873a2a2ab2c3e06e7` | `2026-10-19T09:39:41-04:00` | docs(audit): reflect local R09b docstring cleanup; production: none; tests: tests/test_audit_400_report_contract.py. |
| `ef598a7d3dca3b76974bdd0829991db895d984c1` | `2026-10-19T10:33:34-04:00` | fix(subscriptions): reject unoffered WebSocket subprotocols; production: django_graphex/subscriptions/transports/ws.py; tests: tests/subscriptions/test_ws_subprotocol.py, tests/test_audit_400_report_contract.py. |
| `98956fa142bca0d6b78a7402ff626270d4295afc` | `2026-10-19T11:42:16-04:00` | feat(subscriptions): add optional connection authentication hook; production: django_graphex/subscriptions/transports/ws.py; tests: tests/subscriptions/test_ws_on_connect.py, tests/test_audit_400_report_contract.py. |
| `7ec2264c763859cd840e1475e8f4cec9a47ed8fc` | `2026-10-19T20:56:21-04:00` | feat(subscriptions): add opt-in SSE heartbeat and user limits; production: django_graphex/settings.py, django_graphex/subscriptions/transports/_sse_lease.py, django_graphex/subscriptions/transports/sse.py; tests: tests/subscriptions/test_sse_controls.py, tests/subscriptions/test_sse_lease_lifecycle.py, tests/test_audit_400_report_contract.py. |
| `1ee78e2548dcb7fc4d466a1c702f1ae9e060671d` | `2026-10-19T22:19:26-04:00` | fix(subscriptions): preserve filtered delete notifications; production: django_graphex/subscriptions/bindings.py, django_graphex/subscriptions/source.py, django_graphex/subscriptions/subscription.py; tests: tests/subscriptions/test_delete_snapshot_matching.py, tests/test_audit_400_report_contract.py. |
| `c664db3fe7d727e073de7725564a9cbe8a49e0fa` | `2026-10-19T23:28:14-04:00` | fix(subscriptions): compare finite float snapshots numerically; production: django_graphex/subscriptions/mixins.py; tests: tests/subscriptions/test_float_snapshot_filter.py. |
| `1f97d24d06309309601e029eb21766dcd1da6e67` | `2026-10-20T01:11:46-04:00` | fix(directives): preserve null values in date formatting; production: django_graphex/directives/date.py; tests: tests/test_directive_date_null.py. |
| `35199aa09a2ce3331456accb72348171cb9b98e5` | `2026-10-20T01:54:04-04:00` | fix(directives): zero omitted time components in text dates; production: django_graphex/directives/date.py; tests: tests/test_directive_date_text_time.py. |
| `dc556059c5c06e5d21bcf63388535901ffe3979a` | `2026-10-20T10:30:25-04:00` | fix(directives): localize aware dates in absolute formats; production: django_graphex/directives/date.py; tests: tests/test_directive_date_text_time.py, tests/test_directive_date_timezone.py. |
| `9faf5be77ccba11e18822b1bfd44aba66241da89` | `2026-10-20T11:42:57-04:00` | fix(directives): interpret timezone-less text in the active zone; production: django_graphex/directives/date.py; tests: tests/test_directive_date_naive_timezone.py. |
| `2ca275cd475d209024d87ae1dee7cdb2fb7e1665` | `2026-10-20T12:17:47-04:00` | fix(directives): localize adjacent numeric zero offsets; production: django_graphex/directives/date.py; tests: tests/test_directive_date_timezone.py. |
| `4b82906b44a4af22fad7502c291f9baeb29ab371` | `2026-10-20T13:21:51-04:00` | fix(directives): normalize case values without renaming schema; production: django_graphex/directives/string.py; tests: tests/test_directive_case_normalization.py, tests/test_directives_internals.py. |
| `e84090e6411e95b4a5a9b2378ee8c8d07164cb52` | `2026-10-20T14:34:08-04:00` | fix(directives): preserve numeric nulls without bypassing validation; production: django_graphex/directives/string.py; tests: tests/test_directive_numeric_null.py, tests/test_directives_internals.py. |
| `4a0760664ee6806a1fa8c07211a5501256bd65ef` | `2026-10-20T16:02:02-04:00` | fix(scalars): preserve null slots for omitted JSON variables; production: django_graphex/core/scalars.py; tests: tests/test_audit_400_report_contract.py, tests/test_json_raw_missing_list_null.py. |
| `3a7f2da0ac65e49d2fde02d403dbe95de664f143` | `2026-10-20T16:34:32-04:00` | fix(scalars): reject non-finite raw JSON inputs; production: django_graphex/core/scalars.py; tests: tests/test_json_nonfinite_input.py. |
| `03cd107e028dd096a759e95b5bbb4f98dde15c2c` | `2026-10-20T17:24:33-04:00` | fix(directives): restrict transforms to field locations; production: django_graphex/directives/base.py; tests: tests/test_audit_400_report_contract.py, tests/test_directive_field_locations.py. |
| `5b1022bcb5649016afc1ebada00b8e941e713170` | `2026-10-20T20:39:22-04:00` | fix(directives): normalize non-finite floor errors; production: django_graphex/directives/numbers.py; tests: tests/test_audit_400_report_contract.py, tests/test_floor_nonfinite_error.py. |
| `0512657622e64c731db94a699693999865c34703` | `2026-10-20T23:05:14-04:00` | fix(lookups): distinguish malformed primary key IDs; production: django_graphex/fields.py, django_graphex/types.py, django_graphex/utils.py; tests: tests/test_audit_400_report_contract.py, tests/test_invalid_id_contract.py. |
| `276841a9f9ff1796153c6ca52194f20866067373` | `2026-10-20T23:58:18-04:00` | fix(views): preserve null data for execution errors; production: django_graphex/views.py; tests: tests/test_audit_400_report_contract.py, tests/test_http_execution_error_contract.py, tests/test_http_internal_error_diagnostics.py. |
| `dfb47a0078466b96eb59d9ccba150639db08e225` | `2026-10-21T09:20:54-04:00` | fix(uploads): enforce multipart file size limits; production: django_graphex/settings.py, django_graphex/views.py; tests: tests/test_audit_400_report_contract.py, tests/test_multipart_file_size_http.py. |
| `9760b29773e3f62e9afebe7ac878779398878256` | `2026-10-21T10:20:34-04:00` | fix(settings): reject negative batch body and cache limits; production: django_graphex/settings.py; tests: tests/test_audit_400_report_contract.py, tests/test_settings_minimum_zero.py. |
| `f982bb962cd44c2994d441481b85ce69c698bd5e` | `2026-10-21T11:08:20-04:00` | docs(cache): clarify CSRF cookie cache behavior; production: none; tests: tests/test_docs_current_behavior_boundaries.py, tests/test_views_cache_cookie_bypass.py. |
| `ebeb63ab665f650551470b3db107f8c98f28e87a` | `2026-10-21T12:48:40-04:00` | fix(pagination): normalize automatic null placement; production: django_graphex/fields.py, django_graphex/paginations/pagination.py; tests: tests/test_audit_400_report_contract.py, tests/test_docs_current_behavior_boundaries.py, tests/test_pagination_null_order_parity.py. |
| `b5e48232e4615b0ae5e1d4b29ed874f55a3f859b` | `2026-10-21T15:20:01-04:00` | feat(inputs): compile string literals as automatic enums; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_literal_string_enum_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `7d0165c2df1b3e0006b5a4fd28abf55bd2d4975b` | `2026-10-21T17:00:52-04:00` | feat(inputs): validate typed integer maps as JSON; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_typed_dict_json_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `f17e96f3738a0c33dd58e76b2a8594c8c45e9285` | `2026-10-21T18:14:26-04:00` | fix(schema): render representable fixed JSON defaults; production: django_graphex/core/input_compiler.py, django_graphex/core/scalars.py; tests: tests/benchmarks/test_harness_isolation.py, tests/core/test_json_fixed_default_metadata.py, tests/subscriptions/test_transport_import_without_settings.py, tests/test_docs_mutation_contract.py. |
| `75109ef83013bf0040b25b3f2e9398b702e077cc` | `2026-10-21T18:56:00-04:00` | fix(schema): expose valid JSON list default metadata; production: django_graphex/core/input_compiler.py; tests: tests/core/test_json_fixed_default_metadata.py, tests/core/test_json_list_default_metadata.py. |
| `b84d35979cebc46bf910ee1434310f2646afca0c` | `2026-10-21T19:25:21-04:00` | fix(mutations): avoid output registration for rejected declarations; production: django_graphex/mutation.py; tests: tests/core/test_invalid_mutation_registry_side_effect.py. |
| `fc7ac7b3cc4f899c2e9a43cc91b396cca6c79130` | `2026-10-21T22:25:29-04:00` | fix(inputs): support strict JSON maps with typing Dict; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_typed_dict_json_input.py, tests/test_docs_mutation_contract.py. |
| `b4c0e71e7cede1dc406ea7eb55c0aae8b1b57c8f` | `2026-10-22T10:16:25-04:00` | feat(inputs): validate string-valued dictionaries as strict JSON; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_typed_string_dict_json_input.py, tests/test_docs_mutation_contract.py. |
| `85f8dc30a9c70fc56903d0579037e0976ecf14c2` | `2026-10-22T11:43:14-04:00` | feat(inputs): compile nested lists of supported input types; production: django_graphex/core/input_compiler.py; tests: tests/core/test_recursive_input_lists.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `384e3cd8f1e5d9ca2d3d05829ddcc973fee10f35` | `2026-10-22T13:47:31-04:00` | feat(inputs): support exact integer-set input values; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_set_int_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `22caa45c5ad70e76f52016b54f5157cf5ff4350b` | `2026-10-22T14:54:09-04:00` | feat(inputs): support typing Set integer alias; production: django_graphex/core/input_compiler.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_set_int_input.py, tests/core/test_typing_set_int_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `7b702635ae1bf47220efa9d5f5bd7fd67d3258be` | `2026-10-22T16:55:34-04:00` | feat(inputs): support exact string-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_set_int_input.py, tests/core/test_string_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `c6bff24ba46d8ed1dbd2b756f0d0022dd1823a0c` | `2026-10-23T13:57:45-04:00` | feat(inputs): support exact boolean-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_boolean_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `aeb74b884b952d94740815b387efe3cc92e81a79` | `2026-10-23T15:16:54-04:00` | feat(inputs): support finite float-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_boolean_set_input.py, tests/core/test_float_set_input.py, tests/core/test_string_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `1d0c6c23d54613ed82dbab5c5e31435055262e2b` | `2026-10-23T16:00:10-04:00` | feat(inputs): support exact UUID-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_uuid_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `ca95f9039978693562e7c26294a2c3d9e7a0e9d3` | `2026-10-23T17:15:14-04:00` | feat(inputs): support finite Decimal-set inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_decimal_set_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `deddb61527c123de52e95d239af576da70709b1c` | `2026-10-23T20:42:12-04:00` | feat(inputs): support strict Boolean-map inputs; production: django_graphex/core/input_compiler.py, django_graphex/core/schema_pruner.py; tests: tests/core/test_boolean_dict_json_input.py, tests/core/test_input_typing_fallback_warnings.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `d66b1752449a0441bd06d6e0167f2790ab32c907` | `2026-10-23T21:35:15-04:00` | feat(inputs): support strict IntOrString unions; production: django_graphex/core/input_compiler.py, django_graphex/core/scalars.py; tests: tests/core/test_input_typing_fallback_warnings.py, tests/core/test_int_or_string_union_input.py, tests/test_audit_400_report_contract.py, tests/test_docs_mutation_contract.py. |
| `6463eb1f894692a305e81fe0a2454260a4d61bfe` | `2026-10-23T23:09:57-04:00` | docs(audit): resolve original silent typing fallback claim; production: none; tests: tests/test_audit_400_report_contract.py. |

Snapshot final solo documental: `8d93483d2fd654012a544ce68365baf1964056f3`, 2026-10-23 23:13:45 -04:00, `docs(audit): close original M-D10 disposition`. No integra los 167 registros con fuente/pruebas.


## Apéndice B: archivos de pruebas Python modificados

Inventario completo de 189 rutas Python del área de pruebas en la diferencia base-snapshot: 113 añadidas y 76 modificadas. Algunas rutas de apoyo (p. ej. esquema/settings del Playground) no definen test_; «archivo» indica una ruta del inventario, no necesariamente un módulo pytest. Diferencia AST: 918 definiciones añadidas, 14 eliminadas, 37 modificadas y 1066 sin cambios; no son casos recolectados por pytest. Las 61 añadidas/4 modificadas citadas por la guía son solo un subconjunto. Los nombres son exactos, incluso los eliminados que ya no están en el snapshot.

| Ruta | Cambio | Definiciones añadidas | Definiciones modificadas en AST | Definiciones eliminadas | Cantidad sin cambios |
|---|---:|---|---|---|---:|
| `examples/playground/blog/schema.py` [open](examples/playground/blog/schema.py) | M | — | — | — | 0 |
| `examples/playground/config/settings.py` [open](examples/playground/config/settings.py) | M | — | — | — | 0 |
| `examples/playground/tests/test_relation_scope_hatch.py` [open](examples/playground/tests/test_relation_scope_hatch.py) | M | `test_automatic_reverse_m2m_counts_visible_posts`<br>`test_the_auto_expanded_reverse_fk_is_scoped` | — | `test_the_auto_expanded_relation_beside_it_is_not_scoped` | 6 |
| `examples/playground/tests/test_shipped_defaults.py` [open](examples/playground/tests/test_shipped_defaults.py) | M | `test_optional_sse_controls_ship_off` | — | — | 7 |
| `examples/playground/tests/test_subscription_transports_e2e.py` [open](examples/playground/tests/test_subscription_transports_e2e.py) | M | — | `test_sse_subscription_delivers_post_create`<br>`test_ws_subscription_delivers_post_create` | — | 7 |
| `integration/live_redis/test_sse_live_redis.py` [open](integration/live_redis/test_sse_live_redis.py) | A | `test_public_sse_live_backend_unavailable_is_503_before_source`<br>`test_public_sse_live_cap_and_cleanup`<br>`test_public_sse_live_midstream_loss_is_generic_and_closes`<br>`test_public_sse_live_normal_source_completion_releases_lease`<br>`test_public_sse_live_source_start_failure_releases_lease`<br>`test_real_lua_crashed_owner_expires_without_release`<br>`test_real_lua_cross_process_cap`<br>`test_real_lua_double_cancellation_waits_for_commit_then_releases`<br>`test_real_lua_ownership_expiry_and_independent_accounts`<br>`test_real_lua_unknown_acquire_reply_releases_committed_token` | — | — | 0 |
| `tests/_schema_isolation.py` [open](tests/_schema_isolation.py) | M | — | — | — | 0 |
| `tests/benchmarks/test_canonical_provenance.py` [open](tests/benchmarks/test_canonical_provenance.py) | M | `test_copy_canonical_fixture_ignores_diagnostics`<br>`test_missing_canonical_file_still_fails_with_diagnostics`<br>`test_validator_ignores_unrelated_diagnostic_json` | — | — | 9 |
| `tests/benchmarks/test_harness_isolation.py` [open](tests/benchmarks/test_harness_isolation.py) | M | — | `test_graphex_mutation_sql_contract_counts_request_internal_queries` | — | 9 |
| `tests/core/_sdl_parity_seed.py` [open](tests/core/_sdl_parity_seed.py) | M | — | — | — | 0 |
| `tests/core/test_audit_forked_pair_and_field_names.py` [open](tests/core/test_audit_forked_pair_and_field_names.py) | M | `test_explicit_interface_name_is_shared_with_implementor` | — | — | 4 |
| `tests/core/test_bigint.py` [open](tests/core/test_bigint.py) | A | `test_auto_output_uses_decimal_string_bigint`<br>`test_automatic_bigint_filter_executes_orm_query`<br>`test_automatic_filter_lookups_use_bigint`<br>`test_bigint_accepts_only_string_literals`<br>`test_bigint_foreign_key_id_mutation_accepts_existing_wire_values`<br>`test_bigint_rejects_invalid_variables_before_resolver`<br>`test_explicit_bigint_primary_key_keeps_nonnull_wrapper`<br>`test_explicit_scalar_override_keeps_its_declared_contract`<br>`test_generated_input_parses_decimal_strings_to_python_int`<br>`test_generated_model_mutation_persists_exact_bigint`<br>`test_null_bigint_primary_key_propagates_nonnull_error`<br>`test_nullable_bigint_output_keeps_null`<br>`test_positive_bigint_numeric_choice_mutation_accepts_valid_enum`<br>`test_positive_bigint_validation_keeps_nonnegative_constraint`<br>`test_relation_ids_with_explicit_bigint_pk_keep_old_input_type`<br>`test_signed_minimum_and_out_of_range_output` | — | — | 0 |
| `tests/core/test_boolean_dict_json_input.py` [open](tests/core/test_boolean_dict_json_input.py) | A | `test_alias_and_permission_clone_keep_only_surviving_validator`<br>`test_boolean_map_variable_reaches_resolver`<br>`test_custom_equality_annotations_do_not_gain_boolean_map_contract`<br>`test_empty_map_and_optional_null_preserve_outer_rules`<br>`test_exact_boolean_map_uses_json_input`<br>`test_factory_omission_retains_malformed_output_but_invalid_input_stops_factory`<br>`test_field_selection_and_replacement_remove_stale_boolean_map_metadata`<br>`test_fixed_default_omission_and_explicit_same_object_have_distinct_policy`<br>`test_fixed_default_provenance_survives_permission_clone`<br>`test_legacy_dictionary_subclass_default_remains_printable`<br>`test_list_wrapped_boolean_map_keeps_existing_fallback`<br>`test_literals_accept_exact_bool_and_reject_numbers`<br>`test_malformed_fixed_nonobject_default_keeps_omission_policy`<br>`test_supplied_invalid_boolean_map_rejected_before_resolver`<br>`test_unprintable_fixed_dictionary_default_keeps_original_object`<br>`test_unrelated_dictionary_leaf_keeps_string_fallback` | — | — | 0 |
| `tests/core/test_boolean_set_input.py` [open](tests/core/test_boolean_set_input.py) | A | `test_alias_selection_replacement_and_pruning_project_metadata`<br>`test_approved_boolean_sets_have_list_introspection_without_warning`<br>`test_boolean_sets_publish_list_and_reach_resolver_as_set`<br>`test_custom_leaf_comparing_equal_to_bool_keeps_fallback`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_fixed_and_factory_defaults_keep_lifecycle`<br>`test_inline_singleton_empty_and_duplicates`<br>`test_invalid_native_boolean_literals_fail_before_resolver`<br>`test_invalid_native_boolean_variables_fail_before_resolver`<br>`test_optional_boolean_sets_keep_omission_and_null`<br>`test_other_set_leaves_and_nested_forms_keep_fallback`<br>`test_required_boolean_set_rejects_omission`<br>`test_variable_singleton_empty_and_duplicates` | — | — | 0 |
| `tests/core/test_choices_enum_member_ambiguity.py` [open](tests/core/test_choices_enum_member_ambiguity.py) | A | `test_ambiguous_members_reject_all_supported_choices_forms`<br>`test_ambiguous_members_reject_generated_input_and_filter`<br>`test_ambiguous_members_reject_public_schema_without_cache_pollution` | — | — | 0 |
| `tests/core/test_choices_enum_name_collisions.py` [open](tests/core/test_choices_enum_name_collisions.py) | A | `test_colliding_choice_descriptions_are_incompatible`<br>`test_compatible_same_name_reuses_registry_enum`<br>`test_distinct_registries_keep_colliding_names_isolated`<br>`test_filter_input_rejects_incompatible_enum`<br>`test_generated_create_input_rejects_incompatible_enum`<br>`test_incompatible_choices_collision_rejects_schema`<br>`test_reordered_compatible_choices_share_public_schema_and_inputs` | — | — | 0 |
| `tests/core/test_decimal_output.py` [open](tests/core/test_decimal_output.py) | A | `test_automatic_decimal_field_executes_as_exact_decimal`<br>`test_automatic_decimal_output_preserves_exact_text`<br>`test_automatic_decimal_primary_key_uses_decimal_nonnull`<br>`test_decimal_filter_literals_and_variables_remain_precise`<br>`test_decimal_primary_key_keeps_nonnull_and_exact_output`<br>`test_explicit_decimal_scalar_and_input_mapping_stay_precise`<br>`test_explicit_float_resolver_retains_legacy_numeric_contract`<br>`test_generated_create_mutation_returns_exact_decimal_output`<br>`test_null_decimal_primary_key_propagates_nonnull_error` | — | — | 0 |
| `tests/core/test_decimal_set_input.py` [open](tests/core/test_decimal_set_input.py) | A | `test_alias_selection_replacement_and_pruning_project_metadata`<br>`test_custom_leaf_comparing_equal_to_decimal_keeps_fallback`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_decimal_sets_publish_list_and_reach_resolver_as_set`<br>`test_fixed_and_factory_defaults_keep_lifecycle`<br>`test_inline_finite_singleton_empty_and_duplicates`<br>`test_invalid_native_variables_fail_before_resolver`<br>`test_malformed_legacy_defaults_stay_omittable_but_supplied_nonfinite_fails`<br>`test_native_finite_variables_reach_resolver_as_decimal_set`<br>`test_nonfinite_literals_fail_before_resolver`<br>`test_nonfinite_supplied_field_precedes_omitted_sibling_factory`<br>`test_nonfinite_variable_default_never_reaches_resolver`<br>`test_nonfinite_variables_fail_before_resolver`<br>`test_optional_decimal_sets_keep_omission_and_null`<br>`test_other_leaves_and_nested_forms_keep_fallback`<br>`test_pruned_clone_preserves_fixed_default_identity`<br>`test_required_decimal_set_rejects_omission` | — | — | 0 |
| `tests/core/test_email_input_validation.py` [open](tests/core/test_email_input_validation.py) | A | `test_email_syntax_preserves_optional_defaults_length_and_custom_rules`<br>`test_generated_email_choices_preserve_enum_and_validate_values`<br>`test_generated_email_input_rejects_invalid_syntax`<br>`test_nested_email_validation_rolls_back_parent_and_child`<br>`test_non_text_email_choice_reports_field_error`<br>`test_reserved_named_email_keeps_original_error_field` | — | — | 0 |
| `tests/core/test_enum_cache_concurrency.py` [open](tests/core/test_enum_cache_concurrency.py) | A | `test_compile_enum_shares_one_object_after_contended_miss`<br>`test_compile_schema_keeps_reset_and_build_in_one_transaction`<br>`test_compile_type_shares_one_object_after_contended_miss`<br>`test_native_choices_keep_serial_ambiguity_and_registry_isolation`<br>`test_native_choices_reject_incompatible_concurrent_definition`<br>`test_native_choices_reuse_one_object_after_contended_miss` | — | — | 0 |
| `tests/core/test_factory.py` [open](tests/core/test_factory.py) | M | — | — | — | 9 |
| `tests/core/test_fg2_native_schema_compiler.py` [open](tests/core/test_fg2_native_schema_compiler.py) | M | — | — | — | 6 |
| `tests/core/test_fields.py` [open](tests/core/test_fields.py) | M | — | — | — | 14 |
| `tests/core/test_filter_input_name_pascalcase.py` [open](tests/core/test_filter_input_name_pascalcase.py) | M | — | `test_filter_input_name_in_schema_type_map_is_pascalcase` | — | 1 |
| `tests/core/test_float_set_input.py` [open](tests/core/test_float_set_input.py) | A | `test_alias_selection_replacement_and_pruning_project_metadata`<br>`test_custom_leaf_comparing_equal_to_float_keeps_fallback`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_exact_float_sets_have_list_introspection_without_warning`<br>`test_fixed_and_factory_defaults_keep_lifecycle`<br>`test_float_sets_publish_list_and_reach_resolver_as_set`<br>`test_inline_numeric_singleton_empty_and_duplicates`<br>`test_invalid_native_float_literals_fail_before_resolver`<br>`test_invalid_native_float_variables_fail_before_resolver`<br>`test_literal_overflow_rejects_even_with_malformed_legacy_defaults`<br>`test_literal_overflow_rejects_through_alias_and_pruned_clone`<br>`test_native_numeric_variables_become_float_set`<br>`test_optional_float_sets_keep_omission_and_null`<br>`test_other_set_leaves_and_nested_forms_keep_fallback`<br>`test_overflowing_variable_default_never_reaches_resolver`<br>`test_required_float_set_rejects_omission` | — | — | 0 |
| `tests/core/test_input_compiler_lists_defaults.py` [open](tests/core/test_input_compiler_lists_defaults.py) | M | `test_default_factory_runs_per_coerced_object_without_sdl_default` | — | `test_default_factory_evaluated_once_and_present` | 20 |
| `tests/core/test_input_factory_per_object.py` [open](tests/core/test_input_factory_per_object.py) | A | `test_factory_failures_are_graphql_input_errors_without_private_text`<br>`test_factory_respects_variables_explicit_values_and_field_aliases`<br>`test_literal_field_overwriting_factory_alias_does_not_run_factory`<br>`test_model_derived_input_keeps_omitted_factory_field_absent`<br>`test_nested_inputs_and_inline_aliases_create_distinct_objects`<br>`test_omitted_factory_values_are_fresh_across_graphql_executions`<br>`test_overwritten_wire_alias_only_runs_effective_field_factory`<br>`test_permission_pruned_input_does_not_reinsert_hidden_factory_field`<br>`test_validated_data_factory_remains_a_model_validation_default` | — | — | 0 |
| `tests/core/test_input_typing_fallback_warnings.py` [open](tests/core/test_input_typing_fallback_warnings.py) | A | `test_public_input_mutation_warns_without_changing_wire_behavior`<br>`test_supported_annotations_do_not_gain_fallback_warnings` | — | — | 0 |
| `tests/core/test_int_or_string_union_input.py` [open](tests/core/test_int_or_string_union_input.py) | A | `test_alias_projection_and_permission_pruning`<br>`test_custom_equality_leaf_does_not_match_direct_union`<br>`test_custom_equality_outer_does_not_match_direct_union`<br>`test_direct_union_accepts_matching_literals`<br>`test_direct_union_preserves_variable_branch`<br>`test_direct_union_publishes_shared_scalar`<br>`test_direct_union_rejects_invalid_literal_before_resolver`<br>`test_direct_union_rejects_invalid_variable_before_resolver`<br>`test_factory_values_stay_fresh_and_bad_input_stops_sibling_factory`<br>`test_integer_variable_reaches_resolver_without_string_cast`<br>`test_legacy_dictionary_subclass_default_retains_old_printing`<br>`test_malformed_fixed_default_preserves_omission_and_printing`<br>`test_nullable_union_without_default_still_accepts_null`<br>`test_outer_nullable_direct_union`<br>`test_plain_string_input_is_not_split_or_cast`<br>`test_scalar_name_collision_reports_an_error`<br>`test_selected_and_replaced_fields_keep_final_wire_type`<br>`test_string_fixed_default_keeps_string_branch_in_schema`<br>`test_unapproved_wrapped_union_retains_string_fallback`<br>`test_valid_fixed_default_and_disabled_default_emission` | — | — | 0 |
| `tests/core/test_invalid_mutation_registry_side_effect.py` [open](tests/core/test_invalid_mutation_registry_side_effect.py) | A | `test_rejected_permission_host_does_not_register_user_output`<br>`test_rejected_permission_host_preserves_existing_output`<br>`test_unknown_operation_precedes_permission_error_without_output`<br>`test_valid_mutation_still_uses_one_public_output` | — | — | 0 |
| `tests/core/test_json_fixed_default_metadata.py` [open](tests/core/test_json_fixed_default_metadata.py) | A | `test_bare_json_default_roundtrips_nested_literal_and_pruned_schema`<br>`test_fixed_json_object_default_prints_and_introspects`<br>`test_ineligible_json_values_do_not_gain_metadata_or_new_validation`<br>`test_json_default_factory_is_not_frozen_in_sdl`<br>`test_mismatched_list_default_retains_prior_runtime_shape`<br>`test_non_name_json_default_keeps_runtime_without_invalid_sdl_promise`<br>`test_nullable_list_defaults_publish_metadata_and_preserve_elements`<br>`test_oversized_json_integer_default_preserves_public_runtime`<br>`test_surrogate_json_string_default_preserves_public_runtime` | — | — | 0 |
| `tests/core/test_json_list_default_metadata.py` [open](tests/core/test_json_list_default_metadata.py) | A | `test_empty_list_and_nested_pruned_default_remain_printable`<br>`test_ineligible_fixed_json_list_shapes_stay_internal`<br>`test_invalid_list_defaults_and_factory_keep_legacy_metadata`<br>`test_valid_fixed_json_list_default_prints_and_introspects` | — | — | 0 |
| `tests/core/test_list_output_type.py` [open](tests/core/test_list_output_type.py) | M | — | — | — | 5 |
| `tests/core/test_literal_string_enum_input.py` [open](tests/core/test_literal_string_enum_input.py) | A | `test_compiled_name_and_inherited_public_alias_define_enum_name`<br>`test_literal_defaults_and_factory_are_not_frozen_at_compile_time`<br>`test_member_collision_rejects_ambiguous_literals`<br>`test_public_mutation_uses_literal_enum_and_raw_resolver_value`<br>`test_wrapped_literal_alias_and_nested_input_keep_enum_values` | — | — | 0 |
| `tests/core/test_metadata_enumeration_failures.py` [open](tests/core/test_metadata_enumeration_failures.py) | A | `test_eager_field_recompile_keeps_uncaused_error_unchained`<br>`test_eager_field_recompile_retains_original_cause`<br>`test_lazy_schema_keeps_uncaused_configuration_error`<br>`test_lazy_schema_leaves_generic_type_error_untouched`<br>`test_model_derived_fields_identifies_model_and_preserves_cause`<br>`test_output_compiler_identifies_model_and_preserves_cause`<br>`test_public_schema_rejects_relation_metadata_failure` | — | — | 0 |
| `tests/core/test_native_field_identity_lifetime.py` [open](tests/core/test_native_field_identity_lifetime.py) | A | `test_current_registry_value_is_a_defensive_identity_source`<br>`test_live_native_field_survives_registry_slot_overwrite`<br>`test_model_mutation_builder_tracks_its_actual_native_field`<br>`test_modeltype_builder_tracks_its_actual_native_field`<br>`test_native_field_marker_expires_when_field_dies`<br>`test_stale_identity_key_cannot_admit_an_unrelated_field` | — | — | 0 |
| `tests/core/test_native_root_compiler.py` [open](tests/core/test_native_root_compiler.py) | M | — | — | — | 6 |
| `tests/core/test_native_schema_assembly.py` [open](tests/core/test_native_schema_assembly.py) | M | — | — | — | 14 |
| `tests/core/test_output_compiler_coverage.py` [open](tests/core/test_output_compiler_coverage.py) | M | `test_compile_output_fields_get_fields_exception_aborts_with_cause` | — | `test_compile_output_fields_get_fields_exception_fallback` | 26 |
| `tests/core/test_output_identity_invariant.py` [open](tests/core/test_output_identity_invariant.py) | M | — | — | — | 4 |
| `tests/core/test_positive_input_validation.py` [open](tests/core/test_positive_input_validation.py) | A | `test_custom_schema_preserves_nullable_positive_choice_enum`<br>`test_generated_positive_input_rejects_negative_before_sql`<br>`test_nested_positive_input_rejects_child_before_parent_persists`<br>`test_positive_choices_validate_stored_number_and_keep_enum`<br>`test_positive_field_error_preserves_earlier_sibling_write`<br>`test_positive_validator_preserves_null_and_reports_invalid_choice_value` | — | — | 0 |
| `tests/core/test_recursive_input_lists.py` [open](tests/core/test_recursive_input_lists.py) | A | `test_deep_map_alias_factory_and_permission_clone`<br>`test_deep_typed_maps_keep_strict_leaf_contract`<br>`test_deep_typed_maps_validate_when_defaults_are_not_emitted`<br>`test_ineligible_nested_json_defaults_keep_legacy_metadata`<br>`test_nested_bare_json_keeps_leaf_identity_and_single_list_parity`<br>`test_nested_integer_lists_use_recursive_graphql_wrappers`<br>`test_nested_json_fixed_default_and_factory_keep_runtime_shape`<br>`test_nested_list_nullability_and_singleton_coercion`<br>`test_nullable_nested_bare_json_fixed_defaults_remain_printable`<br>`test_supported_nested_input_and_literal_enum_leaves`<br>`test_typing_list_and_nullable_nested_map_elements`<br>`test_unsupported_nested_leaves_keep_legacy_fallback` | — | — | 0 |
| `tests/core/test_registry_creation_concurrency.py` [open](tests/core/test_registry_creation_concurrency.py) | A | `test_concurrent_list_misses_share_class_graphql_object_and_cache`<br>`test_explicit_list_registration_keeps_last_registration_wins`<br>`test_global_registry_concurrent_cold_calls_share_one_instance`<br>`test_global_registry_failed_construction_retries_and_reset_isolated`<br>`test_list_creation_is_scoped_to_each_model_and_registry` | — | — | 0 |
| `tests/core/test_relation_gfk_native.py` [open](tests/core/test_relation_gfk_native.py) | M | — | `test_choices_seed_sdl_byte_identical_and_enum_renders`<br>`test_seed_native_sdl_byte_identical_to_head_baseline` | — | 14 |
| `tests/core/test_relation_to_many_native.py` [open](tests/core/test_relation_to_many_native.py) | M | — | `test_seed_native_sdl_byte_identical_to_head_baseline` | — | 9 |
| `tests/core/test_relation_to_one_native.py` [open](tests/core/test_relation_to_one_native.py) | M | — | `test_seed_native_sdl_byte_identical_to_head_baseline` | — | 10 |
| `tests/core/test_reserved_model_fields.py` [open](tests/core/test_reserved_model_fields.py) | A | `test_existing_custom_base_config_and_dump_override_remain_active`<br>`test_generated_mutation_persists_reserved_field`<br>`test_inherited_mixed_hooks_preserve_modes_and_caller_base`<br>`test_inherited_model_config_hooks_use_original_field`<br>`test_internal_name_avoids_real_column_and_preserves_inline_validation`<br>`test_original_methods_remain_available_on_generated_class`<br>`test_reserved_default_and_partial_omission_keep_original_presence` | — | — | 0 |
| `tests/core/test_s8c_field_descriptor_graphene_free.py` [open](tests/core/test_s8c_field_descriptor_graphene_free.py) | M | — | — | — | 7 |
| `tests/core/test_s_roots_a_descriptors.py` [open](tests/core/test_s_roots_a_descriptors.py) | M | — | — | — | 12 |
| `tests/core/test_s_roots_c_ok_errors_native.py` [open](tests/core/test_s_roots_c_ok_errors_native.py) | M | — | — | — | 9 |
| `tests/core/test_s_roots_d_converter_native_aware.py` [open](tests/core/test_s_roots_d_converter_native_aware.py) | M | `test_native_scalar_sdl_preserves_approved_bigint_and_decimal` | `test_construct_fields_keeps_relation_descriptors_on_native` | `test_native_scalar_sdl_is_byte_identical_after_skip` | 7 |
| `tests/core/test_s_roots_h_native_mutation_payload.py` [open](tests/core/test_s_roots_h_native_mutation_payload.py) | M | — | — | — | 9 |
| `tests/core/test_s_roots_j_filter_input_collision.py` [open](tests/core/test_s_roots_j_filter_input_collision.py) | M | — | — | — | 4 |
| `tests/core/test_scalars.py` [open](tests/core/test_scalars.py) | M | `TestGdxScalarMap.test_has_8_custom_scalars` | `TestGdxScalarMap.test_singleton_identity`<br>`TestGdxScalarMap.test_total_size` | `TestGdxScalarMap.test_has_7_custom_scalars` | 85 |
| `tests/core/test_schema_fork_threads.py` [open](tests/core/test_schema_fork_threads.py) | A | `test_concurrent_fork_preserves_sibling_output_projections`<br>`test_fork_marker_is_nested_and_restored_after_error`<br>`test_serial_projected_list_keeps_its_node_type` | — | — | 0 |
| `tests/core/test_schema_isolation.py` [open](tests/core/test_schema_isolation.py) | A | `test_isolated_default_pair_restores_after_exception`<br>`test_isolated_default_pair_restores_each_nested_scope`<br>`test_isolated_default_pair_restores_prior_cache` | — | — | 0 |
| `tests/core/test_schema_lazy_fork.py` [open](tests/core/test_schema_lazy_fork.py) | M | — | — | — | 11 |
| `tests/core/test_schema_scoped_registry.py` [open](tests/core/test_schema_scoped_registry.py) | M | — | — | — | 8 |
| `tests/core/test_set_int_input.py` [open](tests/core/test_set_int_input.py) | A | `test_exact_set_int_prints_int_list`<br>`test_fixed_set_default_and_fresh_factory_keep_existing_lifecycle`<br>`test_graphql_singleton_coercion_yields_python_set`<br>`test_inline_set_int_values_use_the_same_boundary`<br>`test_invalid_inline_int_values_fail_before_resolver`<br>`test_invalid_variable_int_values_fail_before_resolver`<br>`test_optional_set_int_keeps_null_and_omission_defaults`<br>`test_other_set_forms_keep_legacy_fallback`<br>`test_permission_clone_keeps_only_surviving_set_conversion`<br>`test_set_field_uses_wire_alias_and_snake_resolver_name`<br>`test_set_int_variable_is_deduplicated_for_resolver` | — | — | 0 |
| `tests/core/test_source_property_attribute_error.py` [open](tests/core/test_source_property_attribute_error.py) | A | `test_absent_django_reverse_one_to_one_stays_nullable_through_property`<br>`test_custom_attribute_lookup_and_nested_required_propagation`<br>`test_explicit_resolver_precedes_source_and_method_body_error_is_unchanged`<br>`test_inherited_source_property_failure_preserves_required_propagation`<br>`test_source_absence_and_successful_dynamic_fallback_remain_nullable`<br>`test_source_property_attribute_error_surfaces_graphql_resolution_error`<br>`test_source_property_failure_keeps_safe_http_diagnostics`<br>`test_unrelated_descriptor_and_dynamic_absence_keep_legacy_null`<br>`test_wrapped_python_property_source_preserves_original_error` | — | — | 0 |
| `tests/core/test_string_set_input.py` [open](tests/core/test_string_set_input.py) | A | `test_alias_and_emitted_field_identity`<br>`test_approved_string_sets_have_list_introspection_without_warning`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_custom_string_set_leaf_comparing_equal_to_str_keeps_fallback`<br>`test_exact_string_sets_publish_list_and_reach_resolver_as_set`<br>`test_fixed_and_factory_defaults_keep_lifecycle`<br>`test_inline_singleton_empty_and_duplicates`<br>`test_invalid_native_string_literals_fail_before_resolver`<br>`test_invalid_native_string_variables_fail_before_resolver`<br>`test_native_string_values_still_become_a_python_set`<br>`test_only_exclude_include_and_replacement_remove_stale_conversion`<br>`test_optional_string_sets_keep_omission_and_null`<br>`test_permission_clone_projects_only_surviving_string_set_metadata`<br>`test_required_string_set_rejects_omission`<br>`test_unapproved_set_leaves_and_nested_forms_keep_fallback`<br>`test_variable_singleton_empty_and_duplicates` | — | — | 0 |
| `tests/core/test_subscription_native_build.py` [open](tests/core/test_subscription_native_build.py) | M | — | — | — | 5 |
| `tests/core/test_typed_dict_json_input.py` [open](tests/core/test_typed_dict_json_input.py) | A | `test_alias_nested_defaults_and_pruned_fields_use_final_input_surface`<br>`test_inline_typed_map_and_nullability_keep_graphql_coercion`<br>`test_invalid_typed_map_factory_is_rejected_before_resolver`<br>`test_invalid_typed_map_variable_is_rejected_before_resolver`<br>`test_permission_scoped_clone_keeps_only_surviving_typed_map_checks`<br>`test_production_http_preserves_deliberate_graphql_input_error`<br>`test_relation_replacement_does_not_keep_typed_map_validator`<br>`test_typed_dictionary_accepts_json_object_before_mutation`<br>`test_typing_alias_http_error_is_safe`<br>`test_typing_alias_invalid_map_stops_mutation`<br>`test_typing_alias_wrappers_defaults_and_pruned_clone`<br>`test_typing_dict_alias_uses_strict_json_public_input`<br>`test_variable_typed_maps_accept_plain_integers_and_share_json` | — | — | 0 |
| `tests/core/test_typed_string_dict_json_input.py` [open](tests/core/test_typed_string_dict_json_input.py) | A | `test_fixed_string_map_lists_render_only_valid_metadata`<br>`test_http_errors_for_invalid_string_map_are_safe`<br>`test_inline_string_maps_preserve_values_and_reject_nonstrings`<br>`test_invalid_string_map_variable_is_rejected_before_resolver`<br>`test_permission_clone_preserves_surviving_string_map_validator`<br>`test_string_map_spellings_use_strict_json_public_input`<br>`test_wrappers_defaults_factory_and_nested_inputs_keep_string_validation` | — | — | 0 |
| `tests/core/test_types_objecttype.py` [open](tests/core/test_types_objecttype.py) | M | — | — | — | 6 |
| `tests/core/test_typing_set_int_input.py` [open](tests/core/test_typing_set_int_input.py) | A | `test_invalid_typing_set_int_literal_fails_before_resolver`<br>`test_invalid_typing_set_int_variable_fails_before_resolver`<br>`test_pruned_typing_set_int_metadata_keeps_only_visible_field`<br>`test_typing_set_custom_leaf_equality_keeps_string_fallback`<br>`test_typing_set_int_alias_uses_resolver_field_name`<br>`test_typing_set_int_emits_no_fallback_warning`<br>`test_typing_set_int_fixed_and_factory_defaults_keep_lifecycle`<br>`test_typing_set_int_inline_values_use_native_coercion`<br>`test_typing_set_int_list_reaches_resolver_as_set`<br>`test_typing_set_int_optional_omission_and_null_are_unchanged`<br>`test_typing_set_int_prints_int_list`<br>`test_typing_set_int_required_field_stays_required`<br>`test_typing_set_int_variable_uses_native_list_coercion`<br>`test_unrelated_custom_scalar_equality_keeps_string_fallback` | — | — | 0 |
| `tests/core/test_uuid_set_input.py` [open](tests/core/test_uuid_set_input.py) | A | `test_alias_selection_replacement_and_pruning_project_uuid_metadata`<br>`test_custom_leaf_comparing_equal_to_uuid_keeps_fallback`<br>`test_custom_outer_annotation_comparing_equal_to_alias_keeps_fallback`<br>`test_fixed_and_factory_uuid_defaults_keep_lifecycle`<br>`test_invalid_uuid_literals_reject_before_mutation`<br>`test_invalid_uuid_variables_reject_before_mutation`<br>`test_malformed_legacy_uuid_defaults_remain_unchanged`<br>`test_native_uuid_literals_use_list_coercion`<br>`test_native_uuid_variables_reach_resolver_as_exact_uuid_set`<br>`test_optional_uuid_sets_keep_omission_and_null`<br>`test_other_set_leaves_and_nested_forms_keep_fallback`<br>`test_required_uuid_set_rejects_omission`<br>`test_uuid_sets_introspect_as_non_null_uuid_lists`<br>`test_uuid_sets_publish_list_and_reach_resolver_as_set` | — | — | 0 |
| `tests/core/test_window_prefetch_native.py` [open](tests/core/test_window_prefetch_native.py) | M | — | — | — | 7 |
| `tests/core/test_wu12_schema_compiler_coverage.py` [open](tests/core/test_wu12_schema_compiler_coverage.py) | M | — | — | — | 15 |
| `tests/core/test_wu9_modeltype_mutation_execution.py` [open](tests/core/test_wu9_modeltype_mutation_execution.py) | M | — | — | — | 5 |
| `tests/core/test_wu9_mutation_execution.py` [open](tests/core/test_wu9_mutation_execution.py) | M | — | — | — | 4 |
| `tests/subscriptions/_transport_schema.py` [open](tests/subscriptions/_transport_schema.py) | M | — | — | — | 0 |
| `tests/subscriptions/test_audit_defects.py` [open](tests/subscriptions/test_audit_defects.py) | M | — | — | — | 16 |
| `tests/subscriptions/test_automatic_best_effort.py` [open](tests/subscriptions/test_automatic_best_effort.py) | A | `test_async_automatic_failure_logs_only_metadata`<br>`test_base_exception_is_not_swallowed`<br>`test_broken_notification_transaction_still_propagates_database_error`<br>`test_database_write_error_remains_strict`<br>`test_explicit_manual_broadcast_remains_strict`<br>`test_failed_delivery_preserves_autocommit_update_and_delete`<br>`test_failed_snapshot_does_not_change_generated_mutation_result`<br>`test_logging_backend_failure_does_not_abort_save`<br>`test_missing_layer_warning_backend_failure_is_best_effort`<br>`test_rollback_discards_automatic_failures_and_snapshots`<br>`test_send_failure_keeps_committed_write_and_later_callback`<br>`test_snapshot_failure_does_not_abort_atomic_save` | — | — | 0 |
| `tests/subscriptions/test_capability_parity.py` [open](tests/subscriptions/test_capability_parity.py) | M | — | — | — | 10 |
| `tests/subscriptions/test_datetime_snapshots.py` [open](tests/subscriptions/test_datetime_snapshots.py) | A | `test_automatic_signal_keeps_original_datetime_after_object_changes`<br>`test_datetime_output_accepts_native_wire_snapshot`<br>`test_different_microseconds_do_not_deliver`<br>`test_equal_datetime_event_delivers_captured_instant`<br>`test_invalid_datetime_wire_values_do_not_pass_a_typed_filter`<br>`test_invalid_native_datetime_output_keeps_scalar_rejection`<br>`test_null_and_ordinary_string_filters_stay_unchanged`<br>`test_unfiltered_full_snapshot_preserves_microseconds_and_output` | — | — | 0 |
| `tests/subscriptions/test_decimal_snapshot_filter.py` [open](tests/subscriptions/test_decimal_snapshot_filter.py) | A | `test_decimal_snapshot_gate_preserves_non_decimal_and_fallback_filters`<br>`test_native_decimal_filter_matches_snapshot_with_different_scale`<br>`test_native_wide_decimal_filter_matches_valid_model_snapshot` | — | — | 0 |
| `tests/subscriptions/test_delete_snapshot_matching.py` [open](tests/subscriptions/test_delete_snapshot_matching.py) | A | `test_missing_or_malformed_private_delete_snapshot_fails_closed`<br>`test_private_capture_excludes_relations_containers_nonfinite_and_custom_backend`<br>`test_private_delete_equality_preserves_typed_scalar_contract`<br>`test_real_delete_uses_signal_time_projected_equality` | — | — | 0 |
| `tests/subscriptions/test_delivery_runtimeerror_diagnostic.py` [open](tests/subscriptions/test_delivery_runtimeerror_diagnostic.py) | A | `test_client_complete_logs_suppressed_delivery_runtimeerror`<br>`test_client_complete_valueerror_keeps_existing_error_frame`<br>`test_delivery_close_runtimeerror_warns_once_and_stays_idempotent` | — | — | 0 |
| `tests/subscriptions/test_float_snapshot_filter.py` [open](tests/subscriptions/test_float_snapshot_filter.py) | A | `test_float_pair_only_changes_finite_exact_equality`<br>`test_real_float_field_exact_event` | — | — | 0 |
| `tests/subscriptions/test_routed_on_commit.py` [open](tests/subscriptions/test_routed_on_commit.py) | A | `test_default_transaction_does_not_capture_secondary_autocommit`<br>`test_missing_layer_warning_follows_secondary_commit`<br>`test_routed_delete_waits_for_commit`<br>`test_routed_save_rollback_discards_notification`<br>`test_routed_save_waits_for_secondary_commit` | — | — | 0 |
| `tests/subscriptions/test_sse_controls.py` [open](tests/subscriptions/test_sse_controls.py) | A | `test_anonymous_request_does_not_access_account_lease_backend`<br>`test_backend_failure_is_pre_stream_503`<br>`test_cancelled_backend_failure_still_propagates_cancellation`<br>`test_cancelled_unknown_admission_cleans_its_token`<br>`test_controls_ship_disabled_with_independent_values`<br>`test_event_heartbeat_and_natural_completion_share_one_source`<br>`test_expired_lease_cannot_be_resurrected`<br>`test_failed_release_is_bounded_by_expiry`<br>`test_healthy_lease_renews_without_heartbeat`<br>`test_heartbeat_remains_off_by_default`<br>`test_idle_heartbeat_keeps_one_source_alive`<br>`test_invalid_control_settings_fail_explicitly`<br>`test_missing_persistent_account_id_is_refused`<br>`test_renewal_failure_finishes_stream_without_backend_secret`<br>`test_second_account_stream_is_rejected_before_source`<br>`test_sixth_stream_is_429_and_existing_five_survive`<br>`test_source_start_failure_releases_reserved_slot`<br>`test_subscribe_result_releases_unused_lease` | — | — | 0 |
| `tests/subscriptions/test_sse_lease_lifecycle.py` [open](tests/subscriptions/test_sse_lease_lifecycle.py) | A | `test_backend_error_after_start_closes_source_before_503`<br>`test_cancelled_startup_revalidation_closes_source_and_lease`<br>`test_consumer_delay_rechecks_before_next_source_read`<br>`test_expired_initial_lease_never_delivers_application_data`<br>`test_overdue_ready_result_is_withheld_on_backend_error`<br>`test_ready_events_still_renew_overdue_lease`<br>`test_repeated_cancellation_settles_admission_before_release` | — | — | 0 |
| `tests/subscriptions/test_startup_cleanup.py` [open](tests/subscriptions/test_startup_cleanup.py) | A | `test_cleanup_failure_does_not_replace_startup_failure`<br>`test_client_complete_during_real_join_discards_membership`<br>`test_disconnect_during_real_join_discards_membership`<br>`test_explicit_close_after_failed_join_stays_closed`<br>`test_failed_second_join_discards_only_its_memberships`<br>`test_failure_before_backend_join_preserves_original_error`<br>`test_same_source_retry_after_failed_join_delivers_and_cleans_up`<br>`test_sse_cancel_during_real_join_discards_membership` | — | — | 0 |
| `tests/subscriptions/test_transport_cold_permissions.py` [open](tests/subscriptions/test_transport_cold_permissions.py) | A | `test_sse_provider_resolves_cold_real_user_permissions`<br>`test_sync_providers_preserve_context_and_error_paths`<br>`test_ws_concurrent_operations_resolve_provider_once`<br>`test_ws_provider_resolves_cold_real_user_permissions`<br>`test_ws_real_auth_handshake_prunes_cold_permissions` | — | — | 0 |
| `tests/subscriptions/test_transport_import_without_settings.py` [open](tests/subscriptions/test_transport_import_without_settings.py) | M | — | — | — | 1 |
| `tests/subscriptions/test_ws_completion_reuse.py` [open](tests/subscriptions/test_ws_completion_reuse.py) | A | `test_complete_waits_for_teardown_then_reuses_same_id`<br>`test_teardown_error_keeps_existing_terminal_frame_sequence` | — | — | 0 |
| `tests/subscriptions/test_ws_on_connect.py` [open](tests/subscriptions/test_ws_on_connect.py) | A | `test_default_ignores_nonmapping_init_payloads`<br>`test_disconnect_cancels_pending_hook`<br>`test_documented_on_connect_callback_is_typed_and_explained`<br>`test_hook_denial_has_no_session_fallback_or_secret_output`<br>`test_hook_identity_replaces_session_for_provider_and_permissions`<br>`test_hook_receives_normalized_payload_and_blocks_ack`<br>`test_hook_rejects_nonmapping_payload_without_invocation`<br>`test_late_callback_result_cannot_replace_identity_or_ack`<br>`test_pending_hook_retains_protocol_errors`<br>`test_pending_hook_times_out_and_cancels_without_late_ack` | — | — | 0 |
| `tests/subscriptions/test_ws_subprotocol.py` [open](tests/subscriptions/test_ws_subprotocol.py) | A | `test_required_subprotocol_is_accepted_among_alternatives`<br>`test_unoffered_subprotocol_is_rejected_before_accept` | — | — | 0 |
| `tests/test_and_many_filtering.py` [open](tests/test_and_many_filtering.py) | A | `test_empty_boolean_operands_and_direct_many_ids`<br>`test_public_and_keeps_relation_object_same_row`<br>`test_public_deeper_and_keeps_one_outer_comment`<br>`test_public_deeper_grouping_and_missing_child_sql_null`<br>`test_public_exact_null_and_isnull_keep_absent_reverse_row`<br>`test_public_m2m_and_branches_match_distinct_rows`<br>`test_public_nested_or_not_and_multihop_correlation`<br>`test_public_paginated_count_and_variables`<br>`test_public_reverse_fk_and_branches_match_distinct_rows`<br>`test_scoped_queryset_alias_projection_and_one_sql`<br>`test_unset_boolean_children_keep_independent_branch` | — | — | 0 |
| `tests/test_async_directive_middleware.py` [open](tests/test_async_directive_middleware.py) | A | `test_http_outer_wrapper_does_not_leak_directive_coroutine`<br>`test_native_async_execution_applies_directive_after_await`<br>`test_sync_http_preserves_borrowed_future_with_directive`<br>`test_sync_http_rejects_async_resolver_with_directive`<br>`test_synchronous_directive_behavior_is_unchanged` | — | — | 0 |
| `tests/test_audit_400_report_contract.py` [open](tests/test_audit_400_report_contract.py) | A | `test_dispositions_keep_important_counterexamples_and_boundaries`<br>`test_examples_and_decision_queue_do_not_turn_boundaries_into_fixes`<br>`test_false_positive_subclaims_keep_counterexample_and_residual`<br>`test_live_redis_proof_is_separate_from_failover_decision`<br>`test_local_docstring_status_distinguishes_current_scan_from_history`<br>`test_primary_table_preserves_exact_original_order_and_status_totals`<br>`test_registry_and_factory_examples_state_the_actual_unit`<br>`test_report_bounds_direct_int_or_string_union_disposition`<br>`test_report_discloses_original_tdd_limit_without_rewriting_history`<br>`test_report_is_navigable_and_release_notes_do_not_claim_release` | — | — | 0 |
| `tests/test_batch_http_error_partial.py` [open](tests/test_batch_http_error_partial.py) | A | `test_first_http_400_has_one_error_entry_and_no_invalidation`<br>`test_later_http_400_keeps_prior_result_and_stops_batch`<br>`test_non_400_http_error_keeps_existing_request_level_envelope`<br>`test_outer_preflight_and_single_error_keep_existing_object_envelope`<br>`test_partial_response_does_not_depend_on_response_cache`<br>`test_validation_error_continues_until_later_transport_error` | — | — | 0 |
| `tests/test_clean_response_http.py` [open](tests/test_clean_response_http.py) | A | `test_clean_response_keeps_zero_false_and_nonempty_values`<br>`test_disabled_cleaning_leaves_the_full_payload_unchanged`<br>`test_selected_operation_controls_introspection_cleaning` | — | — | 0 |
| `tests/test_converter.py` [open](tests/test_converter.py) | M | — | `ConverterTest.test_convert_decimal_field`<br>`FieldConversionIntegrationTest.test_model_to_graphql_type_conversion` | — | 27 |
| `tests/test_converter_branches.py` [open](tests/test_converter_branches.py) | M | `test_decimal_field_converts_to_exact_scalar` | — | `test_decimal_field_converts_to_float` | 30 |
| `tests/test_converter_choices.py` [open](tests/test_converter_choices.py) | M | `test_grouped_colliding_labels_reject_enum_creation`<br>`test_grouped_unique_labels_keep_every_value_in_the_enum`<br>`test_naming_rejects_colliding_names`<br>`test_naming_rejects_colliding_names_across_groups` | — | `test_grouped_colliding_labels_keep_every_value_in_the_enum`<br>`test_naming_dedupes_colliding_names`<br>`test_naming_dedupes_colliding_names_across_groups` | 14 |
| `tests/test_cost_edges.py` [open](tests/test_cost_edges.py) | M | `test_cyclic_fragment_spread_raises_graphql_error` | — | `test_cyclic_fragment_spread_costed_once` | 9 |
| `tests/test_cost_mutation_cache.py` [open](tests/test_cost_mutation_cache.py) | A | `test_late_resolver_error_still_invalidates_after_non_atomic_write`<br>`test_later_refusal_preserves_earlier_executed_batch_mutation`<br>`test_refused_mutation_does_not_invalidate_warmed_query` | — | — | 0 |
| `tests/test_cost_variable_http.py` [open](tests/test_cost_variable_http.py) | A | `test_bound_skip_directive_controls_actual_cost`<br>`test_custom_scalar_and_executor_build_once_before_cost_refusal`<br>`test_high_declared_default_is_checked_when_variable_is_omitted`<br>`test_high_variable_is_rejected_before_resolver_on_validation_cache_hits`<br>`test_input_default_factories_are_not_recoerced_for_bound_cost`<br>`test_no_cost_budget_remains_a_noop`<br>`test_only_selected_operation_is_bound_checked_and_invalid_input_keeps_its_error`<br>`test_small_and_declared_default_variables_remain_accepted`<br>`test_static_fallback_still_rejects_a_small_bound_variable`<br>`test_unselected_operation_still_receives_static_validation` | — | — | 0 |
| `tests/test_datepart_filtering.py` [open](tests/test_datepart_filtering.py) | A | `test_lookup_type_boundaries_and_shared_inputs`<br>`test_numeric_date_parts_have_int_sdl_and_work_over_http` | — | — | 0 |
| `tests/test_datepart_test_portability.py` [open](tests/test_datepart_test_portability.py) | A | `test_datepart_behavior_does_not_assert_local_runtime_identity` | — | — | 0 |
| `tests/test_default_page_size_http.py` [open](tests/test_default_page_size_http.py) | A | `test_default_is_not_a_maximum_http`<br>`test_explicit_none_preserves_each_legacy_paginator_policy`<br>`test_nested_omitted_size_uses_library_default_http`<br>`test_omitted_size_uses_library_default_across_public_paginators`<br>`test_startup_global_override_and_local_size_take_precedence` | — | — | 0 |
| `tests/test_destination_link_compatibility.py` [open](tests/test_destination_link_compatibility.py) | A | `test_malformed_destination_id_uses_structured_missing_error`<br>`test_mti_parent_table_cannot_authorize_child_id`<br>`test_same_concrete_proxy_queryset_still_allows_link`<br>`test_supported_callable_destination_hooks_allow_visible_id`<br>`test_visible_id_remains_linkable_through_supported_queryset_shapes` | — | — | 0 |
| `tests/test_destination_link_scope.py` [open](tests/test_destination_link_scope.py) | A | `test_destination_hook_for_wrong_model_fails_before_write`<br>`test_existing_nested_child_update_is_not_reclassified_as_a_link`<br>`test_hidden_relation_id_has_the_same_error_as_missing`<br>`test_nested_link_is_scoped_before_parent_save`<br>`test_request_registry_not_global_registry_selects_destination_scope`<br>`test_unregistered_destination_adds_no_fk_lookup` | — | — | 0 |
| `tests/test_directive_case_normalization.py` [open](tests/test_directive_case_normalization.py) | A | `test_acronym_block_is_one_word`<br>`test_approved_boundaries_and_nonletters`<br>`test_approved_source_forms_normalize_consistently`<br>`test_each_directive_output_is_idempotent`<br>`test_none_passes_through_and_numeric_value_is_stringified`<br>`test_unapproved_character_forms_keep_legacy_converters` | — | — | 0 |
| `tests/test_directive_date_naive_timezone.py` [open](tests/test_directive_date_naive_timezone.py) | A | `test_missing_components_keep_the_parser_default_across_midnight`<br>`test_named_unknown_and_numeric_offset_text_keep_previous_paths`<br>`test_original_explicit_offset_helper_retains_its_boolean_contract`<br>`test_timezone_less_summer_text_uses_each_active_zone`<br>`test_timezone_less_text_uses_active_zone_for_absolute_and_relative_formats` | — | — | 0 |
| `tests/test_directive_date_null.py` [open](tests/test_directive_date_null.py) | A | `test_date_only_value_still_uses_existing_formatting`<br>`test_date_resolver_none_is_not_a_format_wrapper`<br>`test_invalid_non_null_value_keeps_fallback`<br>`test_nullable_date_field_stays_null`<br>`test_required_nested_date_bubbles_only_to_nullable_parent`<br>`test_required_root_date_uses_normal_non_null_error`<br>`test_valid_datetime_still_formats` | — | — | 0 |
| `tests/test_directive_date_text_time.py` [open](tests/test_directive_date_text_time.py) | A | `test_parser_zeros_microseconds_without_changing_explicit_or_nontext_values`<br>`test_text_default_preserves_active_timezone_with_use_tz_false`<br>`test_text_time_components_are_zero_in_native_graphql`<br>`test_text_time_only_keeps_current_date_across_days` | — | — | 0 |
| `tests/test_directive_date_timezone.py` [open](tests/test_directive_date_timezone.py) | A | `test_absolute_formats_localize_only_explicit_instants`<br>`test_active_zone_applies_to_aware_instants_with_use_tz_false`<br>`test_adjacent_zero_offset_relative_formats_keep_instant`<br>`test_clock_adjacent_zero_offsets_match_z_absolute_zone`<br>`test_dst_conversion_uses_each_instants_active_offset`<br>`test_explicit_offset_before_accepted_abbreviation_is_localized`<br>`test_explicit_offset_before_trailing_year_is_localized`<br>`test_invalid_offset_text_keeps_string_fallback`<br>`test_naive_text_and_typed_inputs_keep_existing_wall_clock`<br>`test_parser_accepted_adjacent_zero_spellings_are_explicit`<br>`test_public_helpers_and_other_input_kinds_are_unchanged`<br>`test_relative_formats_keep_current_path` | — | — | 0 |
| `tests/test_directive_field_locations.py` [open](tests/test_directive_field_locations.py) | A | `test_field_transform_inside_fragment_still_executes`<br>`test_field_transform_order_is_unchanged`<br>`test_guide_states_field_only_contract_with_fragment_migration`<br>`test_invalid_fragment_transform_has_http_error_wire`<br>`test_library_locations_and_builtin_metadata_are_distinct`<br>`test_raw_third_party_directive_keeps_explicit_fragment_locations`<br>`test_spec_builtins_still_control_fragment_and_field_selection`<br>`test_transform_on_fragment_is_rejected_before_resolution` | — | — | 0 |
| `tests/test_directive_numeric_null.py` [open](tests/test_directive_numeric_null.py) | A | `test_currency_custom_symbol_does_not_replace_null`<br>`test_existing_falsy_values_still_format`<br>`test_non_null_bad_value_still_reports_coercion_error`<br>`test_nullable_numeric_directive_preserves_graphql_null`<br>`test_number_cap_still_rejects_null_on_every_field_type`<br>`test_number_invalid_spec_still_rejected_for_null_formatted_field`<br>`test_number_invalid_spec_still_skipped_for_raw_numeric_type`<br>`test_numeric_and_other_nullable_types_keep_null`<br>`test_other_directive_and_default_chain_keep_their_contract`<br>`test_required_null_still_validates_number_spec`<br>`test_required_numeric_directive_bubbles_normally`<br>`test_required_root_numeric_null_bubbles_to_data` | — | — | 0 |
| `tests/test_directives_internals.py` [open](tests/test_directives_internals.py) | M | — | `DirectiveSchemaNoneTest.test_case_directives`<br>`test_number_directive_formats_value`<br>`test_snake_case_directive_resolve` | — | 35 |
| `tests/test_docs_current_behavior_boundaries.py` [open](tests/test_docs_current_behavior_boundaries.py) | A | `test_both_changelogs_scope_these_clarifications_to_documentation`<br>`test_cache_guide_explains_csrf_cookie_round_trip_and_privacy`<br>`test_cache_guide_limits_csrf_cookie_claim_to_decorated_misses`<br>`test_date_guide_states_naive_timezone_assumption_without_changing_scalar`<br>`test_mutation_guide_distinguishes_input_semantics_from_sql_updates`<br>`test_pagination_guide_states_automatic_nullable_order_boundary`<br>`test_subscription_guide_separates_signals_from_manual_broadcast` | — | — | 0 |
| `tests/test_docs_mutation_contract.py` [open](tests/test_docs_mutation_contract.py) | M | `test_docs_qualify_fixed_json_object_default_metadata`<br>`test_guide_documents_direct_int_or_string_union_migration`<br>`test_guide_documents_exact_boolean_map_json_migration`<br>`test_guide_documents_exact_boolean_set_migration`<br>`test_guide_documents_exact_finite_decimal_set_migration`<br>`test_guide_documents_exact_float_set_migration`<br>`test_guide_documents_exact_integer_set_migration`<br>`test_guide_documents_exact_string_set_migration`<br>`test_guide_documents_exact_uuid_set_migration`<br>`test_guide_documents_recursive_supported_input_lists`<br>`test_guide_documents_string_literal_enum_client_migration`<br>`test_guide_documents_typed_integer_map_json_migration`<br>`test_guide_documents_typed_string_map_json_migration` | — | — | 4 |
| `tests/test_docs_types_samples.py` [open](tests/test_docs_types_samples.py) | M | — | `test_sample_builds_behind_the_pages_own_node_type` | — | 3 |
| `tests/test_exact_null_filtering.py` [open](tests/test_exact_null_filtering.py) | A | `test_direct_relation_and_unset_lookup_boundaries`<br>`test_exact_null_field_matrix_and_json_sql_null`<br>`test_native_coercion_preserves_lookup_presence`<br>`test_nullable_choice_and_text_exact_null`<br>`test_public_exact_null_composes_without_changing_empty_nodes`<br>`test_public_literal_exact_null_is_distinct_from_omission`<br>`test_public_variable_exact_null_is_distinct_from_omission`<br>`test_to_many_null_keeps_distinct_and_nested_prefix` | — | — | 0 |
| `tests/test_filtering_internals.py` [open](tests/test_filtering_internals.py) | M | — | `test_is_pk_lookups_non_mapping_is_false` | — | 45 |
| `tests/test_flat_gfk_pruned_security.py` [open](tests/test_flat_gfk_pruned_security.py) | A | `test_explicit_prune_grants_never_widen_from_context_or_reprune`<br>`test_flat_cache_keys_unregistered_target_grants`<br>`test_flat_target_denied_by_actual_model_permission`<br>`test_flat_target_uses_registered_scope_per_request`<br>`test_http_cache_rechecks_same_users_target_grant`<br>`test_invalid_registered_scope_fails_closed`<br>`test_missing_flat_target_stays_null`<br>`test_registered_default_hook_adds_no_membership_query`<br>`test_registered_scope_preserves_join_and_slice_membership`<br>`test_unmarked_schema_keeps_projected_signature` | — | — | 0 |
| `tests/test_floor_nonfinite_error.py` [open](tests/test_floor_nonfinite_error.py) | A | `test_floor_directly_rejects_nonfinite_values`<br>`test_floor_keeps_finite_and_boolean_values`<br>`test_floor_nonnull_error_uses_standard_bubbling`<br>`test_floor_preserves_none_and_malformed_value_policy`<br>`test_floor_public_execution_returns_nullable_error`<br>`test_floor_rejects_numeric_strings_that_coerce_to_nonfinite`<br>`test_other_directives_and_floor_schema_metadata_remain_unchanged` | — | — | 0 |
| `tests/test_fragment_cycles.py` [open](tests/test_fragment_cycles.py) | A | `test_acyclic_spreads_and_missing_targets_do_not_trigger_cycle_check`<br>`test_cyclic_fanout_is_rejected_before_expensive_walks`<br>`test_default_view_rejects_cycle_without_running_resolver`<br>`test_dense_multi_entry_cycle_is_detected`<br>`test_disconnected_fragment_cycle_rejects_direct_cost_analysis`<br>`test_long_fragment_chain_uses_iterative_cycle_check` | — | — | 0 |
| `tests/test_fragment_fanout.py` [open](tests/test_fragment_fanout.py) | M | `test_cyclic_fragment_is_rejected_before_cost_expansion` | — | `test_cyclic_fragment_still_terminates_and_reports_as_before` | 4 |
| `tests/test_generated_delete_security.py` [open](tests/test_generated_delete_security.py) | A | `test_blocked_delete_preserves_sibling_rollback`<br>`test_blocked_generated_delete_hides_collector_details`<br>`test_generated_delete_keeps_success_and_not_found_contract`<br>`test_unclassified_integrity_error_uses_generic_generated_policy` | — | — | 0 |
| `tests/test_generated_integrity_error_redaction.py` [open](tests/test_generated_integrity_error_redaction.py) | A | `test_conditional_unique_violation_is_redacted`<br>`test_direct_backend_keeps_unclassified_integrity_exception`<br>`test_generated_delete_integrity_failure_is_redacted`<br>`test_generated_root_check_failure_is_redacted`<br>`test_generated_success_and_nonintegrity_error_use_http_diagnostics`<br>`test_handwritten_mutation_error_is_safe_in_production_http`<br>`test_mapped_unique_error_keeps_structured_payload`<br>`test_nested_check_failure_rolls_back_without_leaking` | — | — | 0 |
| `tests/test_generated_security_test_portability.py` [open](tests/test_generated_security_test_portability.py) | A | `test_contributor_testing_guidance_keeps_local_runtime_guards_external`<br>`test_generated_security_suites_do_not_require_a_local_graphql_checkout` | — | — | 0 |
| `tests/test_http_execution_error_contract.py` [open](tests/test_http_execution_error_contract.py) | A | `test_batch_execution_error_continues_and_validation_error_remains_scoped`<br>`test_multipart_form_uses_same_execution_envelope`<br>`test_nonnull_root_execution_error_has_null_data_in_both_views`<br>`test_null_execution_envelope_survives_cleaning_and_production_formatting`<br>`test_null_execution_errors_are_not_cached_or_replayed`<br>`test_nullable_error_and_success_keep_existing_data_and_cost`<br>`test_request_errors_stay_http_400_without_data` | — | — | 0 |
| `tests/test_http_internal_error_diagnostics.py` [open](tests/test_http_internal_error_diagnostics.py) | A | `test_custom_view_formatter_remains_an_explicit_override`<br>`test_debug_and_shared_transport_formatter_keep_existing_diagnostics`<br>`test_ids_are_unique_and_wrapped_internal_extensions_are_dropped`<br>`test_internal_failures_have_safe_http_diagnostics_and_correlated_logs`<br>`test_logger_failure_cannot_change_safe_http_response`<br>`test_nonnull_error_keeps_null_data_and_safe_message_in_every_view`<br>`test_production_error_documentation_example_matches_the_wire_contract`<br>`test_public_errors_validation_and_http_parse_errors_keep_their_contract`<br>`test_shared_formatter_is_unchanged_in_production` | — | — | 0 |
| `tests/test_introspection_docs.py` [open](tests/test_introspection_docs.py) | A | `test_introspection_setting_requires_installed_middleware`<br>`test_security_guide_installs_middleware_before_blocking_introspection` | — | — | 0 |
| `tests/test_introspection_fragments.py` [open](tests/test_introspection_fragments.py) | A | `test_ambiguous_reachable_fragment_name_fails_closed`<br>`test_http_disabled_cleaning_remains_unchanged`<br>`test_http_mixed_fragment_still_cleans_ordinary_data`<br>`test_http_named_fragment_introspection_keeps_null_and_empty_lists`<br>`test_malformed_root_selections_fail_closed`<br>`test_mixed_or_unresolved_root_fragments_fail_closed`<br>`test_reachable_root_fragments_are_introspection`<br>`test_repeated_shared_fragments_expand_once`<br>`test_selected_operation_ignores_unreachable_fragments` | — | — | 0 |
| `tests/test_invalid_id_contract.py` [open](tests/test_invalid_id_contract.py) | A | `test_custom_primary_key_prepared_once_with_generic_error`<br>`test_custom_primary_key_renamed_argument_keeps_safe_public_error`<br>`test_existing_missing_exception_boundary_in_hooks_is_preserved`<br>`test_existing_numeric_and_null_coercion_remain_orm_owned`<br>`test_get_node_rejects_malformed_integer_id`<br>`test_hidden_row_still_looks_missing`<br>`test_http_production_wire_keeps_deliberate_error`<br>`test_malformed_id_in_generated_retrieve_field`<br>`test_malformed_integer_id_has_safe_public_error`<br>`test_malformed_uuid_id_has_safe_public_error`<br>`test_non_null_field_bubbles_the_deliberate_error`<br>`test_retrieve_authorization_error_precedes_id_conversion`<br>`test_unrelated_queryset_errors_are_not_relabelled`<br>`test_uuid_missing_and_valid_ids_keep_lookup_behavior`<br>`test_valid_missing_and_char_primary_keys_keep_orm_meaning` | — | — | 0 |
| `tests/test_json_nonfinite_input.py` [open](tests/test_json_nonfinite_input.py) | A | `test_available_variable_literal_path_rejects_nonfinite`<br>`test_defaults_missing_members_and_explicit_null_keep_their_contract`<br>`test_finite_and_string_values_keep_identity_and_wire_shape`<br>`test_http_input_error_uses_graphql_error_wire`<br>`test_huge_finite_int_and_native_container_aliases_are_not_rewritten`<br>`test_literal_overflow_rejected_before_resolver`<br>`test_nested_variable_infinity_rejected_before_resolver`<br>`test_nonfinite_default_literal_rejected`<br>`test_overflow_literal_shapes_fail_before_resolver`<br>`test_raw_output_and_json_string_scalar_remain_separate`<br>`test_variable_nonfinite_values_fail_before_resolver` | — | — | 0 |
| `tests/test_json_raw_missing_list_null.py` [open](tests/test_json_raw_missing_list_null.py) | A | `test_defaulted_and_explicit_null_variables_remain_distinct`<br>`test_http_view_emits_json_null_without_undefined_sentinel`<br>`test_json_string_scalar_is_not_reinterpreted`<br>`test_nested_lists_preserve_slots_while_object_keys_stay_omitted`<br>`test_omitted_variable_keeps_null_slot_on_json_wire`<br>`test_ordinary_typed_list_and_direct_missing_argument_stay_unchanged`<br>`test_supplied_json_variable_values_keep_their_shape` | — | — | 0 |
| `tests/test_multipart_file_size_http.py` [open](tests/test_multipart_file_size_http.py) | A | `test_cache_active_multipart_cannot_bypass_file_cap`<br>`test_csrf_header_refusal_precedes_file_cap`<br>`test_every_repeated_file_is_checked`<br>`test_graphiql_success_path_still_checks_files`<br>`test_independent_total_body_cap_still_rejects_first`<br>`test_malformed_multipart_batch_keeps_400_before_file_cap`<br>`test_multiple_files_are_not_summed`<br>`test_oversized_file_prevents_mutation_resolver`<br>`test_oversized_multipart_file_is_rejected_before_resolver`<br>`test_single_file_boundary_and_uncapped_mode`<br>`test_temporary_uploaded_file_is_rejected_and_closed` | — | — | 0 |
| `tests/test_native_filtering.py` [open](tests/test_native_filtering.py) | M | — | `test_to_q_pk_lookups_on_relation`<br>`test_to_q_pk_lookups_on_to_many_relation_flag_distinct` | — | 28 |
| `tests/test_negative_page_count_error_http.py` [open](tests/test_negative_page_count_error_http.py) | A | `test_failed_count_does_not_use_length_or_iteration`<br>`test_failed_negative_page_count_is_generic_and_does_not_fetch_rows`<br>`test_list_fallback_and_unrelated_count_errors_are_unchanged`<br>`test_positive_page_does_not_attempt_count_when_not_selected` | — | — | 0 |
| `tests/test_nested_child_permissions.py` [open](tests/test_nested_child_permissions.py) | M | — | `TestNestedChildPermissions.test_forward_link_path_is_not_gated`<br>`TestNestedChildPermissions.test_m2m_link_path_is_not_gated` | — | 7 |
| `tests/test_nested_edges.py` [open](tests/test_nested_edges.py) | M | — | `test_relation_kind_reverse_one_for_reverse_o2o` | — | 7 |
| `tests/test_nested_sd4_orphan_scope.py` [open](tests/test_nested_sd4_orphan_scope.py) | A | `test_existing_orphan_requires_child_update_host`<br>`test_existing_owned_and_new_children_keep_prior_paths`<br>`test_later_orphan_denial_rolls_back_earlier_sibling_write`<br>`test_parent_create_keeps_new_child_path`<br>`test_unrelated_registry_cannot_supply_child_update_host`<br>`test_update_host_preserves_scope_and_child_permission`<br>`test_update_serving_mutation_host_admits_visible_orphan` | — | — | 0 |
| `tests/test_optimizer_coverage.py` [open](tests/test_optimizer_coverage.py) | M | — | — | — | 97 |
| `tests/test_optimizer_fragment_fanout.py` [open](tests/test_optimizer_fragment_fanout.py) | A | `test_bounded_promotion_iterator_handles_absent_and_cyclic_internal_inputs`<br>`test_interleaved_fragment_restores_last_annotation_alias_value`<br>`test_interleaved_fragment_restores_last_prefetch_annotation_plan`<br>`test_promotion_consumer_bounds_repeated_spreads_without_changing_rows`<br>`test_reused_fragment_keeps_distinct_relation_path_contexts`<br>`test_valid_repeated_fragment_graph_has_bounded_optimizer_visits` | — | — | 0 |
| `tests/test_optimizer_merged_field_nodes.py` [open](tests/test_optimizer_merged_field_nodes.py) | A | `MergedRootFieldNodesTest.test_direct_and_fragment_root_fields_share_relation_and_column_plan`<br>`MergedRootFieldNodesTest.test_second_root_node_promotes_annotated_relation` | — | — | 0 |
| `tests/test_optimizer_perf.py` [open](tests/test_optimizer_perf.py) | M | — | `OnlyNarrowingFmapCacheTest.test_only_narrowing_memoizes_get_fields` | — | 11 |
| `tests/test_optimizer_phase_c.py` [open](tests/test_optimizer_phase_c.py) | M | — | `TestBuildWindowPrefetchPreChecks.test_precheck_returns_none_when_m2m`<br>`TestBuildWindowPrefetchPreChecks.test_precheck_returns_none_when_not_one_to_many`<br>`TestC3FallbackRegressions.test_fallback_unbounded_no_window_sql`<br>`TestWalkerPaginationArgExtraction.test_g2_custom_resolver_falls_back_without_crash` | — | 50 |
| `tests/test_optimizer_phase_d.py` [open](tests/test_optimizer_phase_d.py) | M | — | — | — | 37 |
| `tests/test_optimizer_phase_e.py` [open](tests/test_optimizer_phase_e.py) | M | — | — | — | 25 |
| `tests/test_ordering_provenance.py` [open](tests/test_ordering_provenance.py) | M | `DivergentAllowlistStampTests.test_hidden_column_is_not_orderable_with_the_canonical_node` | — | `DivergentAllowlistStampTests.test_hidden_column_is_not_orderable_when_the_node_registers_late` | 7 |
| `tests/test_output_registration_conflict.py` [open](tests/test_output_registration_conflict.py) | A | `test_distinct_registries_may_publish_distinct_author_views`<br>`test_identical_class_reregistration_is_idempotent`<br>`test_input_registration_and_proxy_model_keys_remain_distinct`<br>`test_model_mutation_reuses_registered_public_output`<br>`test_non_registering_internal_view_does_not_replace_public_type`<br>`test_public_and_admin_user_schemas_bind_post_user_independently`<br>`test_registered_node_remains_list_and_filter_target`<br>`test_second_public_author_type_fails_without_shadowing_nested_author` | — | — | 0 |
| `tests/test_output_selector_validation.py` [open](tests/test_output_selector_validation.py) | A | `test_bare_string_output_selector_is_rejected`<br>`test_corrected_exclusion_hides_sensitive_user_field`<br>`test_custom_slug_key_and_empty_selector_are_valid`<br>`test_declared_custom_only_output_remains_valid`<br>`test_generic_foreign_key_and_set_selectors_remain_supported`<br>`test_non_name_selectors_fail_in_configuration`<br>`test_noninterface_declared_wire_name_keeps_existing_contract`<br>`test_one_shot_selector_is_reused_for_projection`<br>`test_reverse_accessor_and_query_name_selectors_remain_valid`<br>`test_unknown_output_selector_fails_before_registration`<br>`test_valid_model_and_declared_selectors_remain_supported` | — | — | 0 |
| `tests/test_pagination_cursor_typed_http.py` [open](tests/test_pagination_cursor_typed_http.py) | A | `TestTypedCursorHttp.test_generated_root_cursor_and_nested_relation_http`<br>`TestTypedCursorHttp.test_malformed_cursor_is_existing_graphql_error_envelope`<br>`TestTypedCursorHttp.test_tied_boundaries_match_orm_in_both_orderings`<br>`TestTypedCursorHttp.test_typed_invalid_cursor_direct_pagination_and_page_info`<br>`TestTypedCursorHttp.test_typed_invalid_cursor_value_http_error`<br>`TestTypedCursorHttp.test_unapproved_other_type_coercion_fallback_is_unchanged` | — | — | 0 |
| `tests/test_pagination_default_ordering.py` [open](tests/test_pagination_default_ordering.py) | M | `DefaultPaginatorOrderingTest.test_default_paginator_has_library_size` | — | `DefaultPaginatorOrderingTest.test_default_paginator_is_unbounded` | 24 |
| `tests/test_pagination_none_docs_contract.py` [open](tests/test_pagination_none_docs_contract.py) | A | `test_all_none_and_bounded_controls_match_existing_paginators`<br>`test_all_none_table_names_each_paginator_outcome` | — | — | 0 |
| `tests/test_pagination_null_order_parity.py` [open](tests/test_pagination_null_order_parity.py) | A | `test_explicit_orm_null_placement_remains_authoritative`<br>`test_malformed_prefix_is_not_normalized_into_a_valid_column`<br>`test_multifield_priority_and_relation_name_remain_intact`<br>`test_nested_nullable_order_matches_window_and_plain_prefetch`<br>`test_nullable_queryset_and_materialized_pages_agree` | — | — | 0 |
| `tests/test_pagination_page_null_http.py` [open](tests/test_pagination_page_null_http.py) | A | `test_direct_page_null_normalizes_both_paths`<br>`test_existing_page_boundaries_http`<br>`test_explicit_null_page_matches_omission_http`<br>`test_nested_null_page_reaches_materialized_list_without_optimizer`<br>`test_omitted_nullable_variable_keeps_default_http` | — | — | 0 |
| `tests/test_pagination_pk_tiebreak.py` [open](tests/test_pagination_pk_tiebreak.py) | A | `PkTiebreakOrderingTest.test_col_pk_expression_is_not_duplicated`<br>`PkTiebreakOrderingTest.test_explicit_descending_pk_is_not_overridden`<br>`PkTiebreakOrderingTest.test_explicit_id_inside_multiple_terms_is_not_duplicated`<br>`PkTiebreakOrderingTest.test_http_offset_pages_keep_equal_name_rows_disjoint`<br>`PkTiebreakOrderingTest.test_internal_pk_does_not_expand_client_ordering_allowlist`<br>`PkTiebreakOrderingTest.test_limit_offset_db_appends_pk_to_client_order`<br>`PkTiebreakOrderingTest.test_materialized_model_list_uses_same_tie_break`<br>`PkTiebreakOrderingTest.test_model_meta_ordering_survives_db_and_materialized_paths`<br>`PkTiebreakOrderingTest.test_natural_pk_alias_and_attname_keep_explicit_direction`<br>`PkTiebreakOrderingTest.test_natural_pk_uses_field_name_not_id`<br>`PkTiebreakOrderingTest.test_nested_hidden_pk_is_internal_not_client_ordering`<br>`PkTiebreakOrderingTest.test_no_order_uses_pk_and_page_materialized_rows_match`<br>`PkTiebreakOrderingTest.test_page_db_appends_pk_to_client_order`<br>`PkTiebreakOrderingTest.test_public_graphql_pages_cover_equal_name_rows_once`<br>`PkTiebreakOrderingTest.test_queryset_default_and_explicit_order_are_preserved`<br>`PkTiebreakOrderingTest.test_queryset_expression_order_stays_ahead_of_pk`<br>`PkTiebreakOrderingTest.test_queryset_extra_ordering_stays_ahead_of_pk`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_falls_back_for_unsupported_hook_terms`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_keeps_extra_queryset_ordering`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_keeps_hook_queryset_ordering`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_keeps_model_meta_ordering`<br>`PkTiebreakOrderingTest.test_reverse_fk_window_row_number_uses_pk_secondary`<br>`PkTiebreakOrderingTest.test_unbounded_no_order_preserves_original_queryset_cache`<br>`PkTiebreakOrderingTest.test_unbounded_no_order_retains_meta_ordering_without_a_clone`<br>`PkTiebreakOrderingTest.test_unsupported_meta_list_ordering_keeps_pk_fallback` | — | — | 0 |
| `tests/test_pagination_server_order.py` [open](tests/test_pagination_server_order.py) | A | `test_extra_alias_and_dotted_server_terms_remain_orm_owned`<br>`test_extra_alias_nested_path_falls_back_without_losing_primary_order`<br>`test_reversed_orm_expression_and_requested_order_stay_distinct`<br>`test_server_queryset_order_precedes_ascending_pk` | — | — | 0 |
| `tests/test_permission_cache_lock_split.py` [open](tests/test_permission_cache_lock_split.py) | A | `test_clear_waits_for_build_then_removes_entry`<br>`test_cold_builds_remain_serial_and_same_key_is_shared`<br>`test_reentrant_clear_and_failed_prune_leave_cache_recoverable`<br>`test_warm_hit_completes_before_unrelated_cold_prune_is_released` | — | — | 0 |
| `tests/test_playground_310_contract.py` [open](tests/test_playground_310_contract.py) | M | `test_cursor_pagination_readme_matches_playground_settings` | — | — | 1 |
| `tests/test_query_cost.py` [open](tests/test_query_cost.py) | M | — | `CostEngineTest.test_default_multiplier_when_unbounded`<br>`CostEngineTest.test_unbounded_list_warns_once`<br>`CostViewWiringTest.test_get_query_cost_returns_payload` | — | 18 |
| `tests/test_query_optimization.py` [open](tests/test_query_optimization.py) | M | — | — | — | 14 |
| `tests/test_registry.py` [open](tests/test_registry.py) | M | — | `RegistryKeyCollisionTest.test_register_rejects_foreign_registry` | — | 11 |
| `tests/test_relation_lookup_name_collision.py` [open](tests/test_relation_lookup_name_collision.py) | A | `test_nested_lookup_name_and_direct_pk_exact` | — | — | 0 |
| `tests/test_relation_scope_hatch.py` [open](tests/test_relation_scope_hatch.py) | M | — | — | — | 8 |
| `tests/test_replace_output_limit.py` [open](tests/test_replace_output_limit.py) | A | `test_replace_exact_python_semantics`<br>`test_replace_limit_default_is_one_million`<br>`test_replace_limit_none_preserves_uncapped_behavior`<br>`test_replace_limit_rejects_noninteger_values`<br>`test_replace_limit_rejects_nonpositive_values`<br>`test_replace_nonnull_error_bubbles`<br>`test_replace_preserves_null_field`<br>`test_replace_rejects_already_oversized_noop`<br>`test_replace_rejects_expansion_before_returning_result`<br>`test_replace_rejects_without_calling_replace` | — | — | 0 |
| `tests/test_routed_nested_atomic.py` [open](tests/test_routed_nested_atomic.py) | A | `test_custom_backend_keeps_existing_create_instance_contract`<br>`test_explicit_divergent_through_router_rejects_before_any_write`<br>`test_instance_routed_create_initializes_once_and_commits_only_on_success`<br>`test_instance_routed_forward_and_m2m_writes_share_parent_boundary`<br>`test_late_failure_after_real_writes_rolls_back_chosen_alias`<br>`test_later_child_failure_rolls_back_create`<br>`test_later_child_failure_rolls_back_update`<br>`test_nested_create_succeeds_on_own_alias`<br>`test_nested_routing_contract_documents_native_instance_create_boundary`<br>`test_populated_parent_routes_entire_nested_create_to_one_alias`<br>`test_post_id_divergent_through_router_rolls_back_without_foreign_sql` | — | — | 0 |
| `tests/test_sd1_m2m_output_scope.py` [open](tests/test_sd1_m2m_output_scope.py) | A | `test_custom_through_and_reverse_accessor_scope_m2m_output`<br>`test_declared_m2m_count_only_is_scoped`<br>`test_declared_m2m_members_follow_destination_scope`<br>`test_m2m_count_precedes_nested_page_limit`<br>`test_m2m_scope_uses_current_request_and_compiled_schema`<br>`test_optimized_m2m_scope_uses_source_database_alias`<br>`test_optimized_scoped_m2m_prefetch_does_not_grow_per_parent`<br>`test_reverse_m2m_count_only_is_scoped`<br>`test_reverse_m2m_members_follow_destination_scope`<br>`test_unscoped_prefetch_cache_cannot_authorize_m2m_output` | — | — | 0 |
| `tests/test_sd1_o2o_output_scope.py` [open](tests/test_sd1_o2o_output_scope.py) | A | `test_automatic_o2o_outputs_hide_only_destinations`<br>`test_cached_o2o_values_are_not_visibility_evidence`<br>`test_default_reverse_o2o_accessor_uses_destination_scope`<br>`test_explicit_relation_resolver_is_not_reclassified_as_automatic`<br>`test_nested_o2o_outputs_scope_each_hop`<br>`test_o2o_output_hook_failure_does_not_serve_hidden_child`<br>`test_reverse_o2o_destination_scope_reaches_hidden_child_assertion` | — | — | 0 |
| `tests/test_sd1_relation_read_scope.py` [open](tests/test_sd1_relation_read_scope.py) | A | `test_automatic_fk_visibility_matches_destination_scope`<br>`test_automatic_reverse_fk_filters_before_count_and_page`<br>`test_cached_fk_fallback_applies_destination_scope`<br>`test_reverse_fk_query_costs_are_explicit`<br>`test_reverse_fk_window_pages_visible_rows_only`<br>`test_scoped_and_default_fk_query_costs_are_explicit`<br>`test_scoped_fk_prefetch_is_batched_and_aliases_share_visibility`<br>`test_scoped_reverse_fk_plain_prefetch_ignores_unscoped_cache` | — | — | 0 |
| `tests/test_sd1_reverse_accessor_scope.py` [open](tests/test_sd1_reverse_accessor_scope.py) | A | `test_hidden_reverse_child_cannot_bypass_destination_scope` | — | — | 0 |
| `tests/test_sd2_forward_fk_filter_scope.py` [open](tests/test_sd2_forward_fk_filter_scope.py) | A | `test_boolean_composition_does_not_prune_unrelated_matches`<br>`test_direct_fk_ids_and_omission_keep_source_contract`<br>`test_each_forward_fk_chain_hop_is_scoped`<br>`test_empty_forward_fk_traversal_remains_noop`<br>`test_forward_fk_filter_uses_request_destination_scope`<br>`test_incompatible_destination_hook_fails_closed`<br>`test_missing_compiled_destination_type_fails_closed`<br>`test_nullable_fk_traversal_preserves_real_null`<br>`test_nullable_forward_fk_negative_filter_keeps_real_null`<br>`test_overridden_native_backend_keeps_two_argument_seam`<br>`test_schema_and_request_isolation`<br>`test_scope_failure_is_not_unscoped_fallback` | — | — | 0 |
| `tests/test_sd2_forward_o2o_filter_scope.py` [open](tests/test_sd2_forward_o2o_filter_scope.py) | A | `test_boolean_and_empty_forward_nodes_keep_visible_sources`<br>`test_forward_and_reverse_destination_policies`<br>`test_forward_scope_errors_fail_closed`<br>`test_null_and_direct_id_controls`<br>`test_reverse_then_forward_one_to_one_scopes_each_destination` | — | — | 0 |
| `tests/test_sd2_m2m_filter_scope.py` [open](tests/test_sd2_m2m_filter_scope.py) | A | `test_custom_through_fields_scope_both_m2m_directions`<br>`test_declared_reverse_m2m_accessor_does_not_reopen_filter_path`<br>`test_direct_m2m_target_ids_respect_both_destination_hooks`<br>`test_empty_m2m_child_is_noop`<br>`test_forward_m2m_ids_use_visible_destination_universe`<br>`test_forward_m2m_requires_visible_matching_target`<br>`test_m2m_absence_and_null_match_only_visible_universe`<br>`test_m2m_boolean_grouping_uses_visible_witnesses`<br>`test_m2m_hook_exception_fails_closed`<br>`test_m2m_hook_wrong_alias_fails_closed`<br>`test_m2m_not_complements_visible_parent_matches`<br>`test_m2m_request_visibility_changes_without_cache`<br>`test_m2m_scope_keeps_one_set_based_query_per_list`<br>`test_m2m_scope_uses_active_compiled_registry`<br>`test_nested_m2m_independent_and_keeps_one_visible_outer_target`<br>`test_nested_m2m_scopes_each_hop`<br>`test_reverse_m2m_ids_use_visible_destination_universe`<br>`test_reverse_m2m_not_and_unrelated_or_preserve_parent_set`<br>`test_reverse_m2m_query_name_follows_automatic_accessor`<br>`test_reverse_m2m_requires_visible_matching_target` | — | — | 0 |
| `tests/test_sd2_reverse_fk_filter_scope.py` [open](tests/test_sd2_reverse_fk_filter_scope.py) | A | `test_declared_reverse_accessor_cannot_reopen_filter_path`<br>`test_reverse_absence_nested_forward_null`<br>`test_reverse_fk_absence_and_null_predicates`<br>`test_reverse_fk_and_retains_split_and_grouped_witnesses`<br>`test_reverse_fk_boolean_and_nested_forward_hop`<br>`test_reverse_fk_boolean_null_branch_accepts_hidden_only`<br>`test_reverse_fk_direct_child_ids_are_destination_scoped`<br>`test_reverse_fk_empty_filter_and_hook_failure`<br>`test_reverse_fk_nested_boolean_null_and_match_branches`<br>`test_reverse_fk_nested_independent_and_keeps_one_visible_child`<br>`test_reverse_fk_not_complements_matching_parent_set`<br>`test_reverse_fk_positive_requires_visible_matching_child`<br>`test_reverse_fk_resolves_default_and_named_accessors`<br>`test_reverse_fk_scope_is_one_composed_query_not_per_parent`<br>`test_reverse_fk_source_and_destination_scopes_are_distinct`<br>`test_reverse_fk_uses_active_registry_without_scope_leak`<br>`test_reverse_fk_wrong_alias_hook_fails_closed`<br>`test_reverse_fk_wrong_model_hook_fails_closed` | — | — | 0 |
| `tests/test_serializer_type_custom_fields.py` [open](tests/test_serializer_type_custom_fields.py) | M | — | `CustomFieldsConflictTest.test_warns_and_skips_when_object_type_already_registered` | — | 8 |
| `tests/test_settings.py` [open](tests/test_settings.py) | M | — | `SettingsTest.test_default_settings` | — | 7 |
| `tests/test_settings_minimum_zero.py` [open](tests/test_settings_minimum_zero.py) | A | `test_approved_boundary_values_are_retained`<br>`test_default_is_unchanged`<br>`test_existing_nonnegative_bool_and_noninteger_policy_is_unchanged`<br>`test_negative_integer_limit_fails_on_public_setting_read`<br>`test_negative_limit_is_validated_lazily` | — | — | 0 |
| `tests/test_settings_tables_contract.py` [open](tests/test_settings_tables_contract.py) | A | `test_core_settings_rows_remain_in_one_markdown_table` | — | — | 0 |
| `tests/test_skip_include_directives.py` [open](tests/test_skip_include_directives.py) | M | — | — | — | 61 |
| `tests/test_success_response_cache.py` [open](tests/test_success_response_cache.py) | A | `test_cookie_bearing_queries_bypass_response_cache`<br>`test_disabled_cache_executes_without_response_cache_io`<br>`test_legacy_failed_entry_is_ignored_and_replaced`<br>`test_malformed_legacy_entry_is_ignored`<br>`test_partial_execution_error_recovers_then_success_hits`<br>`test_validation_error_is_not_stored_or_reused` | — | — | 0 |
| `tests/test_sync_async_http.py` [open](tests/test_sync_async_http.py) | A | `test_async_middleware_is_rejected_without_running_its_body`<br>`test_async_mutation_is_rejected_with_transaction_policy`<br>`test_async_resolver_returns_json_500_and_closes_owned_coroutines`<br>`test_callable_object_middleware_remains_active`<br>`test_custom_executor_owned_coroutine_is_closed`<br>`test_executor_exception_after_async_value_closes_owned_coroutine`<br>`test_falsey_object_middleware_is_ignored_like_native`<br>`test_sync_middleware_closes_nested_owned_resolver_coroutines`<br>`test_sync_middleware_keeps_borrowed_coroutine_open` | — | — | 0 |
| `tests/test_track2_optimizer.py` [open](tests/test_track2_optimizer.py) | M | `test_gfk_union_wrapper_bucket_walk_bounds_cycles_and_excludes_foreign_types`<br>`test_gfk_union_wrapper_inline_and_named_fragments_batch_targets` | `test_gfk_union_proxy_members_no_duplicate_content_type_valueerror` | — | 16 |
| `tests/test_utils.py` [open](tests/test_utils.py) | M | `UtilsTest.test_clean_dict_retains_root_scalars_and_prunes_emptied_lists`<br>`UtilsTest.test_clean_dict_retains_zero_and_false_without_mutating_input` | — | — | 4 |
| `tests/test_view_base.py` [open](tests/test_view_base.py) | M | `test_view_constructor_does_not_use_optimized_away_validation`<br>`test_view_constructor_rejects_conflicting_modes`<br>`test_view_constructor_rejects_invalid_schema` | — | — | 20 |
| `tests/test_view_layer_audit.py` [open](tests/test_view_layer_audit.py) | M | — | `MultipartBodyGuardTest.test_multipart_upload_above_data_upload_max_memory_size_is_accepted` | — | 12 |
| `tests/test_views_atomic_errors.py` [open](tests/test_views_atomic_errors.py) | A | `test_atomic_execution_error_does_not_invalidate_rolled_back_write`<br>`test_atomic_mutations_execution_error_rolls_back_native_write`<br>`test_atomic_mutations_explicit_flag_still_rolls_back`<br>`test_atomic_requests_execution_error_rolls_back_native_write`<br>`test_atomic_requests_explicit_flag_rolls_back_without_graphql_error`<br>`test_atomic_success_commits_and_invalidates`<br>`test_batch_failed_atomic_operation_then_success_invalidates_once`<br>`test_native_ok_false_does_not_retroactively_rollback_prior_root`<br>`test_nonatomic_execution_error_keeps_durable_write_and_invalidates` | — | — | 0 |
| `tests/test_views_body_cap_cache.py` [open](tests/test_views_body_cap_cache.py) | A | `CacheActiveBodyCapTests.test_authentication_denial_precedes_body_cap`<br>`CacheActiveBodyCapTests.test_body_at_cap_still_warms_and_hits_response_cache`<br>`CacheActiveBodyCapTests.test_cache_disabled_retains_early_base_view_rejection`<br>`CacheActiveBodyCapTests.test_disabled_cap_allows_the_same_query`<br>`CacheActiveBodyCapTests.test_get_with_invalid_body_keeps_bad_request_not_body_cap`<br>`CacheActiveBodyCapTests.test_oversized_cache_active_body_is_rejected_before_parse_or_cache`<br>`CacheActiveBodyCapTests.test_spoofed_low_content_length_still_rejects_actual_body`<br>`CacheActiveBodyCapTests.test_tightened_cap_rejects_an_already_cached_query` | — | — | 0 |
| `tests/test_views_cache_cookie_bypass.py` [open](tests/test_views_cache_cookie_bypass.py) | M | `CookieCacheBypassTest.test_issued_csrf_cookie_bypasses_next_server_cache_lookup` | — | — | 4 |
| `tests/test_views_cache_isolation.py` [open](tests/test_views_cache_isolation.py) | M | `InvalidResponseCacheTest.test_empty_http_response_is_not_cached` | — | `SentinelHitCheckTest.test_empty_cached_response_is_served_without_re_executing` | 11 |
| `tests/test_views_cache_key_framing.py` [open](tests/test_views_cache_key_framing.py) | A | `test_comment_boundary_cannot_select_another_cached_operation`<br>`test_custom_fetch_cache_key_override_remains_in_dispatch`<br>`test_frame_length_counts_utf8_bytes`<br>`test_get_components_and_body_have_unambiguous_boundaries`<br>`test_get_raw_body_is_documented_and_changes_default_cache_key`<br>`test_missing_and_empty_get_parameters_remain_equivalent`<br>`test_utf8_and_framing_like_text_cannot_cross_get_components` | — | — | 0 |
| `tests/test_views_multipart_body_bound.py` [open](tests/test_views_multipart_body_bound.py) | M | — | `UndeclaredMultipartLengthTest.test_asgi_chunked_multipart_over_the_cap_is_refused` | — | 6 |
