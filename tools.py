# 指标与功能
# 1. qlens、接收/发送带宽、hpcc下的qp_rate速率。
# 2. 携带了多个节点号或者多个Flow，画成对比图。
# 3. 检查number和node不同时为多个。
# 4. 可以进行 tab 自动补全 flow

# 改一下注释，要进一步简化。

# 示例：python3 tools.py -m qlen/tx/rx/qrate -n 0 1 2 -f number1 number2

import argparse
import re
import matplotlib.pyplot as plt
import numpy as np


def batch_mean(data, batch_size):
    batch_means = []
    for i in range(0, len(data), batch_size):
        group = data[i:i+batch_size]
        batch_means.append(sum(group) / len(group))
    return batch_means

# =======================================
#            bandwidth(tx\rx)
# =======================================

def parse_bandwidth_data(file_path):
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

def process_bandwidth_file(file_path, node_id, batch_size):
    results = parse_bandwidth_data(file_path)
    raw_times = []
    raw_tx = []
    raw_rx = []

    for ts, nodes in results.items():
        for node, data in nodes.items():
            if int(node) == node_id:
                raw_times.append(float(int(ts) - 2000000000) / 1e6)
                raw_tx.append(float(data['Tx']))
                raw_rx.append(float(data['Rx']))

    # 分批平均处理（包含所有数据点）
    times_batch = batch_mean(raw_times, batch_size)
    tx_batch = batch_mean(raw_tx, batch_size)
    rx_batch = batch_mean(raw_rx, batch_size)

    times_batch = [round(num, 4) for num in times_batch]
    tx_batch = [round(num, 4) for num in tx_batch]
    rx_batch = [round(num, 4) for num in rx_batch]

    return times_batch, tx_batch, rx_batch

def draw_bandwidth(data_pairs, labels, colors=None):
    plt.figure(figsize=(12, 6))

    if not colors:
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_pairs)))

    plt.style.use('seaborn-v0_8-whitegrid')
    for i, (x, y) in enumerate(data_pairs):
        plt.plot(x, y, label=labels[i], color=colors[i], linewidth=2.5, alpha=0.8)

    plt.title("Bandwidth Comparison", fontsize=16, fontweight='bold')
    plt.xlabel("Time (ms)", fontsize=14)
    plt.ylabel("Bandwidth (Gbps)", fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.6, color='gray')
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.legend(loc='upper right', bbox_to_anchor=(1.1, 1), frameon=True, framealpha=0.9, fontsize=8)
    plt.tight_layout()
    plt.savefig("./my_pic/bandwidth.png", dpi=300, bbox_inches='tight')
    plt.close()

# =======================================
#                  qlen
# =======================================

def parse_switch_data(file_path, node_id):
    pattern = re.compile(
        rf"time\s+is\s+(\d+).*?switch\s+node\s+{node_id}\b.*?egress_bytes\s+is\s+(\d+)",
        re.IGNORECASE
    )

    times_ns = []
    egress = []

    with open(file_path, 'r') as f:
        for line in f:
            if m := pattern.search(line):
                t_ns = int(m.group(1))
                b = int(m.group(2))
                times_ns.append(t_ns)
                egress.append(b)

    return times_ns, egress


def process_qlen_file(file_path, node_id, time_offset_ns=None, batch_size=5):
    times_ns, egress = parse_switch_data(file_path, node_id)

    if not times_ns:
        return [], []

    if time_offset_ns is None:
        time_offset_ns = times_ns[0]

    times = [(t - time_offset_ns) / 1e6 for t in times_ns]

    times_batch = batch_mean(times, batch_size)
    bytes_batch = batch_mean(egress, batch_size)

    return times_batch, bytes_batch

def draw_qlen(data_pairs, labels, colors=None):
    plt.figure(figsize=(12, 6))

    if not colors:
        colors = plt.cm.tab10(np.linspace(0, 1, len(data_pairs)))

    plt.style.use('seaborn-v0_8-whitegrid')
    for i, (x, y) in enumerate(data_pairs):
        plt.plot(x, y, label=labels[i], color=colors[i], linewidth=2.5, alpha=0.8)

    plt.title("QLens Comparison", fontsize=16, fontweight='bold')
    plt.xlabel("Time (ms)", fontsize=14)
    plt.ylabel("Egress Bytes", fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.6, color='gray')
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.legend(loc='upper right', bbox_to_anchor=(1.1, 1), frameon=True, framealpha=0.9, fontsize=8)
    plt.tight_layout()
    plt.savefig("./my_pic/qlen.png", dpi=300, bbox_inches='tight')
    plt.close()

# =======================================
#                 hprate
# =======================================

