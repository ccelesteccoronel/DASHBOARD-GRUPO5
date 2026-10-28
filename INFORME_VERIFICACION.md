# Informe de verificación — Grupo 5

## Verificación numérica (con las 8 bases reales)
El nuevo ETL reproduce exactamente la versión anterior: Gini Total urbano 0,428276 / 0,424758, Gini Corrientes 0,330571 / 0,335805,
población ponderada de Corrientes 392.641 / 395.388 (T4 2024 / T4 2025). También reproduce la tabla del tutor
(IPCF promedio D1 $99.451 → $109.085; D10 $872.720 → $1.072.044; D10/D5 3,48 → 3,07; decil 10: 26,2 % → 24,7 %).

## Devolución del tutor → qué se hizo
| Punto | Estado |
|---|---|
| 1. Dos trimestres no son tendencia / sin IC | Hecho: 8 trimestres, IC 95 % bootstrap, veredicto "cambio detectable: sí/no" |
| 2. Ingresos sin deflactar | Hecho: IPC nacional, pesos del T4 2025 (ver corrección abajo) |
| 3. Solo se cuentan los indicadores que suben | Hecho: guion automático con Gini, D10/D1, D10/D5 y % del decil 10 |
| 4. Lorenz indistinguibles | Hecho: gráfico de diferencia de Lorenz |
| 5. Falta composición del ingreso | Hecho: laboral / jubilaciones / transferencias / otros por decil |
| Palma, Theil, no respuesta, serie larga, Corrientes vs Nacional | Hecho |
| Metodología documentada (fuente, n, fórmulas, supuestos, límites, repo) | Hecho: pestaña Metodología + README |
| Pobreza con CBT | No incluido (requiere ITF y adulto equivalente; coordinar con Grupos 2 y 3) |

## Resultados que cambian el relato
1. **Gini**: ninguna variación T4 2024 → T4 2025 es distinguible de cero (Corrientes +0,0052, IC [-0,038 ; +0,052]; Total urbano -0,0035). Única variación interanual significativa: T1 del Total urbano (-0,031).
2. **Corrección al tutor:** "caída real para todos" vale para D1 (-16,5 %) y D10 (-6,5 %) en Corrientes, pero no para los deciles 4 a 9, que subieron en términos reales. Además, en Corrientes **ningún** decil tiene una variación significativa (n ≈ 1.000 personas / 340 hogares por trimestre): la tesis "ganó el medio" es una hipótesis, no un hallazgo.
3. En el Total urbano, 9 de 10 deciles ganaron poder de compra de forma significativa en el T4.
4. Corrientes tiene muestra chica: los intervalos son anchos (±0,03 en Gini).

## Problemas del código anterior
- Se llamaba "hogares" a deciles calculados por persona (ahora se explicita: persona con IPCF del hogar).
- "Nacional" eran los 31 aglomerados de la EPH (ahora "Total urbano EPH").
- Variación del Gini con flecha roja sin intervalo.
- Las bases 2024-2025 ya no traen V2_M ni V5_M: vienen abiertas en V2_01..03_M y V5_01..03_M. El ETL las suma (sin esto, jubilaciones y transferencias daban 0).

## Supuestos a confirmar
- IPC: serie reconstruida con variaciones mensuales del INDEC y contrastada con 117,8 % (2024), 31,5 % (2025) y 84,5 % (ene-25 interanual). Rezago de 1 mes (`--lag-ipc 0` para quitarlo). Se aplica el IPC nacional también a Corrientes.
- Los subcomponentes V2_0x y V5_0x se suman completos; conviene revisarlos contra el diccionario de registros de la EPH.
- El cuaderno de NotebookLM no era accesible desde acá: no se contrastó con la investigación del grupo.

## Seguimiento del tutor (23-oct-2026)
| Punto | Estado |
|---|---|
| IC del Gini (sin flecha) | Hecho: punto con bigote y veredicto "cambio detectable: sí/no" |
| Ingresos deflactados | Hecho (IPC, pesos del T4 2025; selector real/corrientes) |
| Contar los indicadores que bajan | Hecho: el guion incluye D10/D5 y la participación del decil 10 |
| Composición del ingreso | Hecho (pestaña 5) |
| Diferencia de Lorenz | Hecho (pestaña 4) |
| Link al repositorio y versión | Hecho: pestaña Metodología (link, fecha de procesamiento, archivos usados, semilla) |
| Formato numérico argentino | Hecho: tablas y gráficos (0,3306 · 392.641 · 9,83 veces · 24,7 %) |
| Sin emojis en el título | Hecho |
| Serie larga del Gini | Hecho: T4 2020-2025 con IC 95 %. Corrientes 0,394 → 0,336; Total urbano 0,432 → 0,425. El T4 2020 está afectado por la pandemia |
| Fecha de descarga de las bases | Hecho: T1-T3 de 2024-2025 el 13/10/2026 y T4 de 2024-2025 el 22/07/2026 (tabla en Metodología). T4 2020-2023 el 13/10/2026 |

Nota sobre "ganó el medio": en Corrientes la lectura es consistente con los puntos estimados (D1 -16,5 %, D10 -6,5 %, deciles 4-9 al alza),
pero ningún decil es estadísticamente distinguible de cero; conviene presentarla como hipótesis.
