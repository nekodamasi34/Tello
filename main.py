from djitellopy import Tello
import time

tello = Tello()


try:
    # 接続
    tello.connect()
    print("Battery:", tello.get_battery())

    # 離陸
    tello.takeoff()

    time.sleep(3)

    # 前進10cm
    print("move forward: 10cm")
    tello.move_forward(10)

    # 3秒停止
    print("wait 3s")
    time.sleep(3)

    #後進10cm
    print("move backward: 10cm")
    tello.move_back(10)


    # 3秒停止
    print("wait 3s")
    time.sleep(3)

    # 着陸
    print("landing")
    tello.land()

finally:
    # 例外時でも安全に着陸＆終了
    try:
        tello.land()
        tello.emergency()
    except Exception:
        pass
    # 映像使ってたら: tello.streamoff()
    tello.end()