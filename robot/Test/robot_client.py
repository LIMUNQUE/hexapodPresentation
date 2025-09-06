# robot_client.py
import requests
import time
import logging
import threading
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RobotClient:
    def __init__(self, server_ip="192.168.18.13", server_port=5000, interval=0.8):
        self.estado_url = f"http://{server_ip}:{server_port}/estado"
        self.interval = interval
        self.personas_presentes = None  # desconocido inicialmente
        self.server_connected = True
        self.running = False
        self._thread = None
        
        # Callbacks que el robot puede registrar
        self.on_start_callback = None
        self.on_stop_callback = None
        self.on_server_disconnect_callback = None

    def set_callbacks(self, on_start=None, on_stop=None, on_server_disconnect=None):
        """Registra callbacks para eventos del cliente"""
        self.on_start_callback = on_start
        self.on_stop_callback = on_stop
        self.on_server_disconnect_callback = on_server_disconnect

    def consultar_estado(self):
        try:
            resp = requests.get(self.estado_url, timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                personas = bool(data.get("personas_presentes", False))
                ts = data.get("timestamp", time.time())
                
                # Marcar servidor como conectado
                if not self.server_connected:
                    self.server_connected = True
                    logger.info("Reconectado al servidor")
                
                return personas, ts
            else:
                logger.warning(f"Respuesta inesperada del servidor: {resp.status_code}")
                return None, None
        except Exception as e:
            # Marcar servidor como desconectado
            if self.server_connected:
                self.server_connected = False
                logger.error(f"Servidor desconectado: {e}")
                if self.on_server_disconnect_callback:
                    self.on_server_disconnect_callback()
            return None, None

    def procesar_estado(self, personas_detectadas, timestamp):
        """
        Procesa cambios de estado y ejecuta callbacks correspondientes.
        """
        if personas_detectadas is None:
            # No pudimos consultar, no cambiamos estado
            return

        # Si es la primera vez que consultamos, mostramos estado inicial
        if self.personas_presentes is None:
            self.personas_presentes = personas_detectadas
            fecha_hora = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
            estado_txt = "PERSONAS DETECTADAS" if personas_detectadas else "NO HAY PERSONAS"
            print(f"ℹ️ [{fecha_hora}] Estado inicial: {estado_txt}")
            
            # Ejecutar callback inicial
            if personas_detectadas and self.on_start_callback:
                self.on_start_callback()
            elif not personas_detectadas and self.on_stop_callback:
                self.on_stop_callback()
            return

        # Detectar cambios de estado
        if personas_detectadas != self.personas_presentes:
            fecha_hora = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
            
            if personas_detectadas:
                print(f"🟢 [{fecha_hora}] SEGUIR PRESENTACIÓN (PERSONAS DETECTADAS)")
                if self.on_start_callback:
                    self.on_start_callback()
            else:
                print(f"🔴 [{fecha_hora}] DETENER ROBOT (YA NO HAY PERSONAS)")
                if self.on_stop_callback:
                    self.on_stop_callback()
            
            self.personas_presentes = personas_detectadas

    def start(self):
        """Inicia el cliente en un hilo separado"""
        if self.running:
            return
            
        self.running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        print("🤖 Robot cliente: consultando servidor periódicamente...")

    def stop(self):
        """Detiene el cliente"""
        self.running = False
        if self._thread:
            self._thread.join(timeout=2)
        print("\n🛑 Cliente detenido")

    def _run_loop(self):
        """Bucle principal del cliente (ejecutado en hilo separado)"""
        try:
            while self.running:
                personas, ts = self.consultar_estado()
                self.procesar_estado(personas, ts if ts is not None else time.time())
                time.sleep(self.interval)
        except Exception as e:
            logger.error(f"Error en bucle del cliente: {e}")

    def get_current_state(self):
        """Retorna el estado actual (True si hay personas, False si no, None si desconocido)"""
        if not self.server_connected:
            return None
        return self.personas_presentes

def main():
    """Modo standalone para pruebas"""
    client = RobotClient(server_ip="192.168.18.13", server_port=5000, interval=0.8)
    
    def on_start():
        print("-> Robot debería INICIAR movimiento")
    
    def on_stop():
        print("-> Robot debería DETENER movimiento")
    
    def on_disconnect():
        print("-> Servidor DESCONECTADO - Robot debería detenerse")
    
    client.set_callbacks(on_start=on_start, on_stop=on_stop, on_server_disconnect=on_disconnect)
    
    try:
        client.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        client.stop()

if __name__ == "__main__":
    main()