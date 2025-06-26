import re
import matplotlib.pyplot as plt
import numpy as np

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

def process_file(file_path, target_node=8):
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
    
    return times_batch, rx_batch

def draw_comparison_plot(data_pairs, labels, colors=None):
    """绘制多条时序数据对比图（支持不同长度序列）"""
    plt.figure(figsize=(12, 6))
    
    # 设置默认颜色
    if not colors:
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_pairs)))
    
    for i, (x, y) in enumerate(data_pairs):
        plt.plot(x, y, label=labels[i], color=colors[i], 
                 marker='o', markersize=4, linewidth=2)
    
    plt.title("Throughput Comparison (Complete Data)", fontsize=14)
    plt.xlabel("Time (s)", fontsize=12)
    plt.ylabel("Throughput (Gbps)", fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.legend(loc="best", fontsize=10)
    plt.tight_layout()
    plt.savefig("complete_data_comparison.png", dpi=300)
    plt.close()

if __name__ == "__main__":
    file1 = "/root/ns-3.19/mix/output/hpcc/66515702_out_throughout.txt"
    times1, rx1 = process_file(file1)
    
    file2 = "/root/ns-3.19/mix/output/homa-12000bytes-1000ns/608679822_out_throughout.txt"
    times2, rx2 = process_file(file2)

    file3 = "/root/ns-3.19/mix/output/homa-9000bytes-800ns/99207649_out_throughout.txt"
    times3, rx3 = process_file(file3)

    file4 = "/root/ns-3.19/mix/output/homa-90000bytes-8000ns/928522000_out_throughout.txt"
    times4, rx4 = process_file(file4)    
    
    # 准备绘图数据
    data_pairs = [(times1, rx1), (times2, rx2), (times3, rx3), (times4, rx4)]
    labels = ["HPCC Flow", "Homa Flow-12k-1us", "Homa Flow-9k-0.8us", "Homa Flow-90k-8us"]
    
    # 绘制完整数据对比图
    draw_comparison_plot(data_pairs, labels)
    
    print("绘图完成！完整数据对比图已保存为 'complete_data_comparison.png'")