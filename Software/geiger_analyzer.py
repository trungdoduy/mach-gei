import glob
import os
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats

# ================= CẤU HÌNH PHÂN TÍCH =================
DATA_DIR = "geiger_data"
REPORT_DIR = "ket_qua_bao_cao"
CHANNEL = "out2"            # Chọn 'out2' (xung chuẩn hóa NE555) hoặc 'out1' (xung thô)
DEFAULT_WINDOW_SEC = 60     # Cửa sổ chuẩn (60s = 1 phút) cho TN2, TN4, TN5, TN6
# ======================================================

os.makedirs(REPORT_DIR, exist_ok=True)


def get_latest_file(pattern):
    files = sorted(glob.glob(os.path.join(DATA_DIR, pattern)))
    return files[-1] if files else None


def slice_windows(df_stream, window_sec, col_total):
    """Chia dữ liệu 1s thành các cửa sổ đo không chồng lấp theo từng vị trí."""
    records = []
    for loc, group in df_stream.groupby("location", sort=False):
        group = group.reset_index(drop=True)
        n_blocks = (len(group) - 1) // window_sec
        for i in range(n_blocks):
            idx_start = i * window_sec
            idx_end = (i + 1) * window_sec
            n_counts = group.loc[idx_end, col_total] - group.loc[idx_start, col_total]
            t_min = window_sec / 60.0
            cpm = n_counts / t_min
            records.append({
                "sample_id": len(records) + 1,
                "timestamp": group.loc[idx_end, "timestamp_iso"],
                "location": loc,
                "window_s": window_sec,
                "N_counts": int(n_counts),
                "CPM": cpm
            })
    return pd.DataFrame(records)