def parse_rdma_log_line(line):
    pattern = r'^\[RdmaEgressQueue::GetNextQindex\]\s+(.+)$'
    match = re.match(pattern, line)
    
    if not match:
        return None
    
    variables_part = match.group(1)
    
    var_pattern = r'(\w+):\s*([+\-]?\d+(?:\.\d+)?(?:[a-zA-Z]+)?)'
    variables = re.findall(var_pattern, variables_part)
    
    result = {}
    for var_name, var_value in variables:
        try:
            if '.' in var_value and not var_value.endswith(('ns', 'Gbps')):
                result[var_name] = float(var_value.lstrip('+'))
            elif var_value.isdigit() or (var_value.startswith(('+', '-')) and var_value[1:].isdigit()):
                result[var_name] = int(var_value.lstrip('+'))
            else:
                result[var_name] = var_value.lstrip('+')
        except ValueError:
            result[var_name] = var_value.lstrip('+')
    
    return result

def parse_rdma_log_file(filename):
    results = []

    try:
        with open(filename, 'r', encoding='utf-8') as file:
            for line_num, line in enumerate(file, 1):
                line = line.strip()
                if line.startswith('[RdmaEgressQueue::GetNextQindex]'):
                    parsed = parse_rdma_log_line(line)
                    if parsed:
                        results.append({
                            'line_number': line_num,
                            'variables': parsed,
                            'raw_line': line
                        })
    except FileNotFoundError:
        print(f"文件 {filename} 未找到")
        return []
    except Exception as e:
        print(f"读取文件时出错: {e}")
        return []
    
    return results

def draw_hprate(time, hpcc_u, hpcc_rate, batch_size):
    time_batch = batch_mean(time, batch_size)
    hpcc_u_batch = batch_mean(hpcc_u, batch_size)
    hpcc_rate_batch = batch_mean(hpcc_rate, batch_size) 

    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(10, 8))
    fig.suptitle('hpcc_u sv hpcc_rate', fontsize=16, fontweight='bold')

    ax1.plot(time_batch, hpcc_u_batch, color='blue', label='hpcc_u')
    ax1.set_xlabel('Time (ms)')
    ax1.set_ylabel('u')
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)
    ax1.grid(True, linestyle='--', alpha=0.6, color='gray')
    ax1.legend()

    ax2.plot(time_batch, hpcc_rate_batch, color='red', label='hpcc_rate')
    ax2.set_xlabel('Time (ms)')
    ax2.set_ylabel('rate (Gbps)')
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    ax2.grid(True, linestyle='--', alpha=0.6, color='gray')
    ax2.legend()

    plt.tight_layout(pad=1)
    plt.savefig("./my_pic/hprate.png", dpi=300, bbox_inches='tight')

# =======================================
#               grantbytes
# =======================================

def draw_grantbytes(time, hpcc_gBytes, homa_gBytes, batch_size):
    time_batch = batch_mean(time, batch_size)
    hpcc_gBytes_batch = batch_mean(hpcc_gBytes, batch_size)
    homa_gBytes_batch = batch_mean(homa_gBytes, batch_size) 

    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(10, 8))
    fig.suptitle('hpcc sv homa grant bytes', fontsize=16, fontweight='bold')

    ax1.plot(time_batch, hpcc_gBytes_batch, color='blue', label='hpcc')
    ax1.set_xlabel('Time (ms)')
    ax1.set_ylabel('hpcc grant bytes')
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)
    ax1.grid(True, linestyle='--', alpha=0.6, color='gray')
    ax1.legend()

    ax2.plot(time_batch, homa_gBytes_batch, color='red', label='homa')
    ax2.set_xlabel('Time (ms)')
    ax2.set_ylabel('homa grant bytes')
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)
    ax2.grid(True, linestyle='--', alpha=0.6, color='gray')
    ax2.legend()

    plt.tight_layout(pad=1)
    plt.savefig("./my_pic/grantbytes.png", dpi=300, bbox_inches='tight')


# =======================================
#                 main
# =======================================

BANDWIDTH_BATCH_SIZE = 1
QLEN_BATCH_SIZE = 10

