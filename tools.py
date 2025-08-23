# 指标与功能
# 1. 可视化 qlens、接收/发送带宽、hpcc下的qp_rate速率。
# 2. 支持对多个节点或多个Flow进行对比，生成对比图。
# 3. 检查并防止同时指定多个节点和多个Flow。
# 4. (功能待实现) 可以进行 tab 自动补全 flow

import argparse
import re
import matplotlib.pyplot as plt
import numpy as np
from collections import defaultdict

def batch_mean(data, batch_size):
    """计算数据的分批平均值。"""
    if not data:
        return []
    batch_means = []
    for i in range(0, len(data), batch_size):
        group = data[i:i+batch_size]
        batch_means.append(sum(group) / len(group))
    return batch_means

# =======================================
#            bandwidth(tx/rx)
# =======================================

def parse_bandwidth_data(file_path):
    results = {}
    current_timestamp = None
    current_data = {}
    has_data = False

    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if timestamp_match := re.search(r"FlowMonitor @ (\d+) ns", line):
                if current_timestamp and has_data:
                    results[current_timestamp] = current_data
                current_timestamp = timestamp_match.group(1)
                current_data = {}
                has_data = False
                continue
            if data_match := re.search(r"^(\d+)\s+Tx=([\d.]+) Gbps\s+Rx=([\d.]+) Gbps", line):
                has_data = True
                node_id, tx_val, rx_val = data_match.groups()
                current_data[node_id] = {"Tx": tx_val, "Rx": rx_val}
    if current_timestamp and has_data:
        results[current_timestamp] = current_data
    return results

def process_bandwidth_file(file_path, node_id, batch_size):
    results = parse_bandwidth_data(file_path)
    raw_times, raw_tx, raw_rx = [], [], []
    for ts, nodes in results.items():
        if str(node_id) in nodes:
            raw_times.append(float(int(ts) - 2000000000) / 1e6)
            raw_tx.append(float(nodes[str(node_id)]['Tx']))
            raw_rx.append(float(nodes[str(node_id)]['Rx']))
    times_batch = [round(num, 4) for num in batch_mean(raw_times, batch_size)]
    tx_batch = [round(num, 4) for num in batch_mean(raw_tx, batch_size)]
    rx_batch = [round(num, 4) for num in batch_mean(raw_rx, batch_size)]
    return times_batch, tx_batch, rx_batch

def draw_bandwidth(data_pairs, labels, colors=None):
    plt.figure(figsize=(12, 6))
    if not colors:
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_pairs)))
    plt.style.use('seaborn-v0_8-whitegrid')
    for i, (x, y) in enumerate(data_pairs):
        plt.plot(x, y, label=labels[i], color=colors[i], linewidth=1, alpha=0.8)
    plt.title("Bandwidth Comparison", fontsize=16, fontweight='bold')
    plt.xlabel("Time (ms)", fontsize=14)
    plt.ylabel("Bandwidth (Gbps)", fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.6, color='gray')
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.legend(loc='upper right', frameon=True, fontsize=10)
    plt.tight_layout()
    plt.savefig("./my_pic/bandwidth.png", dpi=300, bbox_inches='tight')
    plt.close()

# =======================================
#                  qlen
# =======================================

def parse_switch_data(file_path, node_id):
    """
    解析指定switch node的数据，并按端口号对数据进行分组。
    返回一个字典，键为端口号，值为包含时间和字节数列表的字典。
    """
    pattern = re.compile(
        rf"time\s+is\s+(\d+).*?switch\s+node\s+{node_id}\b.*?port\s+num\s+is\s+(\d+).*?egress_bytes\s+is\s+(\d+)",
        re.IGNORECASE
    )
    port_data = defaultdict(lambda: {'times': [], 'bytes': []})
    try:
        with open(file_path, 'r') as f:
            for line in f:
                if m := pattern.search(line):
                    t_ns, port, b = map(int, m.groups())
                    port_data[port]['times'].append(t_ns)
                    port_data[port]['bytes'].append(b)
    except FileNotFoundError:
        print(f"错误: qlen文件未找到 {file_path}")
    return port_data

def process_qlen_file(file_path, node_id, time_offset_ns=None, batch_size=5):
    """
    处理指定节点的所有端口数据，为绘图准备数据对和标签。
    """
    port_data = parse_switch_data(file_path, node_id)
    if not port_data:
        return [], []

    all_first_times = [data['times'][0] for port, data in port_data.items() if data['times']]
    if not all_first_times:
        return [], []
    
    # 使用所有端口中最早的时间戳作为全局时间偏移
    time_offset_ns = min(all_first_times)

    data_pairs, labels = [], []
    # 按端口号排序，确保绘图顺序一致
    for port, data in sorted(port_data.items()):
        times_ms = [(t - time_offset_ns) / 1e6 for t in data['times']]
        egress_bytes = data['bytes']
        times_batch = batch_mean(times_ms, batch_size)
        bytes_batch = batch_mean(egress_bytes, batch_size)
        data_pairs.append((times_batch, bytes_batch))
        labels.append(f"Port {port}")
    return data_pairs, labels