def analyze_all():
    stream_path = get_latest_file("stream_1s_*.csv")
    pulse_path = get_latest_file("raw_pulses_*.csv")
    cal_path = get_latest_file("tn3_calibration_*.csv")

    if not stream_path:
        print("[LỖI] Không tìm thấy file stream_1s_*.csv trong thư mục geiger_data/")
        return

    df_stream = pd.read_csv(stream_path)
    col_total = f"total_{CHANNEL}"

    print("=" * 65)
    print("BÁO CÁO PHÂN TÍCH DỮ LIỆU THÍ NGHIỆM GEIGER-MÜLLER")
    print(f"Nguồn dữ liệu: {os.path.basename(stream_path)} | Kênh phân tích: {CHANNEL}")
    print("=" * 65)

    # ---------------------------------------------------------
    # 1. TN1: KIỂM TRA PHẦN CỨNG & SO SÁNH OUT1 vs OUT2
    # ---------------------------------------------------------
    total_1 = df_stream["total_out1"].iloc[-1] - df_stream["total_out1"].iloc[0]
    total_2 = df_stream["total_out2"].iloc[-1] - df_stream["total_out2"].iloc[0]
    total_time_s = len(df_stream) - 1
    print("\n[TN1] KIỂM TRA PHẦN CỨNG & TÍN HIỆU XUNG:")
    print(f" - Tổng thời gian thu thập : {total_time_s} s ({total_time_s/60:.2f} phút)")
    print(f" - Tổng xung out1 (thô)   : {total_1} counts (~{total_1/(total_time_s/60):.2f} CPM)")
    print(f" - Tổng xung out2 (IC 555): {total_2} counts (~{total_2/(total_time_s/60):.2f} CPM)")
    if total_1 > 0:
        diff_pct = abs(total_1 - total_2) / total_1 * 100
        print(f" - Độ lệch đếm out1/out2  : {diff_pct:.2f}% (chênh lệch phản ánh khả năng lọc dội xung của IC 555)")

    if pulse_path and os.path.exists(pulse_path):
        df_pulse = pd.read_csv(pulse_path)
        dt_ms = df_pulse["esp_ms"].diff().dropna()
        if len(dt_ms) > 0:
            print(f" - Khoảng cách 2 xung liên tiếp nhỏ nhất: {dt_ms.min():.0f} ms | Trung bình: {dt_ms.mean():.1f} ms")

    # ---------------------------------------------------------
    # 2. TN3 & MỤC 15.2: HỆ SỐ QUY ĐỔI THỰC NGHIỆM CF & HỒI QUY
    # ---------------------------------------------------------
    cf_avg = 0.0065  # Giá trị dự phòng nếu chưa đo TN3
    if cal_path and os.path.exists(cal_path):
        df_cal = pd.read_csv(cal_path)
        if len(df_cal) >= 2:
            cpm_col = f"cpm_{CHANNEL}"
            df_cal = df_cal[df_cal[cpm_col] > 0].copy()
            df_cal["CF_i"] = df_cal["H_ref_uSv_h"] / df_cal[cpm_col]
            cf_avg = df_cal["CF_i"].mean()

            # Ước lượng theo hệ số trung bình CF_avg
            df_cal["H_est_uSv_h"] = df_cal[cpm_col] * cf_avg
            df_cal["Error_pct"] = (
                np.abs(df_cal["H_est_uSv_h"] - df_cal["H_ref_uSv_h"]) / df_cal["H_ref_uSv_h"] * 100.0
            )
            rmse = np.sqrt(np.mean((df_cal["H_est_uSv_h"] - df_cal["H_ref_uSv_h"]) ** 2))

            # Hồi quy tuyến tính: H_ref = a * CPM + b
            slope, intercept, r_value, p_value, std_err = stats.linregress(
                df_cal[cpm_col], df_cal["H_ref_uSv_h"]
            )
            r_squared = r_value ** 2

            print("\n[TN3 & MỤC 15.2] HIỆU CHUẨN THỰC NGHIỆM VỚI THIẾT BỊ THƯƠNG MẠI:")
            print(f" - Số cặp mẫu đo (n)      : {len(df_cal)}")
            print(f" - Hệ số CF trung bình    : {cf_avg:.6f} µSv/h per CPM")
            print(f" - Phương trình hồi quy   : H_ref = {slope:.6f} * CPM + {intercept:.6f}")
            print(f" - Hệ số xác định R²      : {r_squared:.4f}")
            print(f" - Sai số trung bình      : {df_cal['Error_pct'].mean():.2f}% (Max: {df_cal['Error_pct'].max():.2f}%)")
            print(f" - RMSE                   : {rmse:.5f} µSv/h")

            df_cal.to_csv(os.path.join(REPORT_DIR, "Bang_TN3_HieuChuan.csv"), index=False)

            # Vẽ Hình 4: Scatter CPM vs H_ref
            plt.figure(figsize=(7, 5))
            plt.scatter(df_cal[cpm_col], df_cal["H_ref_uSv_h"], color="#1f77b4", label="Dữ liệu thực nghiệm")
            x_line = np.linspace(df_cal[cpm_col].min() * 0.9, df_cal[cpm_col].max() * 1.1, 100)
            plt.plot(x_line, slope * x_line + intercept, "r--",
                     label=f"Hồi quy: H = {slope:.5f}·CPM + {intercept:.4f} (R²={r_squared:.3f})")
            plt.plot(x_line, cf_avg * x_line, "g:",
                     label=f"Tỷ lệ CF_avg: H = {cf_avg:.5f}·CPM")
            plt.xlabel("Số đếm trên phút - CPM (counts/min)")
            plt.ylabel("Suất liều tham chiếu H_ref (µSv/h)")
            plt.title("Hình 4. Quan hệ giữa CPM tự phát triển và H_ref thương mại")
            plt.grid(True, linestyle="--", alpha=0.5)
            plt.legend()
            plt.tight_layout()
            plt.savefig(os.path.join(REPORT_DIR, "Hinh4_TuongQuan_CPM_Href.png"), dpi=300)
            plt.close()

    # ---------------------------------------------------------
    # 3. TN2, TN4, TN5 & MỤC 15.1: THỐNG KÊ THEO CỬA SỔ 60 GIÂY
    # ---------------------------------------------------------
    df_60s = slice_windows(df_stream, DEFAULT_WINDOW_SEC, col_total)
    if len(df_60s) > 0:
        df_60s["H_est_uSv_h"] = df_60s["CPM"] * cf_avg
        mean_cpm = df_60s["CPM"].mean()
        sd_cpm = df_60s["CPM"].std(ddof=1) if len(df_60s) > 1 else 0.0
        cv_cpm = (sd_cpm / mean_cpm * 100.0) if mean_cpm > 0 else 0.0

        print("\n[TN2 / TN4 / TN5 & MỤC 15.1] TỔNG HỢP KẾT QUẢ ĐO (CỬA SỔ 60s):")
        print(f" - Số mẫu (chu kỳ 1 phút) : {len(df_60s)}")
        print(f" - CPM trung bình (Mean)  : {mean_cpm:.2f} counts/min")
        print(f" - Độ lệch chuẩn (SD)     : {sd_cpm:.2f} counts/min")
        print(f" - Hệ số biến thiên (CV)  : {cv_cpm:.2f} %")
        print(f" - CPM Min / Max          : {df_60s['CPM'].min():.1f} / {df_60s['CPM'].max():.1f} counts/min")
        print(f" - H_est trung bình       : {df_60s['H_est_uSv_h'].mean():.4f} µSv/h")

        # Xuất bảng Phụ lục B
        df_60s.to_csv(os.path.join(REPORT_DIR, "PhuLucB_DuLieuTho_60s.csv"), index=False)

        # Vẽ Hình 3 & Hình 5: CPM và H_est theo thời gian
        fig, ax1 = plt.subplots(figsize=(9, 4.5))
        ax1.plot(df_60s["sample_id"], df_60s["CPM"], marker="o", color="#1f77b4", label="CPM")
        ax1.axhline(mean_cpm, color="red", linestyle="--", label=f"Mean = {mean_cpm:.1f} CPM")
        ax1.set_xlabel("Chu kỳ đo (phút)")
        ax1.set_ylabel("CPM (counts/min)", color="#1f77b4")
        ax1.tick_params(axis="y", labelcolor="#1f77b4")
        ax1.grid(True, linestyle="--", alpha=0.5)

        ax2 = ax1.twinx()
        ax2.plot(df_60s["sample_id"], df_60s["H_est_uSv_h"], linestyle=":", color="#ff7f0e", alpha=0.8)
        ax2.set_ylabel("Suất liều ước lượng H_est (µSv/h)", color="#ff7f0e")
        ax2.tick_params(axis="y", labelcolor="#ff7f0e")

        plt.title("Hình 3 & 5. Diễn biến CPM và suất liều ước lượng H_est theo thời gian")
        fig.legend(loc="upper right", bbox_to_anchor=(0.88, 0.88))
        plt.tight_layout()
        plt.savefig(os.path.join(REPORT_DIR, "Hinh3_5_CPM_TheoThoiGian.png"), dpi=300)
        plt.close()

        # ---------------------------------------------------------
        # 4. TN6: SO SÁNH THEO VỊ TRÍ ĐO
        # ---------------------------------------------------------
        loc_stats = df_60s.groupby("location").agg(
            So_mau=("CPM", "count"),
            Mean_CPM=("CPM", "mean"),
            SD_CPM=("CPM", "std"),
            Mean_H_est=("H_est_uSv_h", "mean")
        ).reset_index()
        loc_stats["SD_CPM"] = loc_stats["SD_CPM"].fillna(0.0)
        loc_stats["CV_pct"] = np.where(loc_stats["Mean_CPM"] > 0,
                                       loc_stats["SD_CPM"] / loc_stats["Mean_CPM"] * 100.0, 0.0)

        print("\n[TN6] SO SÁNH BỨC XẠ NỀN THEO VỊ TRÍ:")
        print(loc_stats.to_string(index=False))
        loc_stats.to_csv(os.path.join(REPORT_DIR, "Bang_TN6_ViTri.csv"), index=False)

        if len(loc_stats) >= 1:
            plt.figure(figsize=(8, 4.5))
            plt.bar(loc_stats["location"], loc_stats["Mean_CPM"], yerr=loc_stats["SD_CPM"],
                    capsize=5, color="#2ca02c", alpha=0.85, edgecolor="black")
            plt.ylabel("CPM trung bình (counts/min)")
            plt.title("Hình 7. So sánh CPM trung bình tại các vị trí đo trong nhà")
            plt.xticks(rotation=15)
            plt.grid(axis="y", linestyle="--", alpha=0.5)
            plt.tight_layout()
            plt.savefig(os.path.join(REPORT_DIR, "Hinh7_SoSanh_ViTri.png"), dpi=300)
            plt.close()

    # ---------------------------------------------------------
    # 5. TN7: ẢNH HƯỞNG CỦA THỜI GIAN LẤY MẪU (10s, 30s, 60s, 300s)
    # ---------------------------------------------------------
    windows = [10, 30, 60, 300]
    tn7_rows = []
    for w in windows:
        df_w = slice_windows(df_stream, w, col_total)
        if len(df_w) >= 2:
            m = df_w["CPM"].mean()
            s = df_w["CPM"].std(ddof=1)
            cv = (s / m * 100.0) if m > 0 else 0.0
            tn7_rows.append({
                "Cua_so_s": w,
                "So_lan_lap": len(df_w),
                "Mean_CPM": round(m, 2),
                "SD_CPM": round(s, 2),
                "CV_pct": round(cv, 2),
                "Mean_H_est_uSv_h": round(m * cf_avg, 4)
            })

    if tn7_rows:
        df_tn7 = pd.DataFrame(tn7_rows)
        print("\n[TN7] ẢNH HƯỞNG CỦA THỜI GIAN LẤY MẪU ĐẾN ĐỘ DAO ĐỘNG CPM:")
        print(df_tn7.to_string(index=False))
        df_tn7.to_csv(os.path.join(REPORT_DIR, "Bang_TN7_ThoiGianLayMau.csv"), index=False)

        # Vẽ Hình 8: Độ dao động CV (%) và SD theo cửa sổ thời gian
        fig, ax1 = plt.subplots(figsize=(7.5, 4.5))
        x_labels = [f"{w}s" for w in df_tn7["Cua_so_s"]]
        ax1.plot(x_labels, df_tn7["CV_pct"], marker="s", color="#d62728", linewidth=2, label="CV (%)")
        ax1.set_xlabel("Cửa sổ thời gian lấy mẫu (T)")
        ax1.set_ylabel("Hệ số biến thiên CV (%)", color="#d62728")
        ax1.tick_params(axis="y", labelcolor="#d62728")
        ax1.grid(True, linestyle="--", alpha=0.5)

        ax2 = ax1.twinx()
        ax2.bar(x_labels, df_tn7["SD_CPM"], alpha=0.25, color="#1f77b4", label="SD CPM")
        ax2.set_ylabel("Độ lệch chuẩn SD (counts/min)", color="#1f77b4")
        ax2.tick_params(axis="y", labelcolor="#1f77b4")

        plt.title("Hình 8. Ảnh hưởng của thời gian lấy mẫu đến độ dao động CPM")
        plt.tight_layout()
        plt.savefig(os.path.join(REPORT_DIR, "Hinh8_ThoiGianLayMau.png"), dpi=300)
        plt.close()

    print(f"\n[HOÀN TẤT] Toàn bộ bảng số liệu CSV và đồ thị PNG đã xuất vào thư mục '{REPORT_DIR}/'.")


if __name__ == "__main__":
    analyze_all()