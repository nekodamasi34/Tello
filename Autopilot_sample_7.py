# -*- coding: utf-8 -*-
import tello
import time
import cv2
import threading
from datetime import datetime
import os
import numpy as np
from collections import deque

# ========= 低遅延受信 =========
ADDRS = [
    "udp://0.0.0.0:11111?fifo_size=262144&overrun_nonfatal=1",
    "udp://192.168.10.1:11111?fifo_size=262144&overrun_nonfatal=1",
]

# ========= 表示/デバッグ =========
SHOW_FRAME   = True
SHOW_MASKS   = False
SHOW_OVERLAY = True
VIEW_WINDOW_NAME = "view"
VIEW_MAX_WIDTH   = 960

# オーバーレイ（加算合成の明るさ）
RED_GAIN   = 90
BLUE_GAIN  = 90
GREEN_GAIN = 90
BOTH_GAIN  = 40   # 重なり微追加

# ========= HSVしきい値（環境で要調整） =========
RED1_LOW,  RED1_HIGH  = (0,   120, 100), (10, 255, 255)
RED2_LOW,  RED2_HIGH  = (160, 120, 100), (179,255, 255)
BLUE_LOW,  BLUE_HIGH  = (100, 150,  80), (130,255, 255)
GREEN_LOW, GREEN_HIGH = (35,   80,  80), (85, 255, 255)

# 検出割合しきい値（%）
RED_THR   = 5.0
BLUE_THR  = 5.0
GREEN_THR = 5.0

# ========= ミッション距離/角度 =========
ALT_SAFE      = 40    # 離陸後の上昇(cm)
FORWARD_STEP  = 40    # 直進の一回分(cm) … 繰り返す
LEFT_STEP     = 40    # 左移動の一回分(cm) … 繰り返す
YAW_CCW       = 180   # 左旋回(deg)
TELLO_SPEED   = 30    # speed設定

# ========= コマンド発行間隔 =========
TIMER_SEC = 1.0

# ========= コマンド非同期実行 =========
CMD_TIMEOUT_SEC = 12.0  # 旋回などが終わらない/応答こない時の保険

cmd_busy = False          # コマンド実行中フラグ
cmd_started_at = 0.0      # 実行開始時刻
cmd_name = ""             # "ccw 180" とか
cmd_thread = None         # 実行スレッド
cmd_done_evt = threading.Event()

# ========= ログ =========
LOG_SILENT, LOG_NORMAL, LOG_VERBOSE = 0, 1, 2
LOG_MODE = LOG_NORMAL
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

# ========= タイマー =========
timer_flag = True
start_flag = False
def InterruptTimer():
    global timer_flag, start_flag
    timer_flag = True
    start_flag = False
    logx(LOG_NORMAL, "timer", "Timer ready", throttle=1.0)

# ========= 受信（最新のみ） =========
def start_reader(cap):
    q = deque(maxlen=1)
    def _reader():
        while True:
            ret, f = cap.read()
            if ret and f is not None:
                q.append(f)
            else:
                time.sleep(0.005)
    th = threading.Thread(target=_reader, daemon=True)
    th.start()
    return q

# ========= 画像処理 =========
def overlay_add(view_bgr, mr_small, mb_small, mg_small):
    h, w = view_bgr.shape[:2]
    mr = cv2.resize(mr_small, (w, h), interpolation=cv2.INTER_NEAREST)
    mb = cv2.resize(mb_small, (w, h), interpolation=cv2.INTER_NEAREST)
    mg = cv2.resize(mg_small, (w, h), interpolation=cv2.INTER_NEAREST)

    red   = np.zeros_like(view_bgr);  red[:,:,2] = RED_GAIN
    blue  = np.zeros_like(view_bgr);  blue[:,:,0] = BLUE_GAIN
    green = np.zeros_like(view_bgr);  green[:,:,1] = GREEN_GAIN
    both  = np.zeros_like(view_bgr);  both[:,:,:]  = BOTH_GAIN

    rb = cv2.bitwise_and(mr, mb)
    rg = cv2.bitwise_and(mr, mg)
    bg = cv2.bitwise_and(mb, mg)
    any_overlap = cv2.bitwise_or(cv2.bitwise_or(rb, rg), bg)

    out = view_bgr
    out = cv2.add(out, cv2.bitwise_and(red,   red,   mask=mr))
    out = cv2.add(out, cv2.bitwise_and(blue,  blue,  mask=mb))
    out = cv2.add(out, cv2.bitwise_and(green, green, mask=mg))
    out = cv2.add(out, cv2.bitwise_and(both,  both,  mask=any_overlap))
    return out

