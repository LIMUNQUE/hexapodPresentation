#!/usr/bin/python3
#coding=utf8
# Robot con evitación de obstáculos controlado por servidor remoto
import os
import sys
import time
import threading
import numpy as np
import pandas as pd
from common import yaml_handle
from common import kinematics
from sensor.ultrasonic_sensor import Ultrasonic
from robot_client import RobotClient

if sys.version_info.major == 2:
    print('Please run this program with python3!')
    sys.exit(0)

board = None
servo_data = None

def load_config():
    global lab_data, servo_data
    
    lab_data = yaml_handle.get_yaml_data(yaml_handle.lab_file_path)
    servo_data = yaml_handle.get_yaml_data(yaml_handle.servo_file_path)

load_config()

servo2_pulse = servo_data['servo2']
Threshold = 40.0 # Umbral de detección de obstáculos en cm

# Variables de control
__isRunning = False
__serverEnabled = False  # Control desde servidor
__isAvoiding = False     # Flag para indicar si está evitando obstáculo
distance = 0

def reset():
    board.pwm_servo_set_position(0.5, [[1, 1800] , [2, servo_data['servo2']]])

def init():
    reset()
    print('🤖 Robot Avoidance Init')

def exit():
    global __isRunning
    
    ultrasonic.setRGBMode(0)
    ultrasonic.setRGB(1, (0, 0, 0))
    ultrasonic.setRGB(2, (0, 0, 0))
    __isRunning = False
    print('🤖 Robot Avoidance Exit')

def setThreshold(args):
    global Threshold
    Threshold = args[0]
    return (True, (Threshold,))

def getThreshold(args):
    global Threshold
    return (True, (Threshold,))

def start_robot():
    """Inicia el movimiento del robot (llamado por el cliente)"""
    global __isRunning, __serverEnabled
    __serverEnabled = True
    __isRunning = True
    print('🟢 Robot movimiento HABILITADO por servidor')

def stop_robot():
    """Detiene el movimiento del robot de forma controlada"""
    global __serverEnabled
    __serverEnabled = False
    print('🔴 Robot movimiento DESHABILITADO por servidor')
    # No detenemos __isRunning inmediatamente para permitir que termine maniobras

def server_disconnected():
    """Maneja desconexión del servidor"""
    global __serverEnabled
    __serverEnabled = False
    print('⚠️ Servidor desconectado - Robot en modo seguro')

def controlled_stop():
    """Detiene el robot de forma controlada"""
    global __isRunning
    __isRunning = False
    ik.stand(ik.initial_pos)
    print('🛑 Robot detenido completamente')

def move():
    """Hilo principal de movimiento con control del servidor"""
    global __isRunning, __serverEnabled, __isAvoiding
    
    while True:
        try:
            # Solo se mueve si el servidor lo permite Y el sistema está activo
            if __isRunning and __serverEnabled:
                if 0 < distance < Threshold:
                    __isAvoiding = True
                    print(f"⚠️ Obstáculo detectado a {distance:.1f}cm - Iniciando maniobra de evasión")
                    
                    # Retroceder mientras esté muy cerca
                    while distance < 25 and __isRunning:
                        if not __serverEnabled:  # Verificar durante retroceso
                            break
                        ik.back(ik.initial_pos, 2, 80, 50, 1)
                        time.sleep(0.1)
                    
                    # Realizar giro completo (6 pasos de 15° = 90°)
                    for i in range(6):
                        if not __isRunning or not __serverEnabled:
                            break
                        ik.turn_left(ik.initial_pos, 2, 50, 50, 1)
                        print(f"🔄 Girando {(i+1)*15}°...")
                        time.sleep(0.1)
                    
                    __isAvoiding = False
                    print("✅ Maniobra de evasión completada")
                    
                else: 
                    # Avanzar normalmente
                    if not __isAvoiding:  # Solo avanzar si no está evitando
                        ik.go_forward(ik.initial_pos, 2, 80, 50, 1)
                        
            else:
                # Si el servidor deshabilitó el movimiento y no está evitando, detener
                if not __serverEnabled and not __isAvoiding and __isRunning:
                    controlled_stop()
                
                time.sleep(0.01)
                
        except Exception as e:
            print(f"❌ Error en movimiento: {e}")
            time.sleep(0.1)

# Iniciar hilo de movimiento
movement_thread = threading.Thread(target=move, daemon=True)
movement_thread.start()

distance_data = []

def run():
    """Procesa datos del sensor ultrasónico"""
    global __isRunning, __serverEnabled, distance, distance_data

    if __isRunning:
        # Procesamiento de datos del sensor ultrasónico con filtrado estadístico
        distance_ = ultrasonic.getDistance() / 10.0
        distance_data.append(distance_)
        
        if len(distance_data) > 1:
            data = pd.DataFrame(distance_data)
            data_ = data.copy()
            u = data_.mean()  # Media
            std = data_.std()  # Desviación estándar

            # Filtrar valores atípicos (fuera de 1 desviación estándar)
            data_c = data[np.abs(data - u) <= std] if std[0] > 0 else data
            distance = data_c.mean()[0] if len(data_c) > 0 else distance_
        else:
            distance = distance_
            
        # Mantener ventana deslizante de 5 mediciones
        if len(distance_data) >= 5:
            distance_data.pop(0)

def main():
    global board, ik, ultrasonic, client
    
    print("🤖 Iniciando Robot con Evitación de Obstáculos Controlado por Servidor")
    
    # Inicializar hardware del robot
    from common.ros_robot_controller_sdk import Board
    board = Board()
    ik = kinematics.IK(board)
    ultrasonic = Ultrasonic()
    
    # Inicializar cliente del servidor
    client = RobotClient(server_ip="192.168.18.13", server_port=5000, interval=0.8)
    
    # Registrar callbacks
    client.set_callbacks(
        on_start=start_robot,
        on_stop=stop_robot,
        on_server_disconnect=server_disconnected
    )
    
    # Inicializar robot
    init()
    
    # Iniciar cliente
    client.start()
    
    print("✅ Sistema inicializado. Presiona CTRL+C para salir")
    
    try:
        while True:
            run()
            time.sleep(0.05)
                
    except KeyboardInterrupt:
        print("\n🛑 Deteniendo robot por interrupción del usuario")
    
    finally:
        # Limpieza
        print("🧹 Cerrando sistema...")
        client.stop()
        exit()
        print("✅ Sistema cerrado correctamente")

if __name__ == '__main__':
    main()
