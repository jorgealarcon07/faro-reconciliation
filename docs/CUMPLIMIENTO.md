# Cumplimiento de ingeniería

| Área | Comprobación |
|---|---|
| Arquitectura y repositorios | P02 independiente del repositorio y la base de P01. El primer commit fijó los estándares y la lógica se separa por responsabilidad |
| Datos | Semilla 2026, CC0 y SHA-256 por archivo. Prueba de fixture versionado y cotejo entre recibos y declaraciones |
| Contratos | JSON Schema de cinco interfaces, lock de hashes y validación de evidencia y manifiesto |
| Corrección | Enteros, claves de recepción/evento/efecto, diferencias exactas y pertenencia declarada de efectos |
| Recuperación | Pruebas con PostgreSQL y HTTP de interrupción antes y después del commit, replay, 429/500 y permutación de páginas |
| Operación | Cursor persistido, transición auditable, revisión que exige un efecto aplicado, prioridad y edad de excepción |
| Seguridad | SQL parametrizado, endpoints loopback, timeout y reintentos, límites de página y texto HTML mediante DOM. Rol propietario para desarrollo local |
| Reproducibilidad | Commit en manifiesto, huellas de entrada/salida, entorno fijado, oráculo manual y benchmark repetible |
| Consumo | CLI de consultas y revisión, HTML autónomo, JSON, CSV y capturas validadas en Chromium |
| Calidad de software | Ruff, pytest con base real y verificación de dependencias. JUnit y detalle de mediciones enlazados |
| Despliegue | Alternativa nativa verificada en PostgreSQL 17.12. Compose y CI remoto preparados y pendientes de ejecución |
| Mantenimiento | Runbook con reanudación, revisión, backups y ciclo de vida. Restauración externa pendiente de ensayo |
| Entrega | Código, fixture, evidencia, caso de estudio, recursos web e historial Git local |

[Suite JUnit](../reports/tests.xml) · [Mediciones](RESULTADOS.md) · [Runbook](RUNBOOK.md).
