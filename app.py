"""
Aplicación de recordatorios de agua y descanso
Desarrollado para Coolify con prefix /facu-demo
"""
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
import logging

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Inicializar Flask
app = Flask(__name__)
CORS(app)

# Configurar el prefix para Coolify
script_name = os.getenv('SCRIPT_NAME', 'facu-demo').strip()
if not script_name.startswith('/'):
    script_name = f"/{script_name}"
script_name = script_name.rstrip('/') or '/facu-demo'
app.config['APPLICATION_ROOT'] = script_name

# Estado de recordatorios
reminders = {
    'water': {
        'count': 0,
        'last_reminder': None,
        'interval': int(os.getenv('WATER_REMINDER_INTERVAL', 30))
    },
    'break': {
        'count': 0,
        'last_reminder': None,
        'interval': int(os.getenv('BREAK_REMINDER_INTERVAL', 60))
    }
}

# Scheduler para recordatorios automáticos
scheduler = BackgroundScheduler()


def trigger_water_reminder():
    """Desencadena recordatorio de agua"""
    reminders['water']['count'] += 1
    reminders['water']['last_reminder'] = datetime.now().isoformat()
    logger.info(f"💧 ¡Recordatorio #{reminders['water']['count']}: Bebe agua!")


def trigger_break_reminder():
    """Desencadena recordatorio de descanso"""
    reminders['break']['count'] += 1
    reminders['break']['last_reminder'] = datetime.now().isoformat()
    logger.info(f"🚶 ¡Recordatorio #{reminders['break']['count']}: ¡Párate y descansa!")


# ==================== RUTAS ====================

@app.route('/')
@app.route(f'{script_name}/')
def index():
    """Página principal"""
    return render_template('index.html', prefix=script_name)


@app.route('/health')
@app.route(f'{script_name}/health')
def health():
    """Endpoint de salud para Coolify"""
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()}), 200


@app.route('/api/reminders', methods=['GET'])
@app.route(f'{script_name}/api/reminders', methods=['GET'])
def get_reminders():
    """Obtiene el estado actual de los recordatorios"""
    return jsonify({
        'water': reminders['water'],
        'break': reminders['break'],
        'timestamp': datetime.now().isoformat()
    }), 200


@app.route('/api/reminders/water', methods=['POST'])
@app.route(f'{script_name}/api/reminders/water', methods=['POST'])
def trigger_water():
    """Dispara manualmente un recordatorio de agua"""
    trigger_water_reminder()
    return jsonify({
        'status': 'success',
        'message': '¡Recordatorio de agua enviado!',
        'reminder': reminders['water']
    }), 200


@app.route('/api/reminders/break', methods=['POST'])
@app.route(f'{script_name}/api/reminders/break', methods=['POST'])
def trigger_break():
    """Dispara manualmente un recordatorio de descanso"""
    trigger_break_reminder()
    return jsonify({
        'status': 'success',
        'message': '¡Recordatorio de descanso enviado!',
        'reminder': reminders['break']
    }), 200


@app.route('/api/config', methods=['GET'])
@app.route(f'{script_name}/api/config', methods=['GET'])
def get_config():
    """Obtiene la configuración de la aplicación"""
    return jsonify({
        'water_interval': reminders['water']['interval'],
        'break_interval': reminders['break']['interval'],
        'prefix': script_name
    }), 200


@app.route('/api/config/intervals', methods=['PUT'])
@app.route(f'{script_name}/api/config/intervals', methods=['PUT'])
def update_intervals():
    """Actualiza los intervalos de recordatorios"""
    try:
        data = request.get_json()
        
        if 'water_interval' in data:
            reminders['water']['interval'] = int(data['water_interval'])
            # Actualizar scheduler
            if scheduler.get_job('water_reminder'):
                scheduler.reschedule_job('water_reminder', trigger='interval', 
                                       minutes=reminders['water']['interval'])
        
        if 'break_interval' in data:
            reminders['break']['interval'] = int(data['break_interval'])
            # Actualizar scheduler
            if scheduler.get_job('break_reminder'):
                scheduler.reschedule_job('break_reminder', trigger='interval',
                                       minutes=reminders['break']['interval'])
        
        return jsonify({
            'status': 'success',
            'water_interval': reminders['water']['interval'],
            'break_interval': reminders['break']['interval']
        }), 200
    except Exception as e:
        logger.error(f"Error al actualizar intervalos: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 400


@app.route('/api/reminders/reset', methods=['POST'])
@app.route(f'{script_name}/api/reminders/reset', methods=['POST'])
def reset_reminders():
    """Reinicia los contadores de recordatorios"""
    reminders['water']['count'] = 0
    reminders['break']['count'] = 0
    reminders['water']['last_reminder'] = None
    reminders['break']['last_reminder'] = None
    
    return jsonify({
        'status': 'success',
        'message': 'Contadores reiniciados',
        'reminders': reminders
    }), 200


# ==================== INICIALIZACIÓN ====================

def init_scheduler():
    """Inicializa el scheduler de recordatorios"""
    scheduler.add_job(
        trigger_water_reminder,
        'interval',
        minutes=reminders['water']['interval'],
        id='water_reminder',
        name='Water Reminder'
    )
    scheduler.add_job(
        trigger_break_reminder,
        'interval',
        minutes=reminders['break']['interval'],
        id='break_reminder',
        name='Break Reminder'
    )
    scheduler.start()
    logger.info("Scheduler iniciado ✅")


if __name__ == '__main__':
    # Asegurarse de que el directorio de templates existe
    os.makedirs('templates', exist_ok=True)
    os.makedirs('static', exist_ok=True)
    
    # Iniciar scheduler
    init_scheduler()
    
    # Obtener configuración
    host = os.getenv('FLASK_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_PORT', 3000))
    debug = os.getenv('FLASK_ENV', 'production') == 'development'
    
    logger.info(f"🚀 Iniciando aplicación en {host}:{port}")
    logger.info(f"📍 Prefix: {script_name}")
    
    app.run(host=host, port=port, debug=debug)