def main():
    parser = argparse.ArgumentParser()
    
    parser.add_argument("-m", dest="mode", required=True, help="Single parameter after -m")
    parser.add_argument("-n", dest="node", nargs='+', type=int, required=True, help="One or more integers after -n")
    parser.add_argument("-f", dest="flow", nargs='+', required=True, help="One or more strings after -f")
    
    args = parser.parse_args()
    
    if len(args.node) > 1 and len(args.flow) > 1:
        parser.error("参数 -n 和 -f 不能同时包含多个值")
    
    m_value = args.mode
    n_values = args.node
    f_values = args.flow

    valid_modes = {"tx", "rx", "qlen", "hprate", "grantbytes"}
    if m_value not in valid_modes:
        parser.error("-m: must select from tx/rx/qlen/hprate")

    file = "debug_file"
    batch_size = -1

    # =======================================
    #           一条流，多个节点对比
    # =======================================
    if len(args.node) > 1:

        # --- bandwidth ---
        if m_value == "tx" or m_value == "rx":
            file = "/root/ns-3.19/mix/output/" + str(f_values[0]) + "/" + str(f_values[0]) + "_out_throughout.txt"
        
        # ----- qlen -----
        elif m_value == "qlen":
            file = "/root/ns-3.19/mix/output/" + str(f_values[0]) + "/" + str(f_values[0]) + "_out_qlen.txt"

        target_nodes = [int(node) for node in n_values]
        data_pairs = []
        labels = []

        # --- bandwidth ---
        if m_value == "tx" or m_value == "rx":
            for node in target_nodes:
                times, tx, rx = process_bandwidth_file(file, node_id=node, batch_size=BANDWIDTH_BATCH_SIZE)
                if m_value == "tx":
                    data_pairs.append((times, tx))
                elif m_value == "rx":
                    data_pairs.append((times, rx))
                labels.append(str(f_values[0]) + "-node" + str(node))
            draw_bandwidth(data_pairs, labels)
        
        # ----- qlen -----
        elif m_value == "qlen":
            for node in target_nodes:
                times, qlen = process_qlen_file(file, node_id=node, batch_size=QLEN_BATCH_SIZE)
                data_pairs.append((times, qlen))
                labels.append(str(f_values[0]) + "-node" + str(node))
            draw_qlen(data_pairs, labels)
        
        else:
            print("此情况不支持/施工中...")


    # =======================================
    #           多条流，同一节点对比
    # =======================================
    elif len(args.flow) > 1:
        node = int(n_values[0])
        data_pairs = []
        labels = []

        # --- bandwidth ---
        if m_value == "tx" or m_value == "rx":
            for i in range(len(args.flow)):
                file = "/root/ns-3.19/mix/output/" + str(f_values[i]) + "/" + str(f_values[i]) + "_out_throughout.txt"
                times, tx, rx = process_bandwidth_file(file, node_id=node, batch_size=BANDWIDTH_BATCH_SIZE)
                if m_value == "tx":
                    data_pairs.append((times, tx))
                elif m_value == "rx":
                    data_pairs.append((times, rx))
                labels.append(str(f_values[i]))
            draw_bandwidth(data_pairs, labels)

        # ----- qlen -----
        elif m_value == "qlen":
            for i in range(len(args.flow)):
                file = "/root/ns-3.19/mix/output/" + str(f_values[i]) + "/" + str(f_values[i]) + "_out_qlen.txt"
                times, qlen = process_qlen_file(file, node_id=node, batch_size=QLEN_BATCH_SIZE)
                data_pairs.append((times, qlen))
                labels.append(str(f_values[i]) + "-node" + str(node))
            draw_qlen(data_pairs, labels)

        else:
            print("此情况不支持/施工中...")

        
    # =======================================
    #           一条流，单一节点画图
    # =======================================
    else:
        node = int(n_values[0])
        data_pairs = []
        labels = []

        # --- bandwidth ---
        if m_value == "tx" or m_value == "rx":
            file = "/root/ns-3.19/mix/output/" + str(f_values[0]) + "/" + str(f_values[0]) + "_out_throughout.txt"
            times, tx, rx = process_bandwidth_file(file, node_id=node, batch_size=BANDWIDTH_BATCH_SIZE)
            if m_value == "tx":
                data_pairs.append((times, tx))
            elif m_value == "rx":
                data_pairs.append((times, rx))
            labels.append(str(f_values[0]) + "-node" + str(node))
            print(tx)
            draw_bandwidth(data_pairs, labels)

        # ----- qlen -----
        elif m_value == "qlen":
            file = "/root/ns-3.19/mix/output/" + str(f_values[0]) + "/" + str(f_values[0]) + "_out_qlen.txt"
            times, qlen = process_qlen_file(file, node_id=node, batch_size=QLEN_BATCH_SIZE)
            data_pairs.append((times, qlen))
            labels.append(str(f_values[0]) + "-node" + str(node))
            draw_qlen(data_pairs, labels)
        
        # ----- u and HPCC-Rate -----
        elif m_value == "hprate":
            file = "/root/ns-3.19/mix/output/" + str(f_values[0]) + "/" + "config.log"
            results = parse_rdma_log_file(file)
            time = []
            hpcc_u = []
            hpcc_rate = []

            for item in results:
                if (node == int(item['variables']['node'])):
                    time.append((float(int(item['variables']['time']) - 2000000000)) / 1e6)
                    hpcc_u.append(float(item['variables']['u']))
                    hpcc_rate.append(float(item['variables']['hp_rate']))
            draw_hprate(time, hpcc_u, hpcc_rate, 1)

        # ----- grantbytes -----
        elif m_value == "grantbytes":
            file = "/root/ns-3.19/mix/output/" + str(f_values[0]) + "/" + "config.log"
            results = parse_rdma_log_file(file)
            time = []
            hpcc_gBytes = []
            homa_gBytes = []

            for item in results:
                if (node == int(item['variables']['node'])):
                    time.append((float(int(item['variables']['time']) - 2000000000)) / 1e6)
                    hpcc_gBytes.append(float(item['variables']['hp_gBytes']))
                    homa_gBytes.append(float(item['variables']['homa_gBytes']))
            draw_grantbytes(time, hpcc_gBytes, homa_gBytes, 10)

if __name__ == "__main__":
    main()
