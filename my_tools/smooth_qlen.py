import re
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import make_interp_spline

def parse_switch_data(file_path, node_id=128):
    """
    解析日志文件，提取指定 switch node 的 time 和 egress_bytes 数值
    返回两个列表：原始时间戳（ns）和出站字节数
    """
    # 一条正则一次性匹配 time 和 egress_bytes
    pattern = re.compile(
        rf"time\s+is\s+(\d+).*?switch\s+node\s+{node_id}.*?egress_bytes\s+is\s+(\d+)",
        re.IGNORECASE
    )

    times_ns = []
    egress = []

    with open(file_path, 'r') as f:
        for line in f:
            if m := pattern.search(line):
                t_ns = int(m.group(1))
                b   = int(m.group(2))
                times_ns.append(t_ns)
                egress.append(b)

    return times_ns, egress

def batch_mean(data, batch_size=10):
    """
    对 data 列表按 batch_size 大小分组（最后一组可以不足 batch_size）
    计算每组的平均值，返回平均值列表
    """
    means = []
    for i in range(0, len(data), batch_size):
        group = data[i: i+batch_size]
        means.append(sum(group) / len(group))
    return means

def smooth_data(x, y, num_points=500):
    """
    对 (x, y) 数据进行三次样条插值平滑
    返回插值后的 (x_smooth, y_smooth)
    """
    x = np.array(x)
    y = np.array(y)
    # 构造均匀的 x
    x_smooth = np.linspace(x.min(), x.max(), num_points)
    spline   = make_interp_spline(x, y, k=3)
    y_smooth = spline(x_smooth)
    return x_smooth, y_smooth

def process_file(file_path,
                 node_id=128,
                 time_offset_ns=None,
                 batch_size=20,
                 do_smooth=True):
    """
    对单个日志文件进行解析、批次平均和可选平滑
    返回：times（s）和 egress_bytes（bytes）的处理后列表
    """
    # 1) 提取原始数据
    times_ns, egress = parse_switch_data(file_path, node_id)

    if not times_ns:
        return [], []

    # 2) 如果没有指定偏移，则以第一个时间戳为 0
    if time_offset_ns is None:
        time_offset_ns = times_ns[0]

    # 转换为秒
    times_s = [(t - time_offset_ns) / 1e6 for t in times_ns]

    # 3) 批次平均
    times_b = batch_mean(times_s, batch_size)
    bytes_b = batch_mean(egress, batch_size)

    # 4) 平滑
    if do_smooth and len(times_b) > 3:
        times_b, bytes_b = smooth_data(times_b, bytes_b)

    return times_b, bytes_b

def draw_comparison_plot(data_pairs, labels, colors=None, out_png="egress_comparison.png"):
    """
    绘制多条曲线对比图
    data_pairs: [(x1, y1), (x2, y2), ...]
    labels:     ["label1", "label2", ...]
    """
    plt.figure(figsize=(10, 6))
    if colors is None:
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_pairs)))

    plt.style.use('seaborn-v0_8-whitegrid')

    for i, ((x, y), label) in enumerate(zip(data_pairs, labels)):
        plt.plot(x, y,
                 label=label,
                 color=colors[i],
                 linewidth=2.0,
                 alpha=0.8)

    plt.title("Switch Node Egress Bytes Over Time", fontsize=16)
    plt.xlabel("Time (ms)", fontsize=14)
    plt.ylabel("Egress Bytes", fontsize=14)
    plt.legend(loc="best", fontsize=12, framealpha=0.9)
    plt.grid(linestyle='--', alpha=0.5)
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.tight_layout()
    plt.savefig(out_png, dpi=300)
    plt.close()
    print(f"Saved plot to {out_png}")

if __name__ == "__main__":
    file_hpcc = "/root/ns-3.19/mix/output/hpcc/66515702_out_qlen.txt"
    file_1000init = "/root/ns-3.19/mix/output/1000init/910270102_out_qlen.txt"
    file_5000init = "/root/ns-3.19/mix/output/5000init/221312662_out_qlen.txt"
    file_10000init = "/root/ns-3.19/mix/output/10000init/887204942_out_qlen.txt"
    file_50000init = "/root/ns-3.19/mix/output/50000init/668301017_out_qlen.txt"

    # 处理文件
    times_hpcc, byte_hpcc = process_file(file_hpcc, node_id=128, batch_size=10, do_smooth=True)
    times_1000init, byte_1000init = process_file(file_1000init, node_id=128, batch_size=10, do_smooth=True)
    times_5000init, byte_5000init = process_file(file_5000init, node_id=128, batch_size=10, do_smooth=True)
    times_10000init, byte_10000init = process_file(file_10000init, node_id=128, batch_size=10, do_smooth=True)
    times_50000init, byte_50000init = process_file(file_50000init, node_id=128, batch_size=10, do_smooth=True)

    # 绘图
    # data_pairs = [(times_hpcc, byte_hpcc), (times_5000init, byte_5000init), (times_10000init, byte_10000init), (times_50000init, byte_50000init)]
    # labels = ["hpcc", "Homa-init-5k", "Homa-init-10k", "Homa-init-50k"]
    data_pairs = [(times_1000init, byte_1000init), (times_5000init, byte_5000init), (times_10000init, byte_10000init), (times_50000init, byte_50000init)]
    labels = ["Homa-init-1k", "Homa-init-5k", "Homa-init-10k", "Homa-init-50k"]

    draw_comparison_plot(data_pairs, labels, out_png="egress_compare.png")
