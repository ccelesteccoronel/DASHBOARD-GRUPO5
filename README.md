# Dinámica de ingresos y desigualdad — EPH-INDEC (Grupo 5)

Dashboard interactivo (Streamlit) que mide la desigualdad del **Ingreso Per Cápita Familiar (IPCF)** en los
**8 trimestres de 2024-2025**, para el **Total urbano EPH** (31 aglomerados) y el **aglomerado Corrientes**.

Fuente: [INDEC · Bases de microdatos EPH](https://www.indec.gob.ar/indec/web/Institucional-Indec-BasesDeDatos)

## Qué muestra
| Pestaña | Contenido |
|---|---|
| Resumen | Gini 2024 vs 2025 con veredicto honesto (¿cambio detectable?) y un guion para exponer |
| Evolución | Serie trimestral de Gini y Palma con intervalo de confianza 95 %; Corrientes y Total urbano en el mismo gráfico |
| Por decil | Variación **real** del ingreso por decil, participación en el ingreso, brechas D10/D1, D9/D1, D10/D5 |
| Curva de Lorenz | Gráfico de la **diferencia** de Lorenz (las curvas superpuestas no se distinguen) |
| Composición | Ingreso laboral / jubilaciones / transferencias por decil + Theil entre y dentro de grupos |
| Datos y descargas | Todas las tablas en CSV (estándar o Excel en español) y ZIP completo |
| Metodología | Fórmulas, límites, calidad de muestra (no respuesta) y verificación contra la versión anterior |

## Metodología
- **Unidad de análisis:** la persona, con el IPCF de su hogar. **Ponderador:** `PONDIH`.
- **Filtro de calidad:** `DECCFR` entre 1 y 10. Se informa cuántos casos excluye (pestaña Metodología).
- **Total urbano EPH:** los 31 aglomerados de la EPH; no es el total del país. **Corrientes:** `AGLOMERADO == 12`.
- **Deciles locales:** recalculados dentro de cada recorte; se agrupa por valor de IPCF sumando `PONDIH` antes de acumular población.
- **Gini:** regla del trapecio sobre la curva de Lorenz. **Palma:** ingreso del 10 % más rico / ingreso del 40 % más pobre.
- **Intervalos de confianza:** bootstrap de hogares (500 réplicas, percentil 95 %).
- **Ingresos reales:** IPC nacional nivel general (INDEC, base dic-2016), promedio trimestral con rezago de 1 mes
  (el ingreso se declara por el mes anterior), en pesos del T4 2025. Se puede cambiar con `--lag-ipc 0`.
- **Theil:** descompuesto entre/dentro de grupos según la condición laboral del jefe/a del hogar.
- **Composición:** ingresos individuales declarados (laboral = `P21`+`TOT_P12`; jubilaciones = `V2_M`;
  transferencias = `V5_M`+`V4_M`; otros = resto de `P47T`).

## Datos incluidos
`data/processed/` ya trae los resultados calculados con las bases reales: los 8 trimestres de 2024-2025 y los T4 de 2020 a 2023 (serie larga del Gini), por lo que el dashboard
funciona directamente. El ETL reproduce exactamente los valores de la versión anterior (Gini y población de T4 2024/2025;
ver pestaña *Metodología → Verificación*).

## Volver a calcular desde las bases (opcional)
```bash
pip install -r requirements.txt
# colocar usu_individual_T124 ... T425 y T420 ... T423 (.xlsx) en data/raw/
python src/etl.py --raw data/raw --boot 500
streamlit run app.py
```
En Colab: montar Drive, clonar el repo y apuntar `--raw` a la carpeta de Drive con las bases.
`data/external/ipc.csv` (columnas `mes,indice`) es el IPC nacional; si no existe, el ETL intenta bajarlo de datos.gob.ar.
Si se publica un dato nuevo del INDEC, reemplazar ese archivo por la serie oficial.

## Despliegue
Streamlit Community Cloud → *New app* → repo, rama `main`, archivo `app.py`. Los CSV de `data/processed/` deben estar versionados.

## Tests
`pytest -q` (Gini con valores conocidos, Palma, deciles con empates, descomposición de Theil, pipeline completo con datos sintéticos).

## Límites
Muestra y no censo; 8 trimestres no son una tendencia de largo plazo; IPC nacional aplicado a Corrientes;
subdeclaración de ingresos altos en la EPH; la incidencia de pobreza por CBT no está incluida (requiere ITF y adulto equivalente, no IPCF).

## Versión
1.0 (octubre de 2026). Nota: Palma usa cortes exactos sobre Lorenz; las brechas por decil usan deciles locales por grupos de IPCF idéntico (diferencia ≈2 %).
