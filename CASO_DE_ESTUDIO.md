# Faro · Conciliación de pagos con trazabilidad

## Problema

Un equipo de operaciones recibe capturas, devoluciones y comisiones mientras el procesador declara los abonos. Si se suman las entregas sin distinguir su identidad, una repetición puede inflar el importe. Si una devolución llega antes que la captura, también puede quedar sin explicación. El equipo necesita saber qué lote puede cerrar, qué movimiento falta y qué evidencia respalda una corrección.

Los proveedores documentan fallos de entrega y la necesidad de relacionar abonos con movimientos liquidados. Faro aplica esos modos de fallo a una simulación local. [Stripe, entrega de eventos](https://docs.stripe.com/webhooks#event-delivery-behaviors) · [Reporte de abonos](https://docs.stripe.com/reports/payout-reconciliation).

## Solución y decisiones

El simulador ofrece páginas por HTTP. La base conserva todo lo recibido, valida contratos, aplica efectos únicos y calcula una proyección por lote. La misma transacción registra movimientos, auditoría y cursor. El conciliador también puede leer los mismos datos por archivo. Una declaración final identifica los efectos esperados, lo que permite detectar faltantes aunque el saldo sea cero.

La demo sigue una factura por 10.000 unidades menores. Dos capturas de 6.000 y 4.000, una devolución de 1.000 y una comisión de 300 explican un abono de 8.700. El recibo duplicado y el alias con otro ID quedan registrados. La primera declaración de 8.600 deja una excepción de −100 y bloquea el intento de cierre. La declaración revisada referencia la original, cuadra con los movimientos y permite registrar la resolución de la analista.

## Evidencias

El oráculo manual verificó los diez lotes del piloto. El resultado final fue cinco conciliados, dos provisionales y tres en excepción. La suma ingenua por recepción calculó 20.700 para el abono del caso y una diferencia de −12.000. El motor calculó 8.700 y conservó las ocho recepciones asociadas, la declaración anterior y el motivo de resolución. La reconstrucción desde archivo y la ingestión incremental HTTP produjeron la misma huella. [Reporte de la demo](reports/demo/index.html) · [Manifiesto](reports/demo/manifest.json).

La suite cubre la reversión de devoluciones, el sobrepago observable, el conflicto entre variantes, el ajuste tardío y la recuperación antes y después del commit. La carga de escala contrasta los lotes con anomalías sembradas y guarda planes de ejecución sobre PostgreSQL. [Resultados medidos](docs/RESULTADOS.md) · [Pruebas](reports/tests.xml).

## Aprendizajes y alcance

El cursor debe compartir la transacción que aplica efectos. Identificar recepciones repetidas tampoco basta para distinguir dos mensajes que se refieren al mismo pago. El monto final y los efectos esperados responden preguntas diferentes. Conservar las tres evidencias permite explicar el cierre y volver a evaluar un lote si cambia lo observado.

La simulación agrupa referencias dentro del mismo lote y usa un solo procesador y moneda. No cuantifica ahorro o recaudación en una empresa. La diferencia de cobertura requiere contexto comercial adicional. La alternativa nativa se ejecutó en Windows. Compose y CI remoto están configurados y su ejecución queda pendiente.
