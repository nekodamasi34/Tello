import tello

import time

import cv2

import threading

LOCAL_IP = '192.168.10.1'

LOCAL_PORT_VIDEO = '11111'

addr = 'udp://' + LOCAL_IP + ':' + str(LOCAL_PORT_VIDEO)



red_low_point = (0, 120, 100)

red_high_point = (10, 255, 255)

blue_low_point = (100, 150, 80)

blue_high_point = (120, 255, 255)

timer_constant = 3.0

red_per_max = 0

blue_per_max = 0

timer = None

timer_flag = True

start_flag = False

finish = False

level_flag = False



def InterruptTimer():
    
    global timer
    
    global timer_flag
    
    global start_flag
    
    timer_flag = True
    
    start_flag = False
    
    timer = threading.Timer(timer_constant, InterruptTimer)
    
    timer.cancel()
    
try:
    
    tello.Send("command")
    
    tello.Send("streamon")
    
    tello.Send("takeoff")
    
    cap = cv2.VideoCapture(addr)
    
    while (cap.isOpened() and finish == False):
        
        ret, frame = cap.read()
        
        if ret == True:
            
            #フレームの大きさ取得
            
            height = frame.shape[0]
            
            width = frame.shape[1]
            
            #赤マスク処理
            
            red_image_mask = cv2.inRange(frame, red_low_point, red_high_point)
            
            red_white_pixels = cv2.countNonZero(red_image_mask)
            
            red_black_pixels = red_image_mask.size - red_white_pixels
            
            red_per = round(red_white_pixels / (red_white_pixels + red_black_pixels) * 100, 2)
            
            #青マスク処理

            blue_image_mask = cv2.inRange(frame, blue_low_point, blue_high_point)
            
            blue_white_pixels = cv2.countNonZero(blue_image_mask)
            
            blue_black_pixels = blue_image_mask.size - blue_white_pixels
            
            blue_per = round(blue_white_pixels / (blue_white_pixels + blue_black_pixels) * 100, 2)
            
            #タイマー管理
            
            if timer_flag == True:
                
                if start_flag == False:
                    
                    timer = threading.Timer(timer_constant, InterruptTimer)
                    
                    timer.start()
                    
                    start_flag = True
                    
                timer_flag = False
                
                #赤参照
                
                if level_flag == False:
                    
                    if red_per < red_per_max:
                        
                        tello.Send("forward 20")
                        
                    else:
                        
                        tello.Send("ccw 90")
                        
                        level_flag = True
                        
                #青参照
                        
                else:
                    
                    if blue_per < blue_per_max:
                        
                        tello.Send("forward 20")
                        
                    else:
                        
                        tello.Send("cw 90")
                        
                        finish = True
                        
    time.sleep(5)
    
    tello.Send("forward 50")
    
    time.sleep(5)
    
    tello.Send("land")
    
    cap.release()
    
    cv2.destroyAllWindows()
    
except KeyboardInterrupt:
    
    tello.Emergency()
