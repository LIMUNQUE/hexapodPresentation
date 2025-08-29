# robot_cliente.py
import requests
import time
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RobotClient:
    def __init__(self, server_ip="192.168.18.7", server_port=5000, interval=2):
        # Cambia server_ip por la IP de la PC que ejecuta deteccion_server.py
        self.estado_url = f"http://{server_ip}:{server_port}/estado"
        self.interval = interval
        self.personas_presentes = None  # desconocido inicialmente

    def consultar_estado(self):
        try:
            resp = requests.get(self.estado_url, timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                personas = bool(data.get("personas_presentes", False))
                ts = data.get("timestamp", time.time())
                return personas, ts
            else:
                logger.warning(f"Respuesta inesperada del servidor: {resp.status_code}")
                return None, None
        except Exception as e:
            logger.error(f"Error consultando servidor: {e}")
            return None, None

    def procesar_estado(self, personas_detectadas, timestamp):
        """
        Imprime solo cuando hay un cambio de estado.
        """
        if personas_detectadas is None:
            # no pudimos consultar, no cambiamos estado
            return

        # Si es la primera vez que consultamos, mostramos estado inicial
        if self.personas_presentes is None:
            self.personas_presentes = personas_detectadas
            fecha_hora = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
            estado_txt = "PERSONAS DETECTADAS" if personas_detectadas else "NO HAY PERSONAS"
            print(f"ℹ️ [{fecha_hora}] Estado inicial: {estado_txt}")
            return

        if personas_detectadas != self.personas_presentes:
            fecha_hora = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
            if personas_detectadas:
                print(f"🟢 [{fecha_hora}] SEGUIR PRESENTACIÓN (PERSONAS DETECTADAS)")
            else:
                print(f"🔴 [{fecha_hora}] DETENER ROBOT (YA NO HAY PERSONAS)")
            self.personas_presentes = personas_detectadas

    def run(self):
        print("🤖 Robot cliente: consultando servidor periódicamente...")
        try:
            while True:
                personas, ts = self.consultar_estado()
                self.procesar_estado(personas, ts if ts is not None else time.time())
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\n🛑 Robot detenido por el usuario")

def main():
    # Cambia server_ip por la IP de la PC que ejecuta deteccion_server.py
    client = RobotClient(server_ip="192.168.18.13", server_port=5000, interval=0.8)
    client.run()

if __name__ == "__main__":
    main()