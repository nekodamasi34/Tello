# -*- coding: utf-8 -*-
import tello
import time
import cv2
import threading
from datetime import datetime
import os
import numpy as np

LOCAL_IP = '192.168.10.1'
LOCAL_PORT_VIDEO = '11111'
addr = 'udp://' + LOCAL_IP + ':' + str(LOCAL_PORT_VIDEO)

# ===== 表示/デバッグ設定 =====
SHOW_FRAME   = True       # 映像+HUD
SHOW_MASKS   = False      # mキーでトグル
SHOW_OVERLAY = True       # oキーでトグル（色マスク合成）

VIEW_WINDOW_NAME = "view"
RED_MASK_WINDOW  = "red_mask"
BLUE_MASK_WINDOW = "blue_mask"
VIEW_MAX_WIDTH   = 960

# オーバーレイ透明度
RED_ALPHA  = 0.35
BLUE_ALPHA = 0.35
BOTH_ALPHA = 0.45

# ===== ログ管理（うるさくない版） =====
LOG_SILENT  = 0   # 決定/エラー中心
LOG_NORMAL  = 1   # 1秒ごとに要点
LOG_VERBOSE = 2   # 詳細多め（従来）
LOG_MODE    = LOG_NORMAL

_last_print = {}  # スロットル用

def _ts():
    return datetime.now().strftime('%H:%M:%S.%f')[:-3]

def logx(level, tag, msg, throttle=None):
    """レベル＆スロットル付きログ"""
    global LOG_MODE, _last_print
    if level > LOG_MODE:
        return
    now = time.time()
    if throttle is not None:
        last = _last_print.get(tag, 0.0)
        if now - last < throttle:
            return
        _last_print[tag] = now
    print(f"[{_ts()}] {msg}")

def log_key(msg):   # 重要イベント（決定/状態遷移）
    print(f"[{_ts()}] {msg}")

def log_err(msg):   # エラーは常に出す
    print(f"[{_ts()}] [ERROR] {msg}")

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

# ===== フラグ =====
timer = None
timer_flag = True
start_flag = False
finish = False
level_flag = False  # False=RED参照, True=BLUE参照

def InterruptTimer():
    global timer_flag, start_flag
    timer_flag = True
    start_flag = False
    logx(LOG_NORMAL, "timer", "Timer ready（次の意思決定OK）")

