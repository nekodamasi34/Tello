# -*- coding: utf-8 -*-
import tello
import time
import cv2
import threading
from datetime import datetime
import os
import numpy as np
from collections import deque

# ===== 低遅延用 受信URL（まずはローカル待受→失敗したらダイレクト） =====
ADDR_PRIMARY = "udp://0.0.0.0:11111?fifo_size=262144&overrun_nonfatal=1"
ADDR_DIRECT  = "udp://192.168.10.1:11111?fifo_size=262144&overrun_nonfatal=1"

# ===== 表示/デバッグ設定 =====
SHOW_FRAME   = True        # 映像 + HUD
SHOW_MASKS   = True        # mキーでトグル（デバッグ用）
SHOW_OVERLAY = True        # oキーでトグル（色マスク合成）
VIEW_WINDOW_NAME = "view"
RED_MASK_WINDOW  = "red_mask"
BLUE_MASK_WINDOW = "blue_mask"
VIEW_MAX_WIDTH   = 960     # 画面幅を抑えると軽くなる（800~960推奨）

# ===== オーバーレイ（加算合成の強さ） =====
# 透明度ではなく「明るさ加算」で染める。軽くて速い。
RED_GAIN   = 90   # 赤マスクが乗る明るさ(0-255)
BLUE_GAIN  = 90   # 青
BOTH_GAIN  = 110  # 赤青重なり（マゼンタ）

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

# ===== ログ（静かめ設計） =====
LOG_SILENT  = 0
LOG_NORMAL  = 1
LOG_VERBOSE = 2
LOG_MODE    = LOG_NORMAL
_last_print = {}

def _ts(): return datetime.now().strftime('%H:%M:%S.%f')[:-3]
def logx(level, tag, msg, throttle=None):
    global LOG_MODE, _last_print
    if level > LOG_MODE: return
    now = time.time()
    if throttle is not None:
        last = _last_print.get(tag, 0.0)
        if now - last < throttle: return
        _last_print[tag] = now
    print(f"[{_ts()}] {msg}")
def log_key(msg): print(f"[{_ts()}] {msg}")
def log_err(msg): print(f"[{_ts()}] [ERROR] {msg}")

def InterruptTimer():
    global timer_flag, start_flag
    timer_flag = True
    start_flag = False
    logx(LOG_NORMAL, "timer", "Timer ready（次の意思決定OK）")

# ===== 受信：最新フレームだけ保持するスレッド =====
def start_reader(cap):
    q = deque(maxlen=1)
    running = True
    def _reader():
        while running:
            ret, f = cap.read()
            if ret and f is not None:
                q.append(f)
            else:
                time.sleep(0.005)
    th = threading.Thread(target=_reader, daemon=True)
    th.start()
    return q, lambda: setattr(_reader, "__doc__", None) or None, th  # ダミー停止フック（デーモンなので終了時に落ちる）