# ========= HUD =========
def draw_hud(img, fps, r, b, g, move_mode, blue_latched, rotated, rotate_req):
    h, w = img.shape[:2]
    panel_w = min(520, int(w * 0.55))
    panel_h = 220
    x0, y0 = 10, 10
    x1, y1 = x0 + panel_w, y0 + panel_h
    overlay = img.copy()
    cv2.rectangle(overlay, (x0, y0), (x1, y1), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.35, img, 0.65, 0, img)

    base = y0 + 26; lh = 26
    cv2.putText(img, f"FPS   : {fps:>4.0f}", (x0+12, base), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,255,255), 2, cv2.LINE_AA)
    cv2.putText(img, f"RED   : {r:>5.2f}% (thr {RED_THR}%)",   (x0+12, base+lh),   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,0,255),   2, cv2.LINE_AA)
    cv2.putText(img, f"BLUE  : {b:>5.2f}% (thr {BLUE_THR}%)",  (x0+12, base+lh*2), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255,0,0),  2, cv2.LINE_AA)
    cv2.putText(img, f"GREEN : {g:>5.2f}% (thr {GREEN_THR}%)", (x0+12, base+lh*3), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0,255,0),  2, cv2.LINE_AA)

    status = [
        f"MOVE_MODE: {move_mode}   (blue_latched={blue_latched})",
        f"ROTATE: requested={rotate_req}  done={rotated}",
        f"CMD: {'BUSY ' + cmd_name if cmd_busy else 'IDLE'}",
        f"Log={['SIL','NOR','VER'][LOG_MODE]} Overlay={'ON' if SHOW_OVERLAY else 'OFF'}"
    ]
    fx, fy = w - 10, 10
    for i, line in enumerate(status):
        (tw, th), _ = cv2.getTextSize(line, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.putText(img, line, (fx - tw, fy + th + i*22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (235,235,235), 2, cv2.LINE_AA)

    cx, cy = w//2, h//2
    cv2.drawMarker(img, (cx, cy), (0,255,255), cv2.MARKER_CROSS, 20, 2)

# ========= キー =========
def handle_key_events():
    global SHOW_MASKS, SHOW_OVERLAY, LOG_MODE
    k = cv2.waitKey(1) & 0xFF
    if k in (27, ord('q')): return "quit"
    if k == ord('m'):
        SHOW_MASKS = not SHOW_MASKS; log_key(f"[KEY] MaskWin -> {SHOW_MASKS}"); return "none"
    if k == ord('o'):
        SHOW_OVERLAY = not SHOW_OVERLAY; log_key(f"[KEY] Overlay -> {SHOW_OVERLAY}"); return "none"
    if k == ord('s'): return "save"
    if k == ord('g'):
        LOG_MODE = (LOG_MODE + 1) % 3
        log_key(f"[KEY] Log -> {['SILENT','NORMAL','VERBOSE'][LOG_MODE]}"); return "none"
    return "none"

# ========= 送信（同期） =========
def send(cmd, val=None):
    if val is None:
        log_key(f"Send: {cmd}"); tello.Send(cmd)
    else:
        log_key(f"Send: {cmd} {val}"); tello.Send(f"{cmd} {val}")

# ========= 送信（非同期） =========
def send_async(cmd, val=None):
    """tello.Send を別スレッドで実行してブロッキングを回避"""
    global cmd_busy, cmd_started_at, cmd_name, cmd_thread, cmd_done_evt
    if cmd_busy and cmd_thread and cmd_thread.is_alive():
        return False
    cmd_done_evt.clear()
    cmd_busy = True
    cmd_started_at = time.time()
    cmd_name = f"{cmd} {val}" if val is not None else cmd

    def worker():
        global cmd_busy
        try:
            send(cmd, val)
        except Exception as e:
            log_err(f"async send error: {e!r}")
        finally:
            cmd_busy = False
            cmd_done_evt.set()

    cmd_thread = threading.Thread(target=worker, daemon=True)
    cmd_thread.start()
    return True

# ========= メイン =========
try:
    log_key("=== Tello 初期化 ===")
    tello.Send("command")
    tello.Send(f"speed {TELLO_SPEED}")
    tello.Send("streamon")

    # 離陸＆上昇
    send("takeoff")
    if ALT_SAFE > 20: send("up", ALT_SAFE)

    # 映像
    cap = None
    for url in ADDRS:
        c = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        try: c.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except: pass
        if c.isOpened():
            cap = c
            log_key(f"[VIDEO] open OK: {url}")
            break
    if cap is None:
        log_key("[VIDEO] open失敗（映像無しでも進行）")

    q = start_reader(cap) if cap else None
    if SHOW_FRAME and cap:
        cv2.namedWindow(VIEW_WINDOW_NAME, cv2.WINDOW_NORMAL)
        cv2.setWindowProperty(VIEW_WINDOW_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    # タイマー開始
    t = threading.Timer(TIMER_SEC, InterruptTimer); t.daemon=True; t.start()
    start_flag=True; timer_flag=False

    # ======= ここが新ロジック用の状態 =======
    move_mode = "FWD"        # 最初は必ず前進繰り返し
    blue_latched = False     # 青を見たら True（以降ずっとLEFTモード）
    rotate_requested = False # 緑を見たら True（ccwが撃てるタイミングで撃つ）
    rotated_done = False     # ccw180を1回やったら True（2回目はしない）
    rotating_now = False     # いまccw実行中
    finish = False
    landing = False

    last_ts = time.time(); fps_cnt = 0; fps = 0.0
    view = None

    log_key("=== ループ開始（イベント駆動） ===")
    while not finish:
        # フレーム
        if cap:
            if not q:
                time.sleep(0.005)
                continue
            frame = q[-1]
        else:
            time.sleep(0.01)
            frame = None

        # FPS
        now = time.time(); fps_cnt += 1
        if now - last_ts >= 1.0:
            fps = fps_cnt / (now - last_ts); fps_cnt = 0; last_ts = now
            logx(LOG_NORMAL, "fps", f"FPS={fps:.0f}", throttle=1.0)

        # 検出
        red_per = blue_per = green_per = 0.0
        red_m = blue_m = green_m = None
        if frame is not None:
            small = cv2.resize(frame, (320,240))
            hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

            r1 = cv2.inRange(hsv, RED1_LOW, RED1_HIGH)
            r2 = cv2.inRange(hsv, RED2_LOW, RED2_HIGH)
            red_m   = cv2.bitwise_or(r1, r2)
            blue_m  = cv2.inRange(hsv, BLUE_LOW,  BLUE_HIGH)
            green_m = cv2.inRange(hsv, GREEN_LOW, GREEN_HIGH)

            total = float(red_m.size)
            red_per   = round(cv2.countNonZero(red_m)   / max(1.0,total) * 100, 2)
            blue_per  = round(cv2.countNonZero(blue_m)  / max(1.0,total) * 100, 2)
            green_per = round(cv2.countNonZero(green_m) / max(1.0,total) * 100, 2)
            logx(LOG_NORMAL, "stats", f"R={red_per}% B={blue_per}% G={green_per}% mode={move_mode}", throttle=1.0)

        # ========= 非同期コマンドのタイムアウト監視 =========
        if cmd_busy and (time.time() - cmd_started_at > CMD_TIMEOUT_SEC):
            log_err(f"cmd timeout: {cmd_name} > {CMD_TIMEOUT_SEC}s -> 続行扱い")
            cmd_busy = False
            cmd_done_evt.set()

        # ========= イベントのラッチ/要求（順番関係なし） =========
        # 赤：最優先で着陸
        if (not landing) and (red_per >= RED_THR):
            landing = True
            log_key("[EVENT] 赤検知 -> LAND（最優先）")
            try:
                send("land")
            except:
                try: tello.Emergency()
                except: pass
            finish = True
            # landしたら即抜けたい
            continue

        # 青：左移動モードに切り替え（ラッチ）
        if (blue_per >= BLUE_THR) and (not blue_latched):
            blue_latched = True
            move_mode = "LEFT"
            log_key("[EVENT] 青検知 -> MOVE_MODE=LEFT（以降左繰り返し）")

        # 緑：ccw180を要求（1回だけ）
        if (green_per >= GREEN_THR) and (not rotated_done):
            if not rotate_requested and not rotating_now:
                rotate_requested = True
                log_key("[EVENT] 緑検知 -> ccw180 を要求")

        # ========= アクション実行（優先度：緑回転 > 移動） =========
        # 1) 緑要求があって、まだ回ってないなら回る（非同期→完了待ち）
        if rotate_requested and (not cmd_busy) and (not rotating_now):
            ok = send_async("ccw", YAW_CCW)
            if ok:
                rotating_now = True
                rotate_requested = False
                log_key(f"[ACTION] ccw {YAW_CCW} start (green)")
            # okじゃなければ次ループでまた試す

        # 旋回完了を検知
        if rotating_now and cmd_done_evt.is_set() and (not cmd_busy):
            rotating_now = False
            rotated_done = True

            blue_latched = False
            move_mode = "FWD"

            log_key("[ACTION] ccw 完了！ -> MOVE_MODE=FWD（強制）")

        # 2) 移動（タイマーで間引き）
        #   - 回転中/回転要求中は移動しない
        if timer_flag and (not cmd_busy) and (not rotating_now) and (not rotate_requested):
            if not blue_latched:
                # 最初は前進繰り返し
                send("forward", FORWARD_STEP)
            else:
                # 青見た後は左繰り返し
                send("left", LEFT_STEP)

            t = threading.Timer(TIMER_SEC, InterruptTimer); t.daemon=True; t.start()
            start_flag=True; timer_flag=False

        # ========= 表示 =========
        if SHOW_FRAME and frame is not None:
            view = frame.copy()
            if SHOW_OVERLAY:
                view = overlay_add(view, red_m, blue_m, green_m)
            draw_hud(view, fps, red_per, blue_per, green_per,
                     move_mode=("LEFT" if blue_latched else "FWD"),
                     blue_latched=blue_latched,
                     rotated=rotated_done,
                     rotate_req=rotate_requested)

            if view.shape[1] > VIEW_MAX_WIDTH:
                r = VIEW_MAX_WIDTH / view.shape[1]
                view = cv2.resize(view, (VIEW_MAX_WIDTH, int(view.shape[0]*r)))
            cv2.imshow(VIEW_WINDOW_NAME, view)

        if SHOW_MASKS and frame is not None:
            cv2.imshow("mask_red",   cv2.resize(red_m,   (640,480), interpolation=cv2.INTER_NEAREST))
            cv2.imshow("mask_blue",  cv2.resize(blue_m,  (640,480), interpolation=cv2.INTER_NEAREST))
            cv2.imshow("mask_green", cv2.resize(green_m, (640,480), interpolation=cv2.INTER_NEAREST))

        # キー
        act = handle_key_events()
        if act == "quit":
            log_key("[KEY] quit -> 強制着陸")
            try: tello.Send("land")
            except: tello.Emergency()
            break
        elif act == "save" and 'view' in locals() and view is not None:
            os.makedirs("frames", exist_ok=True)
            p = f"frames/view_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.png"
            cv2.imwrite(p, view); log_key(f"[SAVE] {p}")

    # 片付け
    if 'cap' in locals() and cap is not None:
        cap.release()
    cv2.destroyAllWindows()
    log_key("完了")

except KeyboardInterrupt:
    log_err("KeyboardInterrupt -> Emergency")
    try: tello.Send("land")
    except: tello.Emergency()

except Exception as e:
    log_err(f"例外: {e!r}")
    try: tello.Send("land")
    except: tello.Emergency()
    try: cv2.destroyAllWindows()
    except: pass