def draw_qlen(data_pairs, labels, colors=None, title="Qlen Comparison"):
    """根据提供的数据对和标签绘制qlen图。"""
    plt.figure(figsize=(12, 6))
    if not colors:
        colors = plt.cm.get_cmap('tab10', max(10, len(data_pairs)))
    plt.style.use('seaborn-v0_8-whitegrid')
    for i, (x, y) in enumerate(data_pairs):
        plt.plot(x, y, label=labels[i], color=colors(i), linewidth=2, alpha=0.9)
    plt.title(title, fontsize=16, fontweight='bold')
    plt.xlabel("Time (ms)", fontsize=14)
    plt.ylabel("Egress Bytes (qlen)", fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.6, color='gray')
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.legend(loc='upper right', frameon=True, fontsize=10)
    plt.tight_layout()
    plt.savefig("./my_pic/qlen.png", dpi=300, bbox_inches='tight')
    plt.close()

# =======================================
#                 hprate
# =======================================

def parse_rdma_log_line(line):
    pattern = r'^\[RdmaEgressQueue::GetNextQindex\]\s+(.+)$'
    match = re.match(pattern, line)
    if not match: return None
    variables_part = match.group(1)
    var_pattern = r'(\w+):\s*([+\-]?\d+(?:\.\d+)?(?:[a-zA-Z]+)?)'
    variables = re.findall(var_pattern, variables_part)
    result = {}
    for var_name, var_value in variables:
        try:
            if '.' in var_value and not var_value.endswith(('ns', 'Gbps')): result[var_name] = float(var_value.lstrip('+'))
            elif var_value.isdigit() or (var_value.startswith(('+', '-')) and var_value[1:].isdigit()): result[var_name] = int(var_value.lstrip('+'))
            else: result[var_name] = var_value.lstrip('+')
        except ValueError: result[var_name] = var_value.lstrip('+')
    return result

def parse_rdma_log_file(filename):
    results = []
    try:
        with open(filename, 'r', encoding='utf-8') as file:
            for line_num, line in enumerate(file, 1):
                line = line.strip()
                if line.startswith('[RdmaEgressQueue::GetNextQindex]'):
                    if parsed := parse_rdma_log_line(line):
                        results.append({'line_number': line_num, 'variables': parsed})
    except FileNotFoundError:
        print(f"文件 {filename} 未找到")
    except Exception as e:
        print(f"读取文件时出错: {e}")
    return results

def draw_hprate(time, hpcc_u, hpcc_rate, batch_size):
    time_batch, hpcc_u_batch, hpcc_rate_batch = batch_mean(time, batch_size), batch_mean(hpcc_u, batch_size), batch_mean(hpcc_rate, batch_size)
    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(10, 8))
    fig.suptitle('hpcc_u vs hpcc_rate', fontsize=16, fontweight='bold')
    ax1.plot(time_batch, hpcc_u_batch, color='blue', label='hpcc_u')
    ax1.set(xlabel='Time (ms)', ylabel='u')
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend()
    ax2.plot(time_batch, hpcc_rate_batch, color='red', label='hpcc_rate')
    ax2.set(xlabel='Time (ms)', ylabel='rate (Gbps)')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()
    plt.tight_layout(pad=1)
    plt.savefig("./my_pic/hprate.png", dpi=300, bbox_inches='tight')
    plt.close()

# =======================================
#               grantbytes
# =======================================

def draw_grantbytes(time, hpcc_gBytes, homa_gBytes, batch_size):
    time_batch, hpcc_gBytes_batch, homa_gBytes_batch = batch_mean(time, batch_size), batch_mean(hpcc_gBytes, batch_size), batch_mean(homa_gBytes, batch_size)
    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(10, 8))
    fig.suptitle('hpcc vs homa grant bytes', fontsize=16, fontweight='bold')
    ax1.plot(time_batch, hpcc_gBytes_batch, color='blue', label='hpcc')
    ax1.set(xlabel='Time (ms)', ylabel='hpcc grant bytes')
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend()
    ax2.plot(time_batch, homa_gBytes_batch, color='red', label='homa')
    ax2.set(xlabel='Time (ms)', ylabel='homa grant bytes')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()
    plt.tight_layout(pad=1)
    plt.savefig("./my_pic/grantbytes.png", dpi=300, bbox_inches='tight')
    plt.close()

# =======================================
#                 main
# =======================================

BANDWIDTH_BATCH_SIZE = 100
QLEN_BATCH_SIZE = 10