# ===== HUD描画 =====
def draw_hud(img, fps, red_per, blue_per, mode_is_blue):
    h, w = img.shape[:2]
    panel_w = min(400, int(w * 0.4))
    panel_h = 150
    x0, y0 = 10, 10
    x1, y1 = x0 + panel_w, y0 + panel_h
    overlay = img.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)

    base = y0 + 26
    lh = 26
    color_txt  = (255, 255, 255)
    color_red  = (0, 0, 255)
    color_blue = (255, 0, 0)

    cv2.putText(img, f"FPS   : {fps:>4.0f}", (x0+12, base), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_txt, 2, cv2.LINE_AA)
    cv2.putText(img, f"RED   : {red_per:>5.2f}% (thr {red_per_max}%)",  (x0+12, base+lh),   cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_red,  2, cv2.LINE_AA)
    cv2.putText(img, f"BLUE  : {blue_per:>5.2f}% (thr {blue_per_max}%)", (x0+12, base+lh*2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color_blue, 2, cv2.LINE_AA)
    mode_txt = "MODE: BLUE" if mode_is_blue else "MODE: RED"
    cv2.putText(img, mode_txt, (x0+12, base+lh*3), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,255), 2, cv2.LINE_AA)

    # 右上にステータス
    flags = [
        f"Log={['SIL','NOR','VER'][LOG_MODE]}",
        f"Overlay={'ON' if SHOW_OVERLAY else 'OFF'}",
        f"MaskWin={'ON' if SHOW_MASKS else 'OFF'}",
        f"Tmr={int(timer_flag)} St={int(start_flag)}",
        f"Lvl={'B' if level_flag else 'R'} Fin={int(finish)}",
    ]
    fx0, fy0 = w - 10, 10
    for i, line in enumerate(flags):
        (tw, th), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.putText(img, line, (fx0 - tw, fy0 + th + i*22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235,235,235), 2, cv2.LINE_AA)

    # 中央クロスヘア
    cx, cy = w // 2, h // 2
    cv2.drawMarker(img, (cx, cy), (0, 255, 255), markerType=cv2.MARKER_CROSS, markerSize=20, thickness=2)

# ===== 高速オーバーレイ（加算合成：cv2.add/bitwise のみ） =====
def fast_additive_overlay(view_bgr, mask_red_small, mask_blue_small):
    h, w = view_bgr.shape[:2]
    mr = cv2.resize(mask_red_small,  (w, h), interpolation=cv2.INTER_NEAREST)
    mb = cv2.resize(mask_blue_small, (w, h), interpolation=cv2.INTER_NEAREST)
    both = cv2.bitwise_and(mr, mb)

    # 固定色のレイヤ（BGR）
    red_layer   = np.zeros_like(view_bgr);  red_layer[:, :, 2] = RED_GAIN
    blue_layer  = np.zeros_like(view_bgr);  blue_layer[:, :, 0] = BLUE_GAIN
    mag_layer   = np.zeros_like(view_bgr);  mag_layer[:, :, 0] = BOTH_GAIN; mag_layer[:, :, 2] = BOTH_GAIN

    # 重なりを先に加算
    out = cv2.add(view_bgr, cv2.bitwise_and(mag_layer, mag_layer, mask=both))

    not_both   = cv2.bitwise_not(both)
    only_red   = cv2.bitwise_and(mr, not_both)
    only_blue  = cv2.bitwise_and(mb, not_both)

    out = cv2.add(out, cv2.bitwise_and(red_layer,  red_layer,  mask=only_red))
    out = cv2.add(out, cv2.bitwise_and(blue_layer, blue_layer, mask=only_blue))
    return out

