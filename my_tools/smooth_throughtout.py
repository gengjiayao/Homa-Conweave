import re
import matplotlib.pyplot as plt
import numpy as np
from scipy.interpolate import make_interp_spline

def parse_flow_data(file_path):
    """解析流量数据文件，返回带时间戳的节点数据字典"""
    results = {}
    current_timestamp = None
    current_data = {}
    has_data = False

    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()

            # 匹配时间戳
            if timestamp_match := re.search(r"FlowMonitor @ (\d+) ns", line):
                if current_timestamp and has_data:
                    results[current_timestamp] = current_data

                current_timestamp = timestamp_match.group(1)
                current_data = {}
                has_data = False
                continue

            # 匹配节点数据（含Tx/Rx）
            if data_match := re.search(r"^(\d+)\s+Tx=([\d.]+) Gbps\s+Rx=([\d.]+) Gbps", line):
                has_data = True
                node_id, tx_val, rx_val = data_match.groups()
                current_data[node_id] = {"Tx": tx_val, "Rx": rx_val}

    # 处理最后一个有效时间戳
    if current_timestamp and has_data:
        results[current_timestamp] = current_data

    return results

def batch_mean(data, batch_size=10):
    """计算数据的批次平均值（包含不足一批的数据）"""
    batch_means = []
    for i in range(0, len(data), batch_size):
        group = data[i:i+batch_size]
        # 计算当前组的平均值，无论是否达到batch_size
        batch_means.append(sum(group) / len(group))
    return batch_means

def smooth_data(x, y, num_points=500):
    """使用三次样条插值平滑数据"""
    # 创建密集插值点
    x_smooth = np.linspace(min(x), max(x), num_points)

    # 生成三次样条插值
    spl = make_interp_spline(x, y, k=3)  # k=3 表示三次样条
    y_smooth = spl(x_smooth)

    return x_smooth, y_smooth

def process_file(file_path, target_node=8, smooth=True):
    """处理单个文件，返回处理后的时序数据（包含所有数据点）"""
    results = parse_flow_data(file_path)

    raw_times = []
    raw_rx = []

    for ts, nodes in results.items():
        for node_id, data in nodes.items():
            if int(node_id) == target_node and data['Rx'] != '0.00':
                # 时间戳转换
                raw_times.append(float(int(ts) - 2000000000) / 1e6)
                raw_rx.append(float(data['Rx']))

    # 分批平均处理（包含所有数据点）
    batch_size = 20
    times_batch = batch_mean(raw_times, batch_size)
    rx_batch = batch_mean(raw_rx, batch_size)

    # 应用平滑处理
    if smooth and len(times_batch) > 3:  # 至少需要4个点才能进行三次样条插值
        times_batch, rx_batch = smooth_data(times_batch, rx_batch)

    return times_batch, rx_batch

def draw_comparison_plot(data_pairs, labels, colors=None):
    """绘制多条时序数据对比图（支持不同长度序列）"""
    plt.figure(figsize=(12, 6))

    # 设置默认颜色
    if not colors:
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_pairs)))

    # 设置更美观的样式 [9,11](@ref)
    plt.style.use('seaborn-v0_8-whitegrid')  # 使用白色网格背景

    for i, (x, y) in enumerate(data_pairs):
        # 绘制平滑曲线，不显示数据点标记
        plt.plot(x, y, label=labels[i], color=colors[i],
                 linewidth=2.5, alpha=0.85)  # 增加线宽和透明度

    plt.title("Throughput Comparison", fontsize=16, fontweight='bold')
    plt.xlabel("Time (ms)", fontsize=14)
    plt.ylabel("Throughput (Gbps)", fontsize=14)

    # 设置网格和边框样式
    plt.grid(True, linestyle='--', alpha=0.6, color='gray')
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)

    # 添加图例并设置位置
    plt.legend(loc="best", fontsize=12, frameon=True, framealpha=0.9)

    # 调整边距
    plt.tight_layout()

    # 保存高质量图片
    plt.savefig("smooth_comparison.png", dpi=300, bbox_inches='tight')
    plt.close()

if __name__ == "__main__":
    file_hpcc = "/root/ns-3.19/mix/output/hpcc/hpcc_out_throughout.txt"
    times_hpcc, rx_hpcc = process_file(file_hpcc)

    file_dcqcn = "/root/ns-3.19/mix/output/dcqcn/dcqcn_out_throughout.txt"
    dcqcn_times, dcqcn_rx = process_file(file_dcqcn)

    file1 = "/root/ns-3.19/mix/output/5000init/5000init_out_throughout.txt"
    times1, rx1 = process_file(file1)

    file2 = "/root/ns-3.19/mix/output/1000init/1000init_out_throughout.txt"
    times2, rx2 = process_file(file2)

    file3 = "/root/ns-3.19/mix/output/10000init/10000init_out_throughout.txt"
    times3, rx3 = process_file(file3)

    file4 = "/root/ns-3.19/mix/output/50000init/50000init_out_throughout.txt"
    times4, rx4 = process_file(file4)

    # 准备绘图数据
    data_pairs = [(times_hpcc, rx_hpcc), (times2, rx2), (times1, rx1), (times3, rx3), (times4, rx4)]
    labels = ["hpcc", "Homa-init-1k", "Homa-init-5k", "Homa-init-10k", "Homa-init-50k"]

    # data_pairs = [(times_hpcc, rx_hpcc), (dcqcn_times, dcqcn_rx), (times1, rx1)]
    # labels = ["hpcc", "dcqcn", "Homa-init-5k"]

    # 绘制完整数据对比图
    draw_comparison_plot(data_pairs, labels)

    print("绘图完成！平滑数据对比图已保存为 'smooth_comparison.png'")
