# capture_test.py
import cv2, time
urls = [
  "udp://0.0.0.0:11111?overrun_nonfatal=1&fifo_size=5000000&reuse=1",
  "udp://@:11111",
]
for u in urls:
    print("TRY:", u)
    cap = cv2.VideoCapture(u, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    t0=time.time(); ok=False
    while time.time()-t0<10:
        r, f = cap.read()
        if r and f is not None and f.size>0:
            print("OK frame", f.shape); ok=True; break
        time.sleep(0.02)
    cap.release()
    if ok: break
