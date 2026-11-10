# Inicio rápido — PC Parts Organizer

Recorrido práctico del primer arranque a la ficha exportada, con las acciones que realmente existen en la interfaz.

## 0. Arrancar

```bat
python -m pc_parts_organizer
```

La primera vez se crean el directorio de datos y los archivos de estado (vacíos).

## 1. Consultar el catálogo

1. Pestaña **Catálogo**.
2. Busca por fabricante o modelo (p. ej. «AMD»).
3. Filtra por categoría y ajusta `Mostrar` si hay muchas referencias.
4. Consulta las especificaciones y notas de una referencia en el panel de detalle.

## 2. Añadir varios componentes al inventario

1. Pestaña **Inventario** → **Añadir desde catálogo**.
2. Selecciona varias filas (Mayús para rango, Ctrl para sumar).
3. Cambia de página si hace falta: la selección se conserva.
4. Comprueba **Seleccionados: N** y pulsa **Añadir seleccionados**.
5. Revisa el informe con creados y omitidos (duplicados con su nombre coincidente).

> Los componentes quedan en el inventario **sin asignar** a ningún equipo.

## 3. Crear una build

1. Pestaña **Equipos** → **Añadir equipo**.
2. Pon nombre (único), tipo (Actual/Planificado) y notas.
3. Selecciona componentes disponibles y confirma con **Guardar**.

## 4. Completar un perfil técnico

1. Inventario → selecciona un componente → **Ver detalles** → **Añadir datos técnicos**.
2. Añade los atributos que apliquen (p. ej. RAM: `memory_generation`, `module_form_factor`, `total_capacity_gb`, `module_count`).
3. Registra procedencia, confianza y, si tienes respaldo, `evidence_ref` + fecha para marcar **Verificado**.

## 5. Revisar la calidad de datos

1. Inventario → **Revisar datos**.
2. Filtra por categoría/estado y usa la **cola de revisión** para ver atributos pendientes y las reglas que los consumen.
3. Corrige valores o aporta evidencia; los hallazgos bloqueados se actualizan al volver a analizar.

## 6. Analizar la compatibilidad

1. Equipos → **Ver detalles** de la build → **Analizar compatibilidad**.
2. Interpreta el resultado global y los hallazgos por severidad.
3. Revisa **Relaciones no evaluadas** y **Limitaciones** antes de concluir.

## 7. Consultar la auditoría técnica

En el mismo detalle de build, sección **Auditoría técnica**: hallazgos demostrados, verificación pendiente, datos insuficientes y atributos relevantes pendientes con su componente y relación (directa/compartida).

## 8. Comparar dos builds

1. Crea una segunda build (p. ej. cambiando RAM o placa).
2. Equipos → **Comparar equipos** → selecciona A y B.
3. Revisa comunes, añadidos, retirados, sustituidos y hallazgos nuevos/comunes/resueltos.

## 9. Exportar una ficha

1. En el detalle de la build, **Exportar ficha**.
2. Elige **Markdown (`.md`)** o **Texto (`.txt`)**.
3. Elige destino en el diálogo de guardado (no se sobrescribe sin confirmar).
4. Revisa el contenido: composición, hallazgos, evidencia, limitaciones y auditoría.

## Resumen del recorrido

```
Catálogo → Añadir varios → Build → Perfil técnico → Calidad
        → Analizar → Auditoría → Comparar → Exportar ficha
```

## Recordatorios

- `compatible` en una relación no certifica compatibilidad total.
- Las incompatibilidades requieren atributos verificados.
- Exporta una copia antes de restauraciones o ediciones masivas.
