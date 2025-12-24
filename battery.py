from djitellopy import Tello

tello = Tello()


# 接続
tello.connect()
print("Battery:", tello.get_battery())

tello.end()