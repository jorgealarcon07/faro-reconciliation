# Contratos v1

- `payment_event` contiene `namespace`, `event_id`, `business_effect_id`, tipo, importe entero, moneda, lote, factura cuando aplica, referencia, horas UTC y versión. `payout_id` es obligatorio en este productor porque todos sus movimientos se liquidan por lote. La factura puede ser nula para comisión y abono.
- `payout_statement` usa tipo `payout`, `finalized` explícito y `expected_effect_ids`. Una revisión referencia el efecto de la declaración anterior. El marcador final incorpora su conjunto de movimientos para tolerar el desorden de las entregas.
- `invoice` contiene importe original positivo. El escenario fija exponente decimal 2 para COP. El saldo operativo es una diferencia de cobertura y se interpreta según el contexto comercial.
- `decision_record` identifica lote, excepción, rol, motivo y evidencia. El ID de excepción se deriva de lote, motivo y referencia. La misma resolución para el mismo registro de auditoría es idempotente.
- `run_manifest` registra ejecución, origen sintético, semilla, contratos, hash de datos, Git y mediciones disponibles.

Los casos actúan como particiones de laboratorio dentro del namespace. Las claves de idempotencia se aplican por caso. El cursor es la próxima posición y se fija por fuente inmutable. Los eventos incluso inválidos se guardan con su checksum en `raw_delivery`. La validación no incorpora valores desconocidos a los importes.

Los contratos y sus hashes están en `contracts/v1` y `contracts.lock.json`. Los checksums de la proyección excluyen horas de ingestión y auditoría porque varían por transporte y reintento. El contrato opcional de facturas de P01 puede integrarse con un adaptador futuro que respete procedencia, moneda y semántica de cobertura.
