#!/usr/bin/python3
#coding=utf8
#第4章 AI视觉学习课程\第6课 自动避障(4.AI Vision Games Lesson\Lesson 6 Auto Obstacle Avoidance)
import os
import sys
import cv2
import time
import threading
import numpy as np
import pandas as pd
from common import yaml_handle
from common import kinematics
from calibration.camera import Camera 
from sensor.ultrasonic_sensor import Ultrasonic

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
Threshold = 40.0 # 默认阈值40cm(default threshold is 40cm)
TextColor = (0, 255, 255)
TextSize = 12

__isRunning = False
distance = 0

def reset():
    board.pwm_servo_set_position(0.5, [[1, 1800] , [2, servo_data['servo2']]])

 
def init():
    reset()
    print('Avoidance Init')

def exit():
    global __isRunning
    
    ultrasonic.setRGBMode(0)
    ultrasonic.setRGB(1, (0, 0, 0))
    ultrasonic.setRGB(2, (0, 0, 0))
    __isRunning = False
    print('Avoidance Exit')

def setThreshold(args):
    global Threshold
    Threshold = args[0]
    return (True, (Threshold,))

def getThreshold(args):
    global Threshold
    return (True, (Threshold,))

def start():
    global __isRunning
    __isRunning = True
    print('Avoidance Start')

def stop():
    global __isRunning
    __isRunning = False
    ik.stand(ik.initial_pos)
    print('Avoidance Stop')

def move():
    while True:
        if __isRunning:
            if 0 < distance < Threshold:
                while distance < 25: # 小于25cm时后退(back up when the distance is less than 25cm)
                    ik.back(ik.initial_pos, 2, 80, 50, 1)
                for i in range(6): # 左转6次，每次15度，一共90度(Turn left 6 times with 15 degrees each time, a total of 90 degree)
                    if __isRunning:
                        ik.turn_left(ik.initial_pos, 2, 50, 50, 1)
            else: 
                ik.go_forward(ik.initial_pos, 2, 80, 50, 1)
        else:
            time.sleep(0.01)

threading.Thread(target=move, daemon=True).start()

distance_data = []

def run(img):
    global __isRunning
    global Threshold
    global distance
    global distance_data

    if __isRunning:
        
        # 数据处理，过滤异常值(process data and filter abnormal values)
        distance_ = ultrasonic.getDistance() / 10.0
        distance_data.append(distance_)
        data = pd.DataFrame(distance_data)
        data_ = data.copy()
        u = data_.mean()  # 计算均值(calculate mean)
        std = data_.std()  # 计算标准差(calculate standard deviation)

        data_c = data[np.abs(data - u) <= std]
        distance = data_c.mean()[0]
        if len(distance_data) == 5:
            distance_data.remove(distance_data[0])

        cv2.putText(img, "Dist:%.1fcm" % distance, (30, 480 - 30), cv2.FONT_HERSHEY_SIMPLEX, 1.2, TextColor, 2)
    return img
if __name__ == '__main__':
    from common.ros_robot_controller_sdk import Board


    board = Board()
    ik = kinematics.IK(board)
    ultrasonic = Ultrasonic()

    init()
    start()
    camera = Camera()
    camera.camera_open(correction=True) # 开启畸变矫正,默认不开启(enable distortion correction which is not started by default)


    while True:
        img = camera.frame
        if img is not None:
            frame = img.copy()
            Frame = run(frame)           
            cv2.imshow('Frame', Frame)
            key = cv2.waitKey(1)
            if key == 27:
                break
        else:
            time.sleep(0.01)
    camera.camera_close()
    cv2.destroyAllWindows()
