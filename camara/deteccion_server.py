# deteccion_server.py
import cv2
import time
import requests
import logging
from threading import Thread, Lock
from datetime import datetime
from flask import Flask, request, jsonify
from ultralytics import YOLO

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------ Servidor Flask ------------------
class DetectionServer:
    def __init__(self, host='0.0.0.0', port=5000):
        self.app = Flask(__name__)
        self.host = host
        self.port = port

        # Estado compartido
        self.personas_presentes = False
        self.timestamp = time.time()
        self.lock = Lock()

        self._setup_routes()

    def _setup_routes(self):
        @self.app.route('/persona_detectada', methods=['POST'])
        def recibir_deteccion():
            try:
                data = request.get_json()
                if not data or 'personas_detectadas' not in data:
                    return jsonify({"error": "Datos inválidos"}), 400

                personas = bool(data['personas_detectadas'])
                ts = data.get('timestamp', time.time())
                self.procesar_mensaje(personas, ts)
                return jsonify({"status": "success"}), 200
            except Exception as e:
                logger.error(f"Error procesando request: {e}")
                return jsonify({"error": "Error interno"}), 500

        @self.app.route('/estado', methods=['GET'])
        def estado():
            with self.lock:
                return jsonify({
                    "personas_presentes": self.personas_presentes,
                    "timestamp": self.timestamp
                }), 200

    def procesar_mensaje(self, personas_detectadas, timestamp):
        """
        Actualiza el estado solo si hay cambio (y lo imprime).
        """
        with self.lock:
            if personas_detectadas != self.personas_presentes:
                fecha_hora = datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')
                if personas_detectadas:
                    print(f"🟢 [{fecha_hora}] PERSONAS DETECTADAS")
                else:
                    print(f"🔴 [{fecha_hora}] YA NO HAY PERSONAS")
                self.personas_presentes = personas_detectadas
                self.timestamp = timestamp

    def run(self):
        # Ejecuta Flask en hilo (threaded)
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False, threaded=True)


# ------------------ Detector de personas (inferencia cada 1s, debounce 10s) ------------------
class PersonDetector:
    def __init__(self, server_ip="127.0.0.1", server_port=5000, cam_index=0,
                 inference_interval=1.0, no_persons_grace=10.0):
        self.server_url = f"http://{server_ip}:{server_port}/persona_detectada"
        logger.info("Cargando modelo YOLO...")
        self.model = YOLO("yolov8n.pt")  # ajusta ruta si necesario

        logger.info("Configurando cámara...")
        self.cap = cv2.VideoCapture(cam_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        self.cap.set(cv2.CAP_PROP_FPS, 10)

        if not self.cap.isOpened():
            raise Exception("No se pudo abrir la cámara")

        cv2.namedWindow("Detección de Personas - YOLO", cv2.WINDOW_NORMAL)

        # Lógica de tiempos/estados
        self.inference_interval = inference_interval   # 1s
        self.no_persons_grace = no_persons_grace         # 10s
        self.last_inference_time = 0.0
        self.last_detection_time = 0.0   # última vez que se detectó persona
        self.state_sent = False          # último estado enviado al servidor
        self.current_frame = None
        logger.info("Detector inicializado")

    def detectar_personas_frame(self, frame):
        """Ejecuta YOLO sobre el frame y devuelve True si hay persona con confianza>0.5"""
        results = self.model(frame, verbose=False)
        persona_detectada = False

        for result in results:
            if result.boxes is not None:
                for box in result.boxes:
                    if int(box.cls) == 0:  # clase persona
                        confidence = float(box.conf)
                        if confidence > 0.5:
                            persona_detectada = True
                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(frame, f"Persona {confidence:.2f}",
                                        (x1, y1 - 10),
                                        cv2.FONT_HERSHEY_SIMPLEX,
                                        0.6, (0, 255, 0), 2)
        return persona_detectada, frame

    def notificar_servidor(self, personas_presentes):
        """Envía POST solo cuando cambia el estado (la llamada desde run asegura eso)."""
        try:
            payload = {"personas_detectadas": personas_presentes, "timestamp": time.time()}
            response = requests.post(self.server_url, json=payload, timeout=2)
            if response.status_code == 200:
                estado = "ACTIVAR" if personas_presentes else "DESACTIVAR"
                logger.info(f"✅ Notificación enviada: {estado}")
            else:
                logger.warning(f"⚠️ Respuesta inesperada del servidor: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Error al notificar servidor: {e}")

    def run(self):
        logger.info("🚀 Iniciando loop de detección (inferencia cada 1s, grace 10s)...")
        try:
            while True:
                now = time.monotonic()
                # Leer frame continuamente para mostrar vídeo fluido
                ret, frame = self.cap.read()
                if not ret:
                    logger.error("No se pudo leer frame de la cámara")
                    time.sleep(0.1)
                    continue
                self.current_frame = frame.copy()

                # Hacer inferencia solo cada inference_interval segundos
                if now - self.last_inference_time >= self.inference_interval:
                    self.last_inference_time = now
                    persona_detectada, frame_annotated = self.detectar_personas_frame(self.current_frame)
                    # Si detecta persona -> actualizar inmediatamente
                    if persona_detectada:
                        self.last_detection_time = now
                        # Si el último estado enviado era False, enviar True
                        if not self.state_sent:
                            self.notificar_servidor(True)
                            self.state_sent = True
                    else:
                        # No se detectó en esta inferencia; solo declarar "no hay personas"
                        # si han pasado no_persons_grace desde la última detección
                        if self.last_detection_time == 0 or (now - self.last_detection_time) >= self.no_persons_grace:
                            if self.state_sent:
                                # enviamos cambio a False (solo si antes estaba True)
                                self.notificar_servidor(False)
                                self.state_sent = False
                        # Si aún no han pasado los 10s, no hacemos nada (esperamos)
                    # Mostrar frame anotado
                    cv2.imshow("Detección de Personas - YOLO", frame_annotated)
                else:
                    # No es tiempo de inferencia: mostramos el frame sin anotaciones o con texto de espera
                    display = self.current_frame.copy()
                    cv2.putText(display, "Esperando siguiente inferencia...", (10, 30),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
                    cv2.imshow("Detección de Personas - YOLO", display)

                # Esc para salir
                if cv2.waitKey(1) & 0xFF == 27:
                    break

                # pequeño sleep para bajar carga de CPU en el loop
                time.sleep(0.01)

        finally:
            self.cleanup()

    def cleanup(self):
        if self.cap:
            self.cap.release()
        cv2.destroyAllWindows()
        logger.info("🧹 Recursos liberados")


# ------------------ Main ------------------
def main():
    try:
        # Iniciar servidor Flask en hilo
        server = DetectionServer(host='0.0.0.0', port=5000)
        server_thread = Thread(target=server.run, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        print("\n" + "="*50)
        print("📶 SERVIDOR de DETECCIÓN iniciado en: 0.0.0.0:5000")
        print("Endpoints: /persona_detectada (POST)  /estado (GET)")
        print("Inferencia cada 1s. 'No personas' se declara tras 10s sin detecciones.")
        print("="*50 + "\n")

        detector = PersonDetector(server_ip="127.0.0.1", server_port=5000,
                                  cam_index=0, inference_interval=1.0, no_persons_grace=10.0)
        detector.run()
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}")

if __name__ == "__main__":
    main()
