import tello

import time

try:

    tello.Send("command")

    tello.Send("takeoff")

    time.sleep(5)

    tello.Send("up 30")

    time.sleep(5)

    tello.Send("land")
   
except KeyboardInterrupt:

    tello.Emergency()
