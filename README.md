# Gestión de Ingresos y Gastos

Sistema web sencillo para controlar los ingresos y gastos de un pequeño negocio.
Funciona en computadora, tableta y teléfono móvil.

## Funciones

- **Registrar movimientos**: ingresos y gastos con importe, fecha, categoría y descripción.
  El botón «Guardar y añadir otro» agiliza la carga diaria.
- **Editar y eliminar**: siempre con confirmación antes de borrar.
- **Panel de resumen**: total de ingresos, total de gastos y saldo, calculados automáticamente;
  resultado del mes y de la semana, gráfico de los últimos 6 meses y gastos por categoría.
- **Categorías**: Ventas, Servicios, Compras, Transporte y Otros vienen creadas.
  Puedes añadir, renombrar, cambiar color o eliminar categorías. Si una categoría tiene
  movimientos, se pide a qué categoría moverlos, para que nunca se pierda información.
- **Filtros**: por período (hoy, esta semana, este mes, mes anterior, este año o fechas
  personalizadas), tipo, categoría y texto de la descripción, con totales del resultado filtrado.
- **Informes**: resumen mensual (mes a mes del año) y semanal (semana a semana del mes),
  con gráfico, tabla, totales, promedios y desglose por categoría. Se pueden imprimir o guardar en PDF.
- **Exportar a Excel** (CSV) los movimientos, con o sin filtros.
- **Base de datos SQLite**: los datos se guardan en el archivo `datos/finanzas.db` y no se pierden al cerrar.
- **Seguridad**: acceso con contraseña y protección de formularios.
- **Copias de seguridad**: copia automática diaria (se conservan 30), descarga manual y restauración.

Los importes se guardan como números enteros en céntimos, por lo que todas las sumas
son exactas (sin errores de redondeo).

---

## Instalación (Windows)

1. Instala **Python 3.10 o superior** desde <https://www.python.org/downloads/>.
   Durante la instalación marca la casilla **«Add python.exe to PATH»**.
2. Copia la carpeta `gestion-finanzas` donde quieras (por ejemplo, en Documentos).
3. Haz doble clic en **`iniciar.bat`**.
   - La primera vez prepara todo automáticamente (necesita Internet, menos de un minuto).
   - Se abrirá el navegador en `http://localhost:5000`.
4. La primera vez, escribe el nombre de tu negocio y elige una contraseña.

> Mientras uses el sistema, **no cierres la ventana negra** que se abre. Para apagarlo, ciérrala.

En macOS o Linux: ejecuta `sh iniciar.sh` en una terminal.

### Abrirlo desde el móvil o la tableta

Con el sistema iniciado en la computadora, la ventana negra muestra una dirección como
`http://192.168.1.20:5000`. Escríbela en el navegador del móvil (conectado a la **misma red Wi-Fi**).

- Si Windows pregunta por el **Firewall**, pulsa **«Permitir acceso»** (redes privadas).
- Consejo: en el móvil, usa «Añadir a pantalla de inicio» para abrirlo como una aplicación.

---

## Uso diario

| Quiero… | Cómo |
|---|---|
| Registrar una venta | Botón **Nuevo movimiento** (o **+** en el móvil) → **Ingreso** → importe, categoría → **Guardar** |
| Registrar un gasto | Igual, eligiendo **Gasto** |
| Corregir un movimiento | **Movimientos** → icono del lápiz |
| Borrar un movimiento | Icono de la papelera → confirmar |
| Ver cuánto gané este mes | **Resumen**, tarjeta del mes; o **Informes → Mensual** |
| Ver una semana concreta | **Informes → Semanal** y elige el mes |
| Buscar movimientos | **Movimientos** → filtros de período, tipo, categoría o texto |
| Pasar datos a Excel | **Movimientos → Exportar** (respeta los filtros aplicados) |
| Imprimir un informe | **Informes → Imprimir** (también permite «Guardar como PDF») |

Los importes se pueden escribir como `1500`, `1500.50` o `1,500.50`.
En **Ajustes** puedes cambiar el símbolo de moneda y el formato (`1,234.56` o `1.234,56`).

---

## Copias de seguridad (muy importante)

Todos tus datos están en un solo archivo: **`datos/finanzas.db`**.

- **Automáticas**: cada día que uses el sistema se guarda una copia en `datos/copias/`
  (se conservan las últimas 30).
- **Manuales**: en **Ajustes → Copias de seguridad → Descargar copia**.
  Recomendado: **una vez por semana**, guarda esa copia fuera de la computadora
  (memoria USB, Google Drive, correo electrónico…). Si la computadora se estropea, la copia te salva.
- **Restaurar**: en **Ajustes → Restaurar copia**, elige el archivo `.db` y confirma.
  Antes de restaurar, el sistema guarda automáticamente el estado actual por si acaso.
  Tu contraseña actual se mantiene.

**Cambiar de computadora**: instala el sistema en la nueva y copia la carpeta `datos`
completa (o restaura una copia descargada desde Ajustes).

### Recomendaciones de seguridad

- Usa una contraseña que no utilices en otros sitios y cámbiala desde **Ajustes** si alguien más la conoce.
- No compartas el archivo `datos/clave_secreta.txt`.
- Si olvidas la contraseña: cierra el sistema, abre `datos/finanzas.db` con
  [DB Browser for SQLite](https://sqlitebrowser.org/), borra la fila `password_hash`
  de la tabla `ajustes` y vuelve a iniciar; te pedirá una contraseña nueva. Tus datos no se pierden.

---

## Publicarlo en Internet (opcional)

Si quieres usarlo desde cualquier lugar (no solo en tu Wi-Fi), puede alojarse en un servicio
como **PythonAnywhere** (tiene plan gratuito):

1. Crea una cuenta y sube la carpeta del proyecto (sin `.venv`).
2. En una consola de PythonAnywhere: `pip install --user -r requirements.txt`.
3. Crea una *Web app* «Manual configuration» y en el archivo WSGI escribe:
   ```python
   import sys
   sys.path.insert(0, "/home/TU_USUARIO/gestion-finanzas")
   from app import create_app
   application = create_app()
   ```
4. Recarga la web app y entra con la dirección que te asignan (con HTTPS).

---

## Información técnica

- Python 3.10+, Flask, SQLite, HTML/CSS/JavaScript sin dependencias externas (funciona sin Internet).
- Servidor de producción: Waitress (`python app.py`).
- Variables opcionales: `PORT` (por defecto 5000), `HOST` (por defecto `0.0.0.0`),
  `ABRIR_NAVEGADOR=0` para no abrir el navegador al iniciar.

```
gestion-finanzas/
├── app.py            Aplicación y rutas
├── database.py       Base de datos y copias de seguridad
├── utilidades.py     Importes, fechas y períodos
├── templates/        Páginas HTML
├── static/           Estilos, JavaScript e icono
├── tests/            Pruebas automáticas
├── datos/            Base de datos y copias (se crea al iniciar)
├── iniciar.bat       Inicio en Windows
└── iniciar.sh        Inicio en macOS / Linux
```

### Pruebas automáticas

```
.venv\Scripts\python -m pip install pytest
.venv\Scripts\python -m pytest
```
