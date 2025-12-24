# -*- coding: utf-8 -*-
import time
import cv2
import threading
from datetime import datetime
from djitellopy import Tello

# ===== デバッグ出力設定 =====
VERBOSE_DECISION_ONLY = False
SHOW_MASKS = False

# ===== HSVしきい値 =====
red_low_point   = (0,   120, 100)
red_high_point  = (10,  255, 255)
red2_low_point  = (160, 120, 100)
red2_high_point = (179, 255, 255)

blue_low_point  = (100, 150,  80)
blue_high_point = (130, 255, 255)

# ===== 意思決定パラメータ =====
timer_constant = 3.0
red_per_max  = 5.0
blue_per_max = 5.0

# ===== フラグ類 =====
timer_flag = True
start_flag = False
finish = False
level_flag = False  # False=RED参照, True=BLUE参照

# ===== ヘルパ =====
def log(*args):
    print(f"[{datetime.now().strftime('%H:%M:%S.%f')[:-3]}]", *args)

def InterruptTimer():
    global timer_flag, start_flag
    timer_flag = True
    start_flag = False
    log("InterruptTimer(): timer_flag=True, start_flag=False（次の意思決定OK）")

def ensure_video_stream(tello, warmup_sec=1.0, wait_total_sec=15.0):
    """
    OpenCV(FFmpeg)で Tello の映像を受信。
    まず 'udp://192.168.10.1:11111' を試し、失敗したら 'udp://0.0.0.0:11111' にフォールバック。
    戻り: ("capture", cap)
    """
    import cv2, time

    def try_open(url, label):
        log(f"[VIDEO] Try {label}: {url}")
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        start = time.time()
        while time.time() - start < wait_total_sec:
            ret, frame = cap.read()
            if ret and frame is not None:
                log(f"[VIDEO] フレーム受信 OK ({label})")
                return cap
            time.sleep(0.02)
        try:
            cap.release()
        except:
            pass
        return None

    # ストリームリセット
    try:
        tello.streamoff()
        time.sleep(0.2)
    except:
        pass
    tello.streamon()
    time.sleep(warmup_sec)

    # 1) 192.168.10.1:11111 を直接
    url1 = "udp://192.168.10.1:11111?overrun_nonfatal=1&fifo_size=5000000"
    cap = try_open(url1, "DIRECT-REMOTE")
    if cap is not None:
        return "capture", cap

    # 2) ローカル待受にフォールバック
    log("[VIDEO] DIRECT-REMOTE失敗 → LOCAL-LISTENへフォールバック")
    try:
        tello.streamoff()
        time.sleep(0.2)
    except:
        pass
    tello.streamon()
    time.sleep(1.0)

    url2 = "udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=5000000"
    cap = try_open(url2, "LOCAL-LISTEN")
    if cap is not None:
        return "capture", cap

    raise RuntimeError("Failed to grab video frames via OpenCV (both DIRECT-REMOTE and LOCAL-LISTEN)")

