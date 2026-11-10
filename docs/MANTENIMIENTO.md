# Mantenimiento, backup y recuperación

Guía técnica de los datos de PC Parts Organizer, procedimientos soportados y diagnóstico. Complementa a `GUIA_USUARIO.md` y `ARQUITECTURA.md`.

> **Restricción.** Las operaciones **soportadas** se realizan desde la interfaz. Las intervenciones manuales sobre los archivos son procedimientos técnicos de último recurso y deben hacerse con la aplicación cerrada y con una copia previa.

---

## 1. Archivos de datos y ubicación

Windows: `%LOCALAPPDATA%\PCPartsOrganizer\` (Linux/macOS: `~/.local/share/PCPartsOrganizer/`).

| Archivo | Formato | Contenido | Escritor |
|---|---|---|---|
| `components.json` | JSON, `schema_version` 4 | Inventario + builds + perfiles técnicos | `storage.save_project_state` (atómico) |
| `settings.json` | JSON, `schema_version` 1 | Idioma (`es`/`en`) | `save_language_preference` (atómico) |
| `catalog.sqlite3` | SQLite | Referencias comerciales | `CatalogStorage` |
| `backups\pre-restore\inventory-pre-restore-<stamp>.json` | JSON | Copia preventiva previa a restauración | `create_pre_restore_backup_from_state` |

## 2. Inventario JSON vs. catálogo SQLite

- **Inventario (`components.json`)**: tu colección personal, con builds y perfiles. Formato abierto, validado al leer/escribir, acepta esquemas 1–4 y escribe 4.
- **Catálogo (`catalog.sqlite3`)**: biblioteca de referencia reutilizable. Esquema interno `CATALOG_SCHEMA_VERSION = 1`. Se crea/actualiza al usar la pestaña Catálogo.

No son intercambiables: el catálogo no alimenta perfiles ni verificaciones del inventario, y el inventario no se importa al catálogo automáticamente.

## 3. Procedimientos de backup existentes

**Exportar copia** (Inventario → Exportar copia):
- Exporta el estado completo a JSON en el destino elegido.
- El archivo es verificable con `read_inventory_file` (incluye SHA256).

**Copia preventiva de restauración** (automática):
- Antes de sustituir el estado, la aplicación crea `backups\pre-restore\inventory-pre-restore-<stamp>.json` y la verifica.
- Nunca sobrescribe: si existe el nombre, añade sufijo numérico.

No existe programación automática de copias periódicas ni herramienta de backup externa. La copia manual de los archivos de datos es el procedimiento técnico disponible.

## 4. Recuperación soportada

1. **Restaurar copia** (Inventario → Restaurar copia).
2. Selecciona un JSON de copia.
3. Se muestra una **vista previa** (componentes, builds, perfiles, esquema, categorías/estados).
4. Confirmas la sustitución. Se crea la **copia preventiva** del estado actual.
5. El archivo se revalida (incluido SHA256) tras la vista previa para detectar cambios.

Advertencias de la vista previa: copia vacía, esquemas antiguos sin builds (v1/v2) o sin perfiles (v1/v2/v3). En esos casos la restauración sustituye el proyecto y puede dejarlo sin builds/perfiles.

## 5. Verificaciones de integridad disponibles

- **JSON**: validación estructural y de referencias cruzadas al leer; SHA256 en copias exportadas; `PRAGMA integrity_check` aplica solo al SQLite.
- **SQLite**: verificación de esquema/columnas al inicializar (`CatalogStorage.initialize`). Para una comprobación externa puntual, abre en **modo solo lectura**:

```bat
python -c "import sqlite3; c=sqlite3.connect('file:%LOCALAPPDATA%/PCPartsOrganizer/catalog.sqlite3?mode=ro', uri=True); print(c.execute('PRAGMA integrity_check').fetchall()); c.close()"
```

- **Idioma**: `tests/test_localization.py` valida paridad ES/EN.

## 6. Versiones de esquema y perfiles

- Inventario: esquemas soportados **1–4**; escritura **4**.
- Ajustes: `schema_version` **1**.
- Catálogo: `CATALOG_SCHEMA_VERSION` **1**.
- Perfiles: `PROFILE_VERSION = 2` (forma estructural), `PROFILE_REGISTRY_VERSION = 7` (registro de atributos/validación).
- Motor: `ENGINE_RULESET_VERSION = "t17.12-v1"`.

## 7. Compatibilidad de perfiles antiguos

- Un perfil es interpretable si su versión estructural está soportada; `validate_profile_for_category` lo revalida contra el registro actual.
- Si el registro cambia de versión, un perfil puede requerir revisión; la aplicación lo detecta al cargar/guardar.
- No se migraron ni eliminaron atributos automáticamente; los perfiles existentes se conservan.

## 8. Qué ocurre al cerrar la aplicación

- El estado se persiste en cada mutación; no hay guardado diferido al cerrar.
- Cerrar con el aspa o **Cerrar** no ejecuta copias adicionales.
- No dejes la aplicación abierta durante ediciones manuales de los archivos.

## 9. Diagnóstico de errores comunes

| Síntoma | Causa probable | Acción |
|---|---|---|
| «No se pudo guardar» | Permisos o disco | Verifica escritura en `%LOCALAPPDATA%\PCPartsOrganizer` |
| Catálogo no disponible | Base corrupta o esquema inesperado | No la edites; reinstala/recupera el catálogo con una copia verificada |
| La copia no se valida | Archivo modificado o truncado | Vuelve a exportar; no restaura |
| Idioma vuelve al anterior | Fallo guardando `settings.json` | Cambia de nuevo; verifica permisos |
| Resultados obsoletos | Cambiaron componentes/perfiles | Pulsa **Analizar compatibilidad** de nuevo |

## 10. Archivos que deben protegerse

- `components.json`, `settings.json`, `catalog.sqlite3`, `backups\`.
- Copia estos archivos (con la aplicación cerrada) antes de intervenciones manuales.

## 11. Operaciones manuales que deben evitarse

- Editar `components.json` a mano sin validar el esquema y las referencias cruzadas.
- Editar `catalog.sqlite3` con herramientas externas.
- Restaurar copias de otro equipo sin verificar esquemas.
- Eliminar `backups\` o sobrescribir copias preventivas.
- Forzar el cierre durante una escritura.

---

## Distinción: interfaz vs. procedimiento técnico

| Necesidad | Vía soportada | Vía técnica (último recurso) |
|---|---|---|
| Copia de seguridad | Exportar copia | Copiar archivos con la app cerrada |
| Restaurar | Restaurar copia + vista previa + copia preventiva | Restaurar manualmente `components.json` verificado |
| Recuperar catálogo | Reimportar CSV/JSON verificado | Restaurar `catalog.sqlite3` desde copia |
| Verificar integridad | Validación en restauración | `PRAGMA integrity_check` en modo solo lectura |

Las vías técnicas no disponen de interfaz ni de las garantías de validación automática; úsalas solo si la interfaz no es viable y siempre con copia previa.