def save_frame(frame, prefix="view"):
    os.makedirs("frames", exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    path = f"frames/{prefix}_{ts}.png"
    cv2.imwrite(path, frame)
    log_key(f"[SAVE] {path}")

def handle_key_events():
    global SHOW_MASKS, SHOW_OVERLAY, LOG_MODE
    k = cv2.waitKey(1) & 0xFF
    if k in (27, ord('q')):
        return "quit"
    elif k == ord('m'):
        SHOW_MASKS = not SHOW_MASKS
        log_key(f"[KEY] MaskWin -> {SHOW_MASKS}")
        if not SHOW_MASKS:
            for wn in (RED_MASK_WINDOW, BLUE_MASK_WINDOW):
                try: cv2.destroyWindow(wn)
                except: pass
        return "none"
    elif k == ord('o'):
        SHOW_OVERLAY = not SHOW_OVERLAY
        log_key(f"[KEY] Overlay -> {SHOW_OVERLAY}")
        return "none"
    elif k == ord('s'):
        return "save"
    elif k == ord('g'):
        LOG_MODE = (LOG_MODE + 1) % 3
        log_key(f"[KEY] Log -> {['SILENT','NORMAL','VERBOSE'][LOG_MODE]}")
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

    # 受信開始（まずはPRIMARY、ダメならDIRECT）
    cap = cv2.VideoCapture(ADDR_PRIMARY, cv2.CAP_FFMPEG)
    try: cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except: pass
    if not cap.isOpened():
        log_key("PRIMARY失敗→DIRECTに切替")
        cap = cv2.VideoCapture(ADDR_DIRECT, cv2.CAP_FFMPEG)
        try: cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except: pass
        if not cap.isOpened():
            raise RuntimeError("VideoCapture open failed for both PRIMARY and DIRECT")

    # 最新フレームだけ取るグラバースレッド
    q, stop_reader, th = start_reader(cap)

    # ウィンドウ準備
    if SHOW_FRAME:
        cv2.namedWindow(VIEW_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(VIEW_WINDOW_NAME, VIEW_MAX_WIDTH, int(VIEW_MAX_WIDTH * 9 / 16))

    last_ts = time.time()
    frame_cnt = 0
    fps_disp = 0.0
    view = None  # スクショ用

    log_key("=== ループ開始 ===")
    while cap.isOpened() and not finish:
        if not q:
            time.sleep(0.005); continue
        frame = q[-1]

        # FPS（1秒に1回だけログ）
        frame_cnt += 1
        now = time.time()
        if now - last_ts >= 1.0:
            fps_disp = frame_cnt / (now - last_ts)
            frame_cnt, last_ts = 0, now
            logx(LOG_NORMAL, "fps", f"FPS={fps_disp:.0f}/s", throttle=1.0)

        # 検出は 320x240 で軽量処理
        frame_small = cv2.resize(frame, (320, 240))
        hsv = cv2.cvtColor(frame_small, cv2.COLOR_BGR2HSV)

        mask_red1 = cv2.inRange(hsv, red_low_point,  red_high_point)
        mask_red2 = cv2.inRange(hsv, red2_low_point, red2_high_point)
        red_mask  = cv2.bitwise_or(mask_red1, mask_red2)
        blue_mask = cv2.inRange(hsv, blue_low_point, blue_high_point)

        rw = cv2.countNonZero(red_mask)
        bw = cv2.countNonZero(blue_mask)
        total = red_mask.size  # = blue_mask.size
        red_per  = round(rw / max(1, total) * 100, 2)
        blue_per = round(bw / max(1, total) * 100, 2)

        logx(LOG_NORMAL, "stats", f"RED={red_per}% / BLUE={blue_per}%  MODE={'BLUE' if level_flag else 'RED'}", throttle=1.0)
        logx(LOG_VERBOSE, "detail", f"HSV red1{red_low_point}->{red_high_point} red2{red2_low_point}->{red2_high_point} blue{blue_low_point}->{blue_high_point}")

        # ===== 表示 =====
        if SHOW_FRAME:
            view = frame.copy()
            if SHOW_OVERLAY:
                view = fast_additive_overlay(view, red_mask, blue_mask)
            draw_hud(view, fps_disp, red_per, blue_per, level_flag)

            if view.shape[1] > VIEW_MAX_WIDTH:
                ratio = VIEW_MAX_WIDTH / view.shape[1]
                view = cv2.resize(view, (VIEW_MAX_WIDTH, int(view.shape[0] * ratio)))
            cv2.imshow(VIEW_WINDOW_NAME, view)

        if SHOW_MASKS:
            show_r = cv2.resize(red_mask,  (red_mask.shape[1]*2,  red_mask.shape[0]*2),  interpolation=cv2.INTER_NEAREST)
            show_b = cv2.resize(blue_mask, (blue_mask.shape[1]*2, blue_mask.shape[0]*2), interpolation=cv2.INTER_NEAREST)
            cv2.imshow(RED_MASK_WINDOW,  show_r)
            cv2.imshow(BLUE_MASK_WINDOW, show_b)

        # ===== 意思決定（3秒ごと） =====
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
        elif action == "save" and view is not None:
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
