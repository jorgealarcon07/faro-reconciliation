# Estándares de ingeniería · Faro 02

17 de noviembre de 2026. Este documento se adopta antes de programar. Conserva el enfoque del proyecto 01 y aplica sus verificaciones a un flujo de conciliación transaccional.

| Área | Práctica | Evidencia de cumplimiento |
|---|---|---|
| Arquitectura y código | Separar contratos, adaptadores, cálculo de dominio, persistencia y consumo. Usar funciones puras para las reglas monetarias y transacciones explícitas para las escrituras | Pruebas de dominio aisladas y pruebas con PostgreSQL real |
| Dependencias y entorno | Python 3.12, dependencias fijadas, entornos aislados y PostgreSQL dedicado al proyecto | `pip check`, versiones en el manifiesto y ejecución nativa o Compose |
| Datos y licencias | Fixtures originales CC0, semilla fija, UTC, hashes y fuente declarada. Contratos JSON Schema y versión 1.0.0 | Verificación de archivos, contratos y casos manuales independientes |
| Configuración y secretos | Parámetros explícitos, loopback para el simulador, credenciales en entorno o archivo ignorado | Revisar configuración y archivos versionados |
| Integridad | Unidades menores enteras, claves independientes de recepción, evento y efecto. Mantener historial de entrada y recalcular proyecciones deterministas | Repeticiones, permutaciones, colisiones, devoluciones y cierres |
| Recuperación | Guardar recepción, efectos, auditoría y cursor en una transacción. El cierre se deriva de la evidencia y de las invariantes | Fallos antes y después del commit y reejecución contra la misma base |
| Seguridad | SQL parametrizado, límites de entrada, timeout, reintentos acotados, HTML escapado y servicios de laboratorio en red local | Casos adversos y revisión de permisos y configuración |
| Observabilidad | Medir filas, estados, reintentos, checkpoint, latencia, memoria y diferencias por lote. Registrar rol y motivo de revisión | Manifiesto, fixtures, JUnit, cola y auditoría |
| Pruebas y CI | Ruff, pruebas unitarias, integración PostgreSQL, demo CLI y validación de contratos en GitHub Actions | JUnit y resultados locales. Reportar por separado la ejecución remota |
| Despliegue y mantenimiento | Compose y ruta nativa, migración repetible, runbook, documentación de restauración, alcance local y limpieza conservadora | Conservar esquema y datos entre reejecuciones. Documentar comprobaciones pendientes |
| Entrega | README, arquitectura, caso de estudio, benchmarks, capturas y commits revisables | Contrastar artefactos y oráculos con la aceptación. Actualizar el plan solo para el proyecto ejecutado |

El cierre del laboratorio requiere demostrar el recorrido HTTP y por archivo, comparar los resultados con el oráculo, verificar recuperación y explicar un abono desde la CLI o el reporte. El escaneo de entrega excluye credenciales, binarios instalados y clústeres de base de datos.
