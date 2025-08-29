# deteccion_server_no_tracker.py
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
        self.app.run(host=self.host, port=self.port, debug=False, use_reloader=False, threaded=True)


# ------------------ Detector (sin tracker, inferencia en real-time) ------------------
class PersonDetector:
    def __init__(self,
                 server_ip="127.0.0.1", server_port=5000, cam_index=0,
                 no_persons_grace=10.0,      # 10s sin detecciones para declarar "no hay"
                 conf_threshold=0.5):
        self.server_url = f"http://{server_ip}:{server_port}/persona_detectada"

        logger.info("Cargando modelo YOLO...")
        self.model = YOLO("yolo11n.onnx")  # ajusta si usas otro checkpoint

        logger.info("Configurando cámara...")
        self.cap = cv2.VideoCapture(cam_index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        # no forzamos FPS — la inferencia será por frame
        if not self.cap.isOpened():
            raise Exception("No se pudo abrir la cámara")

        # Nombre de ventana único para evitar ventanas múltiples
        self.WINDOW_NAME = "Detección de Personas - YOLO (RealTime)"
        cv2.namedWindow(self.WINDOW_NAME, cv2.WINDOW_NORMAL)

        # Parámetros
        self.no_persons_grace = no_persons_grace
        self.conf_threshold = conf_threshold

        # Tiempos
        self.last_detection_time = 0.0     # última vez que YOLO vio una persona

        # Estado enviado al servidor
        self.server_state = False          # False: no hay personas; True: hay

        logger.info("Detector inicializado (sin tracker)")

    def _pick_any_person(self, result):
        """
        Recorre cajas y devuelve True si encuentra al menos una persona por encima del umbral.
        Además dibuja todas las cajas de persona sobre el frame.
        """
        found = False
        if result.boxes is None:
            return False

        for box in result.boxes:
            try:
                cls = int(box.cls)
            except Exception:
                # algunos formatos pueden diferir; ignorar si no tiene clase
                continue
            if cls == 0:  # clase persona (COCO)
                conf = float(box.conf)
                if conf >= self.conf_threshold:
                    found = True
        return found

    def _run_yolo_and_annotate(self, frame):
        """
        Ejecuta YOLO sobre el frame, dibuja cajas y devuelve (persona_detectada_bool, annotated_frame)
        """
        # Si tu versión de ultralytics soporta show=False, puedes añadirlo para evitar GUIs internas.
        results = self.model(frame, verbose=False)
        persona_detectada = False

        # Dibujar cajas: iteramos resultados y boxes
        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                try:
                    cls = int(box.cls)
                    conf = float(box.conf)
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                except Exception:
                    continue
                if cls == 0 and conf >= self.conf_threshold:
                    persona_detectada = True
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"Persona {conf:.2f}", (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        return persona_detectada, frame

    def _notificar_servidor(self, personas_presentes):
        try:
            payload = {"personas_detectadas": personas_presentes, "timestamp": time.time()}
            resp = requests.post(self.server_url, json=payload, timeout=2)
            if resp.status_code == 200:
                estado = "ACTIVAR" if personas_presentes else "DESACTIVAR"
                logger.info(f"✅ Notificación enviada: {estado}")
            else:
                logger.warning(f"⚠️ Respuesta inesperada del servidor: {resp.status_code}")
        except Exception as e:
            logger.error(f"❌ Error al notificar servidor: {e}")

    def run(self):
        logger.info("🚀 Loop de detección en tiempo real iniciado (sin tracker)")
        try:
            while True:
                now = time.monotonic()
                ret, frame = self.cap.read()
                if not ret:
                    logger.error("No se pudo leer frame de la cámara")
                    time.sleep(0.05)
                    continue

                # Si el usuario cerró la ventana con el gestor de ventanas, salir limpiamente
                if cv2.getWindowProperty(self.WINDOW_NAME, cv2.WND_PROP_VISIBLE) < 1:
                    logger.info("Ventana cerrada por el usuario. Saliendo...")
                    break

                # Ejecutar YOLO en cada frame (real-time)
                persona_detectada, annotated = self._run_yolo_and_annotate(frame)

                if persona_detectada:
                    # refrescar última detección
                    self.last_detection_time = now

                    # si antes el servidor estaba en False -> notificar True inmediatamente
                    if not self.server_state:
                        self._notificar_servidor(True)
                        self.server_state = True
                else:
                    # sin detección en este frame: comprobamos si han pasado N segundos desde la última detección
                    # si server_state == True y han pasado no_persons_grace => notificar Ausencia
                    time_since_last = now - self.last_detection_time if self.last_detection_time > 0 else float('inf')
                    if self.server_state and time_since_last >= self.no_persons_grace:
                        self._notificar_servidor(False)
                        self.server_state = False

                # Overlay informativo
                last_elapsed = (now - self.last_detection_time) if self.last_detection_time > 0 else float('inf')
                info1 = f"Evidencia hace: {0 if last_elapsed == float('inf') else last_elapsed:.1f}s"
                info2 = f"Estado: {'PRESENTE' if self.server_state else 'AUSENTE'}"
                cv2.putText(annotated, info1, (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (220, 220, 220), 2)
                cv2.putText(annotated, info2, (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 180, 255), 2)

                cv2.imshow(self.WINDOW_NAME, annotated)

                # ESC para salir
                if cv2.waitKey(1) & 0xFF == 27:
                    break

                # pequeño respiro para la CPU (si tu hardware puede procesar más rápido, reducir o quitar)
                time.sleep(0.001)
        finally:
            self.cleanup()

    def cleanup(self):
        if self.cap:
            self.cap.release()
        try:
            cv2.destroyWindow(self.WINDOW_NAME)
        except Exception:
            pass
        cv2.destroyAllWindows()
        logger.info("🧹 Recursos liberados")


# ------------------ Main ------------------
def main():
    try:
        # Servidor Flask en hilo
        server = DetectionServer(host='0.0.0.0', port=5000)
        server_thread = Thread(target=server.run, daemon=True)
        server_thread.start()
        time.sleep(0.5)

        print("\n" + "="*50)
        print("📶 SERVIDOR de DETECCIÓN iniciado en: 0.0.0.0:5000")
        print("Endpoints: /persona_detectada (POST)  /estado (GET)")
        print(f"Reglas: inferencia en tiempo real, 'No personas' tras {10.0}s sin detecciones")
        print("="*50 + "\n")

        detector = PersonDetector(
            server_ip="127.0.0.1", server_port=5000,
            cam_index=0,
            no_persons_grace=10.0,
            conf_threshold=0.5
        )
        detector.run()
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}")

if __name__ == "__main__":
    main()