# ===== 表示系 =====
def draw_hud(img, fps, red_per, blue_per, mode_is_blue):
    h, w = img.shape[:2]
    panel_w = min(420, int(w * 0.45))
    panel_h = 176
    x0, y0 = 10, 10
    x1, y1 = x0 + panel_w, y0 + panel_h
    overlay = img.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)

    base = y0 + 28
    lh = 26
    color_txt  = (255, 255, 255)
    color_red  = (0, 0, 255)
    color_blue = (255, 0, 0)

    cv2.putText(img, f"FPS   : {fps:>4.0f}", (x0+12, base), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_txt, 2, cv2.LINE_AA)
    cv2.putText(img, f"RED   : {red_per:>5.2f}%  (thr {red_per_max}%)",  (x0+12, base+lh),   cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_red,  2, cv2.LINE_AA)
    cv2.putText(img, f"BLUE  : {blue_per:>5.2f}%  (thr {blue_per_max}%)", (x0+12, base+lh*2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_blue, 2, cv2.LINE_AA)
    mode_txt = "MODE: BLUE (LEVEL=BLUE)" if mode_is_blue else "MODE: RED (LEVEL=RED)"
    cv2.putText(img, mode_txt, (x0+12, base+lh*3), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2, cv2.LINE_AA)

    # 右上にステータス
    flags = [
        f"LogMode={['SILENT','NORMAL','VERBOSE'][LOG_MODE]}",
        f"overlay={'ON' if SHOW_OVERLAY else 'OFF'}",
        f"masks_win={'ON' if SHOW_MASKS else 'OFF'}",
        f"timer_flag={timer_flag}",
        f"start_flag={start_flag}",
        f"level={'BLUE' if level_flag else 'RED'}",
        f"finish={finish}",
    ]
    fx0, fy0 = w - 10, 10
    for i, line in enumerate(flags):
        (tw, th), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.putText(img, line, (fx0 - tw, fy0 + th + i*22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (240,240,240), 2, cv2.LINE_AA)

    # 中央クロスヘア
    cx, cy = w // 2, h // 2
    cv2.drawMarker(img, (cx, cy), (0, 255, 255), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)

def apply_color_overlay(view_bgr, mask_red_small, mask_blue_small,
                        red_alpha=RED_ALPHA, blue_alpha=BLUE_ALPHA, both_alpha=BOTH_ALPHA):
    h, w = view_bgr.shape[:2]
    mr = cv2.resize(mask_red_small,  (w, h), interpolation=cv2.INTER_NEAREST)
    mb = cv2.resize(mask_blue_small, (w, h), interpolation=cv2.INTER_NEAREST)
    mr = mr > 0
    mb = mb > 0
    both = mr & mb

    out = view_bgr.astype(np.float32)
    red_color  = np.array([0, 0, 255], dtype=np.float32)
    blue_color = np.array([255, 0, 0], dtype=np.float32)
    both_color = np.array([255, 0, 255], dtype=np.float32)

    if both.any():
        out[both] = out[both] * (1.0 - both_alpha) + both_color * both_alpha
    only_red = mr & ~both
    if only_red.any():
        out[only_red] = out[only_red] * (1.0 - red_alpha) + red_color * red_alpha
    only_blue = mb & ~both
    if only_blue.any():
        out[only_blue] = out[only_blue] * (1.0 - blue_alpha) + blue_color * blue_alpha

    return np.clip(out, 0, 255).astype(np.uint8)

def save_frame(frame, prefix="view"):
    os.makedirs("frames", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    path = f"frames/{prefix}_{ts}.png"
    cv2.imwrite(path, frame)
    log_key(f"[SAVE] {path}")

def handle_key_events():
    """
    q/ESC: 終了, m: マスク窓, o: オーバーレイ, s: スクショ, g: ログモード切替
    """
    global SHOW_MASKS, SHOW_OVERLAY, LOG_MODE
    k = cv2.waitKey(1) & 0xFF
    if k in (27, ord('q')):
        return "quit"
    elif k == ord('m'):
        SHOW_MASKS = not SHOW_MASKS
        log_key(f"[KEY] masks_win -> {SHOW_MASKS}")
        if not SHOW_MASKS:
            try:
                cv2.destroyWindow(RED_MASK_WINDOW)
                cv2.destroyWindow(BLUE_MASK_WINDOW)
            except:
                pass
        return "none"
    elif k == ord('o'):
        SHOW_OVERLAY = not SHOW_OVERLAY
        log_key(f"[KEY] overlay -> {SHOW_OVERLAY}")
        return "none"
    elif k == ord('s'):
        return "save"
    elif k == ord('g'):
        LOG_MODE = (LOG_MODE + 1) % 3
        log_key(f"[KEY] LogMode -> {['SILENT','NORMAL','VERBOSE'][LOG_MODE]}")
        return "none"
    return "none"

# ===== メイン =====
try:
    log_key("=== Tello 初期化 ===")
    log_key("Send: command");  tello.Send("command")
    log_key("Send: streamon"); tello.Send("streamon")
    log_key("Send: takeoff");  tello.Send("takeoff")

    time.sleep(2.0)
    log_key("離陸後ウェイト完了")

    cap = cv2.VideoCapture(addr)
    if not cap.isOpened():
        log_key("VideoCaptureオープン失敗？再トライ")
        time.sleep(0.8)
        cap.open(addr)

    if SHOW_FRAME:
        cv2.namedWindow(VIEW_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(VIEW_WINDOW_NAME, VIEW_MAX_WIDTH, int(VIEW_MAX_WIDTH * 9 / 16))

    last_ts = time.time()
    frame_cnt = 0
    fps_disp = 0.0

    log_key("=== ループ開始 ===")
    while cap.isOpened() and not finish:
        ret, frame = cap.read()
        if not ret or frame is None:
            time.sleep(0.01)
            continue

        # FPS計測（1秒毎の要点ログだけ）
        frame_cnt += 1
        now = time.time()
        if now - last_ts >= 1.0:
            fps_disp = frame_cnt / (now - last_ts)
            frame_cnt = 0
            last_ts = now
            logx(LOG_NORMAL, "fps", f"FPS={fps_disp:.0f}/s", throttle=1.0)

        # 検出
        frame_small = cv2.resize(frame, (320, 240))
        hsv = cv2.cvtColor(frame_small, cv2.COLOR_BGR2HSV)

        mask_red1 = cv2.inRange(hsv, red_low_point,  red_high_point)
        mask_red2 = cv2.inRange(hsv, red2_low_point, red2_high_point)
        red_image_mask = mask_red1 | mask_red2
        blue_image_mask = cv2.inRange(hsv, blue_low_point, blue_high_point)

        red_white  = cv2.countNonZero(red_image_mask)
        red_black  = red_image_mask.size - red_white
        red_per  = round(red_white / max(1, (red_white + red_black)) * 100, 2)

        blue_white = cv2.countNonZero(blue_image_mask)
        blue_black = blue_image_mask.size - blue_white
        blue_per = round(blue_white / max(1, (blue_white + blue_black)) * 100, 2)

        # 要点だけ1秒に1回
        logx(LOG_NORMAL, "stats", f"RED={red_per}% / BLUE={blue_per}%  MODE={'BLUE' if level_flag else 'RED'}", throttle=1.0)
        # 詳細が欲しければ Verbose に
        logx(LOG_VERBOSE, "detail", f"HSV red1{red_low_point}->{red_high_point} red2{red2_low_point}->{red2_high_point} blue{blue_low_point}->{blue_high_point}")

        # ===== 画面表示 =====
        if SHOW_FRAME:
            view = frame.copy()
            if SHOW_OVERLAY:
                view = apply_color_overlay(view, red_image_mask, blue_image_mask,
                                           red_alpha=RED_ALPHA, blue_alpha=BLUE_ALPHA, both_alpha=BOTH_ALPHA)
            draw_hud(view, fps_disp, red_per, blue_per, level_flag)
            if view.shape[1] > VIEW_MAX_WIDTH:
                ratio = VIEW_MAX_WIDTH / view.shape[1]
                view = cv2.resize(view, (VIEW_MAX_WIDTH, int(view.shape[0] * ratio)))
            cv2.imshow(VIEW_WINDOW_NAME, view)

        if SHOW_MASKS:
            show_r = cv2.resize(red_image_mask,  (red_image_mask.shape[1]*2,  red_image_mask.shape[0]*2),  interpolation=cv2.INTER_NEAREST)
            show_b = cv2.resize(blue_image_mask, (blue_image_mask.shape[1]*2, blue_image_mask.shape[0]*2), interpolation=cv2.INTER_NEAREST)
            cv2.imshow(RED_MASK_WINDOW,  show_r)
            cv2.imshow(BLUE_MASK_WINDOW, show_b)

        # ===== 3秒毎の意思決定 =====
        if timer_flag:
            if not start_flag:
                timer = threading.Timer(timer_constant, InterruptTimer)
                timer.daemon = True
                timer.start()
                start_flag = True
            timer_flag = False

            log_key("=== 意思決定 ===")
            log_key(f"MODE={'BLUE' if level_flag else 'RED'}  red={red_per}% thr={red_per_max}%  blue={blue_per}% thr={blue_per_max}%")

            if not level_flag:
                if red_per < red_per_max:
                    log_key("Action: forward 20（赤未達）")
                    tello.Send("forward 20")
                else:
                    log_key("Action: ccw 90（赤達成→青モードへ）")
                    tello.Send("ccw 90")
                    level_flag = True
            else:
                if blue_per < blue_per_max:
                    log_key("Action: forward 20（青未達）")
                    tello.Send("forward 20")
                else:
                    log_key("Action: cw 90（青達成→finish=True）")
                    tello.Send("cw 90")
                    finish = True

        # ===== キー入力 =====
        action = handle_key_events()
        if action == "quit":
            log_key("[KEY] quit -> 探索終了へ")
            finish = True
        elif action == "save" and SHOW_FRAME:
            save_frame(view, prefix="view")

    log_key("=== 探索フェーズ終了 ===")
    time.sleep(5)
    log_key("Action: forward 50（終了前の演出）")
    tello.Send("forward 50")

    time.sleep(5)
    log_key("Action: land（着陸）")
    tello.Send("land")

    cap.release()
    cv2.destroyAllWindows()
    log_key("リソース開放完了")

except KeyboardInterrupt:
    log_err("KeyboardInterrupt -> Emergency停止")
    tello.Emergency()

except Exception as e:
    log_err(f"例外発生: {repr(e)}")
    try:
        log_err("フェイルセーフ: land送出")
        tello.Send("land")
    except:
        log_err("land送出失敗 -> Emergency")
        tello.Emergency()
    finally:
        try:
            cap.release()
            cv2.destroyAllWindows()
        except:
            pass
        log_err("終了")
