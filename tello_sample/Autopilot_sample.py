import tello
import time
import cv2
import threading
from datetime import datetime

LOCAL_IP = '192.168.10.1'

LOCAL_PORT_VIDEO = '11111'

addr = 'udp://' + LOCAL_IP + ':' + str(LOCAL_PORT_VIDEO)

# ===== デバッグ出力設定 =====
VERBOSE_DECISION_ONLY = False  # True: 意思決定時のみprint、False: 毎フレームもprint（大量）
SHOW_MASKS = False             # Trueにするとマスク表示（開発中向け）

# 赤だけは色相(Hue)が0°付近と180°付近の両端にまたがってる
# red_low_point = (0, 0, 0)
#
# red_high_point = (0, 0, 0)
#
# blue_low_point = (0, 0, 0)
#
# blue_high_point = (0, 0, 0)

# # 赤は2レンジ
red_low_point  = (0,   120, 100)   # 赤レンジ1(下限)
red_high_point = (10,  255, 255)   # 赤レンジ1(上限)
red2_low_point  = (160, 120, 100)  # 赤レンジ2(下限)
red2_high_point = (179, 255, 255)  # 赤レンジ2(上限)

# # 青
blue_low_point  = (100, 150,  80)  # 青(下限)
blue_high_point = (130, 255, 255)  # 青(上限)

timer_constant = 3.0
red_per_max = 5.0
blue_per_max = 5.0

timer = None
timer_flag = True
start_flag = False
finish = False
level_flag = False

# ===== ヘルパ：タイムスタンプ付きprint =====
def log(*args):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]", *args)

def InterruptTimer():
    
    # global timer
    
    global timer_flag
    global start_flag
    
    timer_flag = True
    start_flag = False
    
    # timer = threading.Timer(timer_constant, InterruptTimer)
    # timer.cancel()

    log("InterruptTimer(): timer_flag=True, start_flag=False（次の意思決定OK）")
    