def main():
    parser = argparse.ArgumentParser(description="A tool for plotting network simulation data.")
    parser.add_argument("-m", dest="mode", required=True, choices=["tx", "rx", "qlen", "hprate", "grantbytes"], help="Metric to plot (tx, rx, qlen, hprate, grantbytes)")
    parser.add_argument("-n", dest="node", nargs='+', type=int, required=True, help="One or more node IDs")
    parser.add_argument("-f", dest="flow", nargs='+', required=True, help="One or more flow identifiers (used for file paths)")
    args = parser.parse_args()

    if len(args.node) > 1 and len(args.flow) > 1:
        parser.error("参数 -n 和 -f 不能同时包含多个值")

    m_value = args.mode
    n_values = args.node
    f_values = args.flow

    # =======================================
    #           一条流，多个节点对比
    # =======================================
    if len(n_values) > 1:
        flow = f_values[0]
        all_data_pairs, all_labels = [], []

        if m_value in ["tx", "rx"]:
            for node in n_values:
                file = f"/root/ns-3.19/mix/output/{flow}/{flow}_out_throughout.txt"
                times, tx, rx = process_bandwidth_file(file, node, BANDWIDTH_BATCH_SIZE)
                all_data_pairs.append((times, tx if m_value == "tx" else rx))
                all_labels.append(f"{flow}-node{node}")
            draw_bandwidth(all_data_pairs, all_labels)

        elif m_value == "qlen":
            file = f"/root/ns-3.19/mix/output/{flow}/{flow}_out_qlen.txt"
            for node in n_values:
                # 获取该节点所有端口的数据
                data_pairs_node, labels_node = process_qlen_file(file, node, QLEN_BATCH_SIZE)
                all_data_pairs.extend(data_pairs_node)
                # 为标签添加节点信息前缀，如 "Node 11 - Port 6"
                all_labels.extend([f"Node {node} - {lbl}" for lbl in labels_node])
            draw_qlen(all_data_pairs, all_labels, title=f"Qlen Comparison for Flow {flow}")
        else:
            print("此模式下不支持多节点对比。")

    # =======================================
    #           多条流，同一节点对比
    # =======================================
    elif len(f_values) > 1:
        node = n_values[0]
        all_data_pairs, all_labels = [], []

        if m_value in ["tx", "rx"]:
            for flow in f_values:
                file = f"/root/ns-3.19/mix/output/{flow}/{flow}_out_throughout.txt"
                times, tx, rx = process_bandwidth_file(file, node, BANDWIDTH_BATCH_SIZE)
                all_data_pairs.append((times, tx if m_value == "tx" else rx))
                all_labels.append(f"{flow}-node{node}")
            draw_bandwidth(all_data_pairs, all_labels)

        elif m_value == "qlen":
            for flow in f_values:
                file = f"/root/ns-3.19/mix/output/{flow}/{flow}_out_qlen.txt"
                data_pairs_flow, labels_flow = process_qlen_file(file, node, QLEN_BATCH_SIZE)
                all_data_pairs.extend(data_pairs_flow)
                all_labels.extend([f"Flow {flow} - {lbl}" for lbl in labels_flow])
            draw_qlen(all_data_pairs, all_labels, title=f"Qlen Comparison on Node {node}")
        else:
            print("此模式下不支持多Flow对比。")

    # =======================================
    #           一条流，单一节点画图
    # =======================================
    else:
        node = n_values[0]
        flow = f_values[0]

        if m_value in ["tx", "rx"]:
            file = f"/root/ns-3.19/mix/output/{flow}/{flow}_out_throughout.txt"
            times, tx, rx = process_bandwidth_file(file, node, BANDWIDTH_BATCH_SIZE)
            data = (times, tx if m_value == "tx" else rx)
            label = f"{flow}-node{node}"
            draw_bandwidth([data], [label])

        elif m_value == "qlen":
            file = f"/root/ns-3.19/mix/output/{flow}/{flow}_out_qlen.txt"
            # 这是您最核心的场景
            data_pairs, labels = process_qlen_file(file, node, QLEN_BATCH_SIZE)
            title = f"Qlen for Switch Node {node} (Flow: {flow})"
            draw_qlen(data_pairs, labels, title=title)
        
        elif m_value == "hprate":
            file = f"/root/ns-3.19/mix/output/{flow}/config.log"
            results = parse_rdma_log_file(file)
            time, hpcc_u, hpcc_rate = [], [], []
            for item in results:
                if node == int(item['variables']['node']):
                    time.append((float(int(item['variables']['time']) - 2000000000)) / 1e6)
                    hpcc_u.append(float(item['variables']['u']))
                    hpcc_rate.append(float(item['variables']['hp_rate']))
            draw_hprate(time, hpcc_u, hpcc_rate, 1)

        elif m_value == "grantbytes":
            file = f"/root/ns-3.19/mix/output/{flow}/config.log"
            results = parse_rdma_log_file(file)
            time, hpcc_gBytes, homa_gBytes = [], [], []
            for item in results:
                if node == int(item['variables']['node']):
                    time.append((float(int(item['variables']['time']) - 2000000000)) / 1e6)
                    hpcc_gBytes.append(float(item['variables']['hp_gBytes']))
                    homa_gBytes.append(float(item['variables']['homa_gBytes']))
            draw_grantbytes(time, hpcc_gBytes, homa_gBytes, 10)

if __name__ == "__main__":
    main()