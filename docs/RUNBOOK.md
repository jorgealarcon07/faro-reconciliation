# Operación y recuperación

## Preparar el entorno

La ruta nativa usa PostgreSQL 17 con un clúster separado y se ejecuta en una sola sesión para el sandbox de Windows. El script recibe el directorio de binarios, prepara un clúster con contraseña efímera, registra resultados y detiene ese clúster. Los directorios de trabajo quedan en `.runtime/`. Se puede usar una instalación PostgreSQL propia proporcionando `FARO2_DB_HOST`, `FARO2_DB_PORT`, `FARO2_DB_NAME`, `FARO2_DB_USER` y `FARO2_DB_PASSWORD`. El puerto de laboratorio es 55433.

Para Compose, crear `.env` con una contraseña local, ejecutar `docker compose run --rm app demo --output /out/demo` y usar `docker compose stop` para detener la base. El volumen de resultados conserva los archivos. Se puede copiar un informe con un contenedor temporal de solo lectura o consultar la ruta nativa ya incluida. La ejecución Compose requiere Docker y se verifica separadamente.

## Recuperar después de un fallo

1. Mantener el mismo caso, bundle y fuente. El archivo `source.json` vincula el caso con sus hashes.
2. Ejecutar de nuevo el mismo comando `ingest`. El cliente consulta la próxima posición confirmada. Si el fallo ocurrió antes del commit, repite esa página. Si ocurrió después, retoma en la siguiente.
3. Comparar `payout` y `queue` con el manifiesto. La auditoría muestra transiciones, incluidas las de dependencias y correcciones. Guarde el stdout JSON del comando de ingestión si necesita conservar el total de reintentos y la duración.
4. Si la fuente se alteró, conservar ambos archivos y verificar hashes. El contrato de una corrección es un feed nuevo con `--extra`, no editar el checkpoint ni los recibos originales.

```powershell
faro-reconcile ingest --case operaciones --source data/fixtures --extra local/correction.jsonl
faro-reconcile payout --case operaciones syn_p1
faro-reconcile resolve --case operaciones --payout syn_p1 --issue ID_DE_LA_COLA --actor analista_faro --reason "Revisión de declaración verificada" --evidence syn_e_1_revision
```

Una corrección válida añade una revisión que referencia el efecto de la declaración anterior o una reversión ligada a un movimiento. Conserve el ID de excepción de la cola antes de incorporar la corrección. El comando `resolve` valida que ese ID haya existido y que el lote ahora concilie. Los conflictos de identidad persistentes requieren investigación y un conjunto revisado que pueda reejecutarse como caso nuevo. Borrar variantes para cerrar violaría el contrato del laboratorio.

Si llega una factura que faltaba, use `faro-reconcile register --case operaciones --invoice local/invoice.json` con un objeto conforme a `invoice.schema.json`. Para un lote nuevo, use `faro-reconcile register --case operaciones --payout syn_p11`. El registro añade evidencia al catálogo, reprocesa los eventos pendientes en la misma transacción y rechaza cambios al importe original de una factura ya registrada.

## Conservación

`clean` conserva los datos. Para conservar una ejecución necesita el bundle y su manifiesto, sus feeds de corrección y el backup de PostgreSQL. Una restauración de infraestructura llevaría el backup a una base nueva, validaría los conteos y compararía la huella con el reporte guardado. Esa restauración externa queda pendiente de ensayo. Para eliminar una base de laboratorio después de una revisión, primero identifique y detenga su clúster específico, exporte las evidencias y confirme que se puede descartar. El script no elimina clústeres o volúmenes.

El servidor HTTP del simulador solo escucha en loopback. En la ruta nativa el clúster está aislado. Un entorno con usuarios reales requiere control de accesos, rotación de credenciales, backups probados y política de retención.
