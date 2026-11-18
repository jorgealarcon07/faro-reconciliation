# Resultados medidos · Proyecto 02

Ejecución del 17 de noviembre de 2026 en Windows 11, Python 3.12.14, PostgreSQL 17.12, 12 CPU lógicas y 15,11 GiB RAM. Las marcas de auditoría se guardan en UTC y pueden corresponder al día siguiente. El código ejecutado se identifica con el commit `97c6fe7b712ee76e7fc41d300b2577469c5c016c`. Las dependencias fijadas se instalaron en un entorno propio y `pip check` terminó correctamente.

## Piloto por HTTP y reconstrucción por archivo

Se leyeron **30 entregas de 10 lotes** en 1,44 s, contando arranque y apagado del simulador, revisión, exportación y reconstrucción. El motor conservó 30 recepciones, incluidas una repetición íntegra y un alias semántico. El oráculo comprobó los 10 lotes y la cobertura de cinco facturas. Resultado final de los lotes: **5 conciliados, 2 provisionales y 3 en excepción**, con siete motivos activos y 5.000 unidades menores de diferencia absoluta en lotes con declaración comparable.

El abono `syn_p1` quedó en 8.700 unidades menores tras la corrección. La suma ingenua calculó 20.700 y una diferencia de −12.000. La diferencia del lote había sido −100 antes de la revisión. Al interrumpir la página de corrección antes del commit, el cursor permaneció en 7. Al interrumpirla después, el cursor quedó en 8 y el siguiente arranque partió desde ahí. El simulador generó un 429 y un 500, ambos recuperados dentro del presupuesto de reintentos.

Hash canónico común de la proyección incremental HTTP y la reconstrucción por archivo:

```text
454c392e3468da7042c53daa6b911e94f0a09a2f4d39a2672f028892ccdad7c7
```

Los 3 lotes de excepción del oráculo se detectaron y se obtuvieron cero falsos cierres en ese fixture. Se midieron cuatro cargas adicionales con un oráculo separado de diferencias sembradas. [Manifiesto y etapas](../reports/demo/manifest.json) · [Reporte operativo](../reports/demo/index.html).

## Carga por archivo y consulta puntual

| Perfil | Facturas | Entregas | Ingestión | Entregas/s | Pico RSS Python | Lotes anómalos detectados/esperados |
|---|---:|---:|---:|---:|---:|---:|
| clean | 1.000 | 3.000 | 0,51 s | 5.901,64 | 54,09 MiB | 0/0 |
| duplicates | 1.000 | 3.076 | 0,54 s | 5.705,53 | 61,49 MiB | 0/0 |
| mixed | 1.000 | 3.076 | 0,55 s | 5.574,93 | 62,87 MiB | 10/10 |
| mixed | 32.500 | 100.000 | 25,60 s | 3.905,92 | 390,15 MiB | 325/325 |

Se usaron páginas de 1.000 eventos. El reloj de ingestión cubre lectura desde el fixture en memoria, validación y persistencia transaccional. La preparación del fixture se mide por separado en el JSON. El muestreo RSS incluye Python y sus datos en memoria. PostgreSQL se ejecutó en un proceso separado y su memoria queda fuera de esa cifra. El conjunto de 100.000 entregas contenía 65.000 movimientos válidos y 325 lotes con un desfase sembrado de −100 unidades menores. Se comprobaron importes y estados de todos los lotes, con 325/325 detecciones y cero falsos cierres en ese conjunto.

La búsqueda puntual de movimientos para un lote usó `Index Scan` y tomó 0.046 ms según PostgreSQL. Forzar una lectura sin índices en esa sesión dio `Seq Scan` y 5.554 ms. Es una observación con planes y buffers registrados, con las cachés del laboratorio y una consulta pequeña. Las cifras describen esta máquina y esta distribución. [Mediciones y EXPLAIN](../reports/benchmark.json).

## Verificación y pendientes

- **35 pruebas correctas**, 3,83 s según JUnit. Cubren contrato, importes, permiso de cierre, 429/500, página atómica, conflictos, referencias tardías, permutaciones y CLI. [JUnit](../reports/tests.xml).
- Chromium comprobó las tres vistas, el filtro de excepciones, navegación por teclado y evidencia de resolución. Se guardaron tres capturas con cero errores JavaScript observados. [Validación](../reports/ui-validation.json) · [Capturas](../assets/web/README.md).
- Compose y GitHub Actions están preparados. La validación funcional se ejecutó con PostgreSQL nativo. Docker y CI remoto siguen pendientes de ejecución en sus entornos, al igual que una restauración externa de backup. El escenario y las mediciones son sintéticos.
