import serial
import threading
import time
import csv
import os
from collections import deque
from datetime import datetime

# ================= CẤU HÌNH =================
SERIAL_PORT = "COM3"        # Đổi thành cổng của ESP32-C3 (VD: 'COM5' trên Windows hoặc '/dev/ttyACM0' trên Linux/Mac)
BAUD_RATE = 115200
OUTPUT_DIR = "geiger_data"
DEFAULT_CF = 0.0065         # Hệ số CF ước lượng ban đầu cho ống J305 (µSv/h per CPM), sẽ cập nhật lại ở TN3
# ============================================

os.makedirs(OUTPUT_DIR, exist_ok=True)
session_id = datetime.now().strftime("%Y%m%d_%H%M%S")

STREAM_FILE = os.path.join(OUTPUT_DIR, f"stream_1s_{session_id}.csv")
PULSE_FILE = os.path.join(OUTPUT_DIR, f"raw_pulses_{session_id}.csv")
CAL_FILE = os.path.join(OUTPUT_DIR, f"tn3_calibration_{session_id}.csv")

state = {
    "running": True,
    "location": "Vi_tri_co_dinh",
    "cf": DEFAULT_CF,
    "latest_cpm_out1": 0.0,
    "latest_cpm_out2": 0.0,
    "total_out1": 0,
    "total_out2": 0,
    "elapsed_s": 0
}
state_lock = threading.Lock()

# Bộ đệm trượt 60 giây để tính CPM thời gian thực
window_60s = deque(maxlen=61)


def serial_worker():
    try:
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.2)
    except Exception as e:
        print(f"[LỖI] Không mở được cổng {SERIAL_PORT}: {e}")
        state["running"] = False
        return

    with open(STREAM_FILE, "w", newline="", encoding="utf-8") as f_stream, \
         open(PULSE_FILE, "w", newline="", encoding="utf-8") as f_pulse:

        w_stream = csv.writer(f_stream)
        w_pulse = csv.writer(f_pulse)

        w_stream.writerow(["timestamp_iso", "elapsed_s", "esp_ms", "total_out1", "total_out2", "location"])
        w_pulse.writerow(["timestamp_iso", "esp_ms", "total_out1", "total_out2", "location"])

        start_pc_time = time.time()
        print(f"[OK] Đã kết nối {SERIAL_PORT}. Bắt đầu ghi dữ liệu vào thư mục '{OUTPUT_DIR}/'...\n")

        while state["running"]:
            try:
                raw_line = ser.readline().decode("utf-8", errors="ignore").strip()
                if not raw_line or raw_line.startswith("HEADER"):
                    continue

                parts = raw_line.split(",")
                if len(parts) != 4:
                    continue

                msg_type, esp_ms_str, c1_str, c2_str = parts
                esp_ms = int(esp_ms_str)
                c1 = int(c1_str)
                c2 = int(c2_str)
                now_iso = datetime.now().isoformat(timespec="milliseconds")

                with state_lock:
                    loc = state["location"]
                    cf = state["cf"]

                if msg_type == "PULSE":
                    w_pulse.writerow([now_iso, esp_ms, c1, c2, loc])
                    f_pulse.flush()

                elif msg_type == "TICK":
                    elapsed = int(round(time.time() - start_pc_time))
                    w_stream.writerow([now_iso, elapsed, esp_ms, c1, c2, loc])
                    f_stream.flush()

                    window_60s.append((time.time(), c1, c2))
                    if len(window_60s) >= 2:
                        dt = window_60s[-1][0] - window_60s[0][0]
                        if dt > 0:
                            cpm1 = (window_60s[-1][1] - window_60s[0][1]) * (60.0 / dt)
                            cpm2 = (window_60s[-1][2] - window_60s[0][2]) * (60.0 / dt)
                        else:
                            cpm1 = cpm2 = 0.0
                    else:
                        cpm1 = cpm2 = 0.0

                    h_est = cpm2 * cf
                    with state_lock:
                        state["latest_cpm_out1"] = cpm1
                        state["latest_cpm_out2"] = cpm2
                        state["total_out1"] = c1
                        state["total_out2"] = c2
                        state["elapsed_s"] = elapsed

                    print(
                        f"\r[{elapsed:4d}s | {loc}] "
                        f"Out1(thô): {c1} ({cpm1:5.1f} CPM) | "
                        f"Out2(555): {c2} ({cpm2:5.1f} CPM) | "
                        f"H_est: {h_est:.4f} µSv/h   ",
                        end="", flush=True
                    )
            except Exception:
                continue

    ser.close()


def main():
    # Khởi tạo file lưu cặp hiệu chuẩn TN3
    with open(CAL_FILE, "w", newline="", encoding="utf-8") as f_cal:
        csv.writer(f_cal).writerow([
            "timestamp_iso", "location", "cpm_out1", "cpm_out2", "H_ref_uSv_h"
        ])

    t = threading.Thread(target=serial_worker, daemon=True)
    t.start()

    print("Lệnh điều khiển nhanh (gõ và nhấn Enter bất cứ lúc nào):")
    print("  loc <ten_vi_tri>   -> Đổi vị trí đo (VD: loc Gan_tuong_be_tong)")
    print("  ref <gia_tri>      -> Lưu cặp hiệu chuẩn với máy thương mại (VD: ref 0.13)")
    print("  cf <he_so>         -> Cập nhật hệ số CF hiển thị (VD: cf 0.0062)")
    print("  quit               -> Kết thúc đo\n")

    while state["running"]:
        try:
            cmd = input().strip()
            if not cmd:
                continue
            if cmd.lower() == "quit":
                state["running"] = False
                print("\n[INFO] Đang dừng và lưu dữ liệu...")
                break
            elif cmd.lower().startswith("loc "):
                new_loc = cmd[4:].strip().replace(" ", "_")
                with state_lock:
                    state["location"] = new_loc
                window_60s.clear()  # Reset cửa sổ trượt khi đổi vị trí
                print(f"\n[INFO] Đã chuyển vị trí sang: {new_loc}")
            elif cmd.lower().startswith("ref "):
                h_ref = float(cmd[4:].strip())
                with state_lock:
                    loc = state["location"]
                    cpm1 = state["latest_cpm_out1"]
                    cpm2 = state["latest_cpm_out2"]
                with open(CAL_FILE, "a", newline="", encoding="utf-8") as f_cal:
                    csv.writer(f_cal).writerow([
                        datetime.now().isoformat(timespec="seconds"),
                        loc, round(cpm1, 2), round(cpm2, 2), h_ref
                    ])
                print(f"\n[TN3] Đã lưu cặp đo: CPM(out2)={cpm2:.2f}, H_ref={h_ref:.4f} µSv/h tại '{loc}'")
            elif cmd.lower().startswith("cf "):
                new_cf = float(cmd[3:].strip())
                with state_lock:
                    state["cf"] = new_cf
                print(f"\n[INFO] Đã cập nhật CF = {new_cf:.6f} µSv/h per CPM")
        except ValueError:
            print("\n[CẢNH BÁO] Giá trị số không hợp lệ.")
        except KeyboardInterrupt:
            state["running"] = False
            break

    t.join(timeout=2)
    print(f"[HOÀN TẤT] Các file đã lưu:\n - {STREAM_FILE}\n - {PULSE_FILE}\n - {CAL_FILE}")


if __name__ == "__main__":
    main()