try:
    log("=== Tello 初期化 ===")

    log("Send: command")
    tello.Send("command")

    # # ▼ バッテリー問い合わせ → 表示
    # tello.Send("battery?")
    # resp = tello.Tello.getInstance().response  # bytes が入ってる
    # try:
    #     batt_str = resp.decode("utf-8").strip()
    #     print(f"[INFO] Battery: {batt_str}%")
    # except Exception as e:
    #     print(f"[WARN] Battery decode failed: {e}, raw={resp}")

    log("Send: streamon")
    tello.Send("streamon")

    log("Send: takeoff")
    tello.Send("takeoff")

    time.sleep(2.0)  # IMU安定待ち
    log("離陸後ウェイト完了")
    
    cap = cv2.VideoCapture(addr)

    if not cap.isOpened():
        log("VideoCaptureオープン失敗？再トライ")
        time.sleep(0.8)
        cap.open(addr)

    # FPS計測用
    last_ts = time.time()
    frame_cnt = 0

    log("=== ループ開始 ===")
    while (cap.isOpened() and finish == False):
        
        ret, frame = cap.read()
        
        if ret == True:

            frame_cnt += 1
            now = time.time()
            if now - last_ts >= 1.0:
                log(f"FPS: {frame_cnt:.0f} /s")
                frame_cnt = 0
                last_ts = now
            
            #フレームの大きさ取得
            
            height = frame.shape[0]
            
            width = frame.shape[1]

            frame_small = cv2.resize(frame, (320, 240))
            
            # ★BGR→HSVに変換（ここが重要）
            hsv = cv2.cvtColor(frame_small, cv2.COLOR_BGR2HSV)

            #赤マスク処理
            # red_image_mask = cv2.inRange(frame, red_low_point, red_high_point)
            mask_red1 = cv2.inRange(hsv, red_low_point, red_high_point)
            mask_red2 = cv2.inRange(hsv, red2_low_point, red2_high_point)
            red_image_mask = mask_red1 | mask_red2
            
            red_white_pixels = cv2.countNonZero(red_image_mask)
            red_black_pixels = red_image_mask.size - red_white_pixels
            red_per = round(red_white_pixels / (red_white_pixels + red_black_pixels) * 100, 2)
            
            #青マスク処理
            # blue_image_mask = cv2.inRange(frame, blue_low_point, blue_high_point)
            blue_image_mask = cv2.inRange(hsv, blue_low_point, blue_high_point)

            blue_white_pixels = cv2.countNonZero(blue_image_mask)
            blue_black_pixels = blue_image_mask.size - blue_white_pixels
            blue_per = round(blue_white_pixels / (blue_white_pixels + blue_black_pixels) * 100, 2)

            if not VERBOSE_DECISION_ONLY:
                log(f"Frame {width}x{height} / small 320x240")
                log(f"HSV赤1: low{red_low_point} high{red_high_point}  赤2: low{red2_low_point} high{red2_high_point}")
                log(f"HSV青 : low{blue_low_point} high{blue_high_point}")
                log(f"赤mask: white={red_white_pixels} black={red_black_pixels} => {red_per}%  (閾値 {red_per_max}%)")
                log(f"青mask: white={blue_white_pixels} black={blue_black_pixels} => {blue_per}%  (閾値 {blue_per_max}%)")
                log(f"Flags => timer_flag={timer_flag}, start_flag={start_flag}, level_flag={'BLUE' if level_flag else 'RED'}, finish={finish}")

             # マスク表示（任意）
            if SHOW_MASKS:
                cv2.imshow("red_mask", red_image_mask)
                cv2.imshow("blue_mask", blue_image_mask)
                cv2.waitKey(1)

            #タイマー管理：3秒に1回だけ意思決定
            if timer_flag == True:
                if start_flag == False:
                    log(f"Timer開始: {timer_constant}s")
                    timer = threading.Timer(timer_constant, InterruptTimer)
                    timer.start()
                    start_flag = True
                timer_flag = False

                log("=== 意思決定 ===")
                log(f"現在のモード: {'青参照(LEVEL=BLUE)' if level_flag else '赤参照(LEVEL=RED)'}")
                log(f"red_per={red_per}% (閾値{red_per_max}%), blue_per={blue_per}% (閾値{blue_per_max}%)")

                #赤参照
                if level_flag == False:
                    if red_per < red_per_max:
                        log("Action: forward 20（赤未達）")
                        tello.Send("forward 20")
                        
                    else:
                        log("Action: ccw 90（赤達成→青モードへ）")
                        tello.Send("ccw 90")
                        level_flag = True
                        log(f"level_flag -> {level_flag}（True=青）")
                        
                #青参照
                else:
                    if blue_per < blue_per_max:
                        log("Action: forward 20（青未達）")
                        tello.Send("forward 20")
                        
                    else:
                        log("Action: cw 90（青達成→finish=True）")
                        tello.Send("cw 90")
                        finish = True
                        log(f"finish -> {finish}")

    log("=== 探索フェーズ終了 ===")
    time.sleep(5)
    log("Action: forward 50（終了前の演出）")
    tello.Send("forward 50")
    
    time.sleep(5)
    log("Action: land（着陸）")
    tello.Send("land")
    
    cap.release()
    cv2.destroyAllWindows()
    log("リソース開放完了")
    
except KeyboardInterrupt:
    log("KeyboardInterrupt検知 -> Emergency停止")
    tello.Emergency()

except Exception as e:
    # 念のためのフェイルセーフ
    log("例外発生:", repr(e))
    try:
        log("フェイルセーフ: land送出")
        tello.Send("land")
    except:
        log("land送出失敗 -> Emergency")
        tello.Emergency()
    finally:
        try:
            cap.release()
            cv2.destroyAllWindows()
        except:
            pass
        log("終了")