def main():
    global timer_flag, start_flag, finish, level_flag
    airborne = False  # 飛行中フラグ

    tello = Tello()
    try:
        log("=== Tello 初期化 ===")
        tello.connect()

        try:
            batt = tello.get_battery()
            log(f"Battery: {batt}%")
        except Exception as e:
            log(f"[WARN] バッテリー取得失敗: {e}")

        try:
            tello.set_speed(30)
        except Exception:
            pass

        # ==== 映像ストリームを安定化してから飛ばす ====
        log("Video stream 準備")
        video_mode, frame_source = ensure_video_stream(
            tello,
            warmup_sec=1.0,
            wait_total_sec=15.0
        )

        # ここでフレームが来ていることが保証されたので離陸
        log("Takeoff")
        tello.takeoff()
        airborne = True
        time.sleep(2.0)
        log("離陸後ウェイト完了")

        # FPS計測
        last_ts = time.time()
        frame_cnt = 0

        log("=== ループ開始 ===")
        while not finish:
            # 今回は "capture" 前提
            ret, frame = frame_source.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            frame_cnt += 1
            now = time.time()
            if now - last_ts >= 1.0:
                log(f"FPS: {frame_cnt:.0f} /s")
                frame_cnt = 0
                last_ts = now

            height, width = frame.shape[:2]
            frame_small = cv2.resize(frame, (320, 240))
            hsv = cv2.cvtColor(frame_small, cv2.COLOR_BGR2HSV)

            # 赤
            mask_red1 = cv2.inRange(hsv, red_low_point,  red_high_point)
            mask_red2 = cv2.inRange(hsv, red2_low_point, red2_high_point)
            red_image_mask = mask_red1 | mask_red2
            red_white = cv2.countNonZero(red_image_mask)
            red_black = red_image_mask.size - red_white
            red_per = round(red_white / max(1, (red_white + red_black)) * 100, 2)

            # 青
            blue_image_mask = cv2.inRange(hsv, blue_low_point, blue_high_point)
            blue_white = cv2.countNonZero(blue_image_mask)
            blue_black = blue_image_mask.size - blue_white
            blue_per = round(blue_white / max(1, (blue_white + blue_black)) * 100, 2)

            if not VERBOSE_DECISION_ONLY:
                log(f"Frame {width}x{height} / small 320x240")
                log(f"HSV赤1: {red_low_point}->{red_high_point}  赤2: {red2_low_point}->{red2_high_point}")
                log(f"HSV青 : {blue_low_point}->{blue_high_point}")
                log(f"赤mask: {red_per}%  (閾値 {red_per_max}%)")
                log(f"青mask: {blue_per}%  (閾値 {blue_per_max}%)")
                log(f"Flags => timer_flag={timer_flag}, start_flag={start_flag}, level_flag={'BLUE' if level_flag else 'RED'}, finish={finish}")

            if SHOW_MASKS:
                cv2.imshow("red_mask", red_image_mask)
                cv2.imshow("blue_mask", blue_image_mask)
                cv2.waitKey(1)

            # 3秒に1回だけ意思決定
            if timer_flag:
                if not start_flag:
                    log(f"Timer開始: {timer_constant}s")
                    t = threading.Timer(timer_constant, InterruptTimer)
                    t.daemon = True
                    t.start()
                    start_flag = True
                timer_flag = False

                log("=== 意思決定 ===")
                log(f"現在のモード: {'青参照(LEVEL=BLUE)' if level_flag else '赤参照(LEVEL=RED)'}")
                log(f"red_per={red_per}% (閾値{red_per_max}%), blue_per={blue_per}% (閾値{blue_per_max}%)")

                if not level_flag:
                    if red_per < red_per_max:
                        log("Action: forward 20（赤未達）")
                        tello.move_forward(20)
                    else:
                        log("Action: ccw 90（赤達成→青モードへ）")
                        tello.rotate_counter_clockwise(90)
                        level_flag = True
                        log(f"level_flag -> {level_flag}（True=青）")
                else:
                    if blue_per < blue_per_max:
                        log("Action: forward 20（青未達）")
                        tello.move_forward(20)
                    else:
                        log("Action: cw 90（青達成→finish=True）")
                        tello.rotate_clockwise(90)
                        finish = True
                        log(f"finish -> {finish}")

        log("=== 探索フェーズ終了 ===")
        time.sleep(5)
        log("Action: forward 50（終了前の演出）")
        tello.move_forward(50)

    except KeyboardInterrupt:
        log("KeyboardInterrupt検知 -> Emergency停止")
        try:
            if airborne:
                tello.emergency()
        except Exception as e:
            log(f"emergency失敗: {e}")

    except Exception as e:
        log("例外発生:", repr(e))
        try:
            if airborne:
                log("フェイルセーフ: land送出")
                tello.land()
        except Exception as e2:
            log(f"land送出失敗 -> emergency: {e2}")
            try:
                if airborne:
                    tello.emergency()
            except:
                pass
    finally:
        try:
            tello.streamoff()
        except:
            pass
        try:
            if 'frame_source' in locals():
                frame_source.release()
        except:
            pass
        try:
            cv2.destroyAllWindows()
        except:
            pass
        try:
            tello.end()
        except:
            pass
        log("リソース解放完了")

if __name__ == "__main__":
    main()
