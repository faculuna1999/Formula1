# 💪 Facu Demo - Recordatorios de Salud

Una aplicación web simple para recordarte que bebas agua y te pares a descansar durante tu jornada de trabajo.

## 🎯 Características

- ✅ Recordatorios automáticos de agua cada 30 minutos (configurable)
- ✅ Recordatorios automáticos de descanso cada 60 minutos (configurable)
- ✅ Interfaz web moderna y responsiva
- ✅ Disparo manual de recordatorios
- ✅ Contador de recordatorios
- ✅ Configuración de intervalos en tiempo real
- ✅ Desplegable en Coolify con prefix `/facu-demo`
- ✅ Docker listo para producción

## 🚀 Inicio Rápido

### Usar Docker Compose

```bash
# Clonar el repositorio
git clone <repository-url>
cd facu-demo

# Construir y ejecutar con Docker Compose
docker-compose up --build
```

La aplicación estará disponible en: `http://localhost:5000`

### Desarrollo Local

```bash
# Crear entorno virtual
python3 -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Crear archivo .env (opcional)
cp .env.example .env

# Ejecutar la aplicación
python app.py
```

La aplicación estará disponible en: `http://localhost:5000`

## 🐳 Despliegue en Coolify

### Configuración del Proyecto

1. **Crear nuevo proyecto en Coolify**
   - Conectar el repositorio de GitHub
   - Seleccionar la rama principal

2. **Configurar la aplicación Docker**
   - **Puerto:** 5000
   - **Health Check:** `/health`
   - **Script Name:** `/facu-demo` (se configura automáticamente en el Dockerfile)

3. **Variables de Entorno**
   ```
   FLASK_ENV=production
   FLASK_HOST=0.0.0.0
   FLASK_PORT=5000
   WATER_REMINDER_INTERVAL=30
   BREAK_REMINDER_INTERVAL=60
   SCRIPT_NAME=/facu-demo
   ```

4. **URL de acceso**
   - La aplicación será accesible en: `tu-dominio.com/facu-demo`

## 📋 API Endpoints

### GET `/facu-demo/` 
Página principal de la aplicación

### GET `/facu-demo/health`
Verificar salud de la aplicación

### GET `/facu-demo/api/reminders`
Obtener estado actual de recordatorios
```json
{
  "water": {
    "count": 5,
    "last_reminder": "2024-04-15T14:30:00",
    "interval": 30
  },
  "break": {
    "count": 2,
    "last_reminder": "2024-04-15T14:00:00",
    "interval": 60
  }
}
```

### POST `/facu-demo/api/reminders/water`
Disparar recordatorio de agua manualmente

### POST `/facu-demo/api/reminders/break`
Disparar recordatorio de descanso manualmente

### GET `/facu-demo/api/config`
Obtener configuración actual

### PUT `/facu-demo/api/config/intervals`
Actualizar intervalos de recordatorios
```json
{
  "water_interval": 25,
  "break_interval": 45
}
```

### POST `/facu-demo/api/reminders/reset`
Reiniciar contadores de recordatorios

## ⚙️ Configuración

Las variables de entorno disponibles son:

| Variable | Descripción | Default |
|----------|-------------|---------|
| `FLASK_ENV` | Ambiente (production/development) | production |
| `FLASK_HOST` | Host de la aplicación | 0.0.0.0 |
| `FLASK_PORT` | Puerto de la aplicación | 5000 |
| `WATER_REMINDER_INTERVAL` | Intervalo recordatorios agua (minutos) | 30 |
| `BREAK_REMINDER_INTERVAL` | Intervalo recordatorios descanso (minutos) | 60 |
| `SCRIPT_NAME` | Prefix para Coolify | /facu-demo |

## 📁 Estructura del Proyecto

```
facu-demo/
├── app.py                 # Aplicación principal Flask
├── requirements.txt       # Dependencias Python
├── Dockerfile            # Configuración Docker
├── docker-compose.yml    # Compose para desarrollo
├── .env.example         # Ejemplo de variables de entorno
├── .gitignore           # Archivos ignorados por Git
├── README.md            # Este archivo
└── templates/
    └── index.html       # Interfaz web
```

## 🔧 Tecnologías Utilizadas

- **Python 3.11** - Lenguaje de programación
- **Flask** - Framework web
- **APScheduler** - Planificador de tareas
- **Flask-CORS** - Manejo de CORS
- **Docker** - Containerización

## 📝 Notas de Desarrollo

### Agregar nuevas dependencias
```bash
pip install nueva-dependencia
pip freeze > requirements.txt
```

### Construir imagen Docker
```bash
docker build -t facu-demo:latest .
```

### Ejecutar contenedor
```bash
docker run -p 5000:5000 \
  -e WATER_REMINDER_INTERVAL=30 \
  -e BREAK_REMINDER_INTERVAL=60 \
  facu-demo:latest
```

## 🐛 Troubleshooting

### La aplicación no se conecta en `/facu-demo`
- Verificar que `SCRIPT_NAME=/facu-demo` esté configurado
- En desarrollo, acceder a `http://localhost:5000/`

### Los recordatorios no se disparan
- Verificar que el scheduler esté iniciado
- Revisar los logs: `docker logs facu-demo-app`

### Puerto 5000 ya está en uso
```bash
# Cambiar el puerto en docker-compose.yml o:
docker run -p 5001:5000 facu-demo:latest
```

## 👨‍💻 Desarrollador

Facundo Luna - Desarrollador Junior

## 📄 Licencia

MIT License - Libre para usar y modificar

## 🤝 Contribuciones

Las contribuciones son bienvenidas. Por favor:
1. Fork el proyecto
2. Crea una rama para tu feature (`git checkout -b feature/AmazingFeature`)
3. Commit tus cambios (`git commit -m 'Add some AmazingFeature'`)
4. Push a la rama (`git push origin feature/AmazingFeature`)
5. Abre un Pull Request

## 📞 Soporte

Para reportar bugs o sugerencias, abre un issue en el repositorio.
