# coding: utf-8
"""
一个用于可视化网络模拟数据的命令行工具。

主要功能:
1. 可视化多种指标：发送/接收带宽 (tx/rx)、队列长度 (qlen)、HPCC 速率 (hprate) 等。
2. 支持对多个节点或多个流进行对比绘图。
3. 提供 `stream` 模式，用于生成交互式的散点泳道图来可视化数据包发送时序。
4. `stream` 模式下，支持使用 `-n` 参数筛选特定节点相关的流。
"""

import argparse
import os
import re
from collections import defaultdict
from typing import List, Dict, Tuple, Any, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# =============================================================================
# Constants and Configurations
# =============================================================================
OUTPUT_DIR = "./my_pic"
BANDWIDTH_BATCH_SIZE = 100
QLEN_BATCH_SIZE = 10
HPRATE_BATCH_SIZE = 1
GRANTBYTES_BATCH_SIZE = 10
TIMESTAMP_OFFSET = 2000000000  # ns


# =============================================================================
# Helper Functions
# =============================================================================

def batch_mean(data: List[float], batch_size: int) -> List[float]:
    """
    计算数据的分批平均值。

    Args:
        data: 包含数字的列表。
        batch_size: 每个批次的大小。

    Returns:
        一个包含各批次平均值的新列表。
    """
    if not data or batch_size <= 0:
        return data
    return [
        sum(data[i:i + batch_size]) / len(data[i:i + batch_size])
        for i in range(0, len(data), batch_size)
    ]


# =============================================================================
# Bandwidth (tx/rx) Module
# =============================================================================

def parse_bandwidth_data(file_path: str) -> Dict[str, Any]:
    """解析 FlowMonitor 的带宽日志文件。"""
    results = {}
    current_timestamp = None
    current_data = {}
    has_data = False
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
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
    except FileNotFoundError:
        print(f"错误: 带宽文件未找到 {file_path}")
    return results


def process_bandwidth_file(file_path: str, node_id: int, batch_size: int) -> Tuple[List[float], List[float], List[float]]:
    """从解析的数据中提取特定节点的 tx/rx 带宽。"""
    results = parse_bandwidth_data(file_path)
    raw_times, raw_tx, raw_rx = [], [], []
    for ts, nodes in results.items():
        if str(node_id) in nodes:
            raw_times.append((int(ts) - TIMESTAMP_OFFSET) / 1e6)
            raw_tx.append(float(nodes[str(node_id)]['Tx']))
            raw_rx.append(float(nodes[str(node_id)]['Rx']))
    times_batch = [round(num, 4) for num in batch_mean(raw_times, batch_size)]
    tx_batch = [round(num, 4) for num in batch_mean(raw_tx, batch_size)]
    rx_batch = [round(num, 4) for num in batch_mean(raw_rx, batch_size)]
    return times_batch, tx_batch, rx_batch


def draw_bandwidth(data_pairs: List[Tuple[List[float], List[float]]], labels: List[str]):
    """绘制带宽对比图。"""
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.figure(figsize=(12, 6))
    colors = plt.get_cmap('tab10')(np.linspace(0, 1, len(data_pairs)))

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
    plt.savefig(os.path.join(OUTPUT_DIR, "bandwidth.png"), dpi=300, bbox_inches='tight')
    plt.close()
    print(f"带宽图已保存至 {os.path.join(OUTPUT_DIR, 'bandwidth.png')}")


# =============================================================================
# Qlen Module
# =============================================================================

def parse_switch_data(file_path: str, node_id: int) -> Dict[int, Dict[str, List[int]]]:
    """解析交换机节点的队列长度 (qlen) 日志。"""
    pattern = re.compile(
        rf"time\s+is\s+(\d+).*?switch\s+node\s+{node_id}\b.*?port\s+num\s+is\s+(\d+).*?egress_bytes\s+is\s+(\d+)",
        re.IGNORECASE
    )
    port_data = defaultdict(lambda: {'times': [], 'bytes': []})
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                if m := pattern.search(line):
                    t_ns, port, b = map(int, m.groups())
                    port_data[port]['times'].append(t_ns)
                    port_data[port]['bytes'].append(b)
    except FileNotFoundError:
        print(f"错误: qlen文件未找到 {file_path}")
    return port_data


def process_qlen_file(file_path: str, node_id: int, batch_size: int) -> Tuple[List[Tuple], List[str]]:
    """处理指定节点的 qlen 数据，为绘图准备。"""
    port_data = parse_switch_data(file_path, node_id)
    if not port_data:
        return [], []

    all_first_times = [data['times'][0] for data in port_data.values() if data['times']]
    if not all_first_times:
        return [], []
    time_offset_ns = min(all_first_times)

    data_pairs, labels = [], []
    for port, data in sorted(port_data.items()):
        times_ms = [(t - time_offset_ns) / 1e6 for t in data['times']]
        bytes_data = data['bytes']
        times_batch = batch_mean(times_ms, batch_size)
        bytes_batch = batch_mean(bytes_data, batch_size)
        data_pairs.append((times_batch, bytes_batch))
        labels.append(f"Port {port}")
    return data_pairs, labels


def draw_qlen(data_pairs: List[Tuple], labels: List[str], title: str = "Qlen Comparison"):
    """绘制队列长度对比图。"""
    plt.style.use('seaborn-v0_8-whitegrid')
    plt.figure(figsize=(12, 6))
    colors = plt.get_cmap('tab10')(np.linspace(0, 1, len(data_pairs)))

    for i, (x, y) in enumerate(data_pairs):
        plt.plot(x, y, label=labels[i], color=colors[i], linewidth=2, alpha=0.9)

    plt.title(title, fontsize=16, fontweight='bold')
    plt.xlabel("Time (ms)", fontsize=14)
    plt.ylabel("Egress Bytes (qlen)", fontsize=14)
    plt.grid(True, linestyle='--', alpha=0.6, color='gray')
    plt.gca().spines['top'].set_visible(False)
    plt.gca().spines['right'].set_visible(False)
    plt.legend(loc='upper right', frameon=True, fontsize=10)
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "qlen.png"), dpi=300, bbox_inches='tight')
    plt.close()
    print(f"Qlen图已保存至 {os.path.join(OUTPUT_DIR, 'qlen.png')}")


# =============================================================================
# RDMA (hprate & grantbytes) Module
# =============================================================================

def parse_rdma_log_line(line: str) -> Optional[Dict[str, Any]]:
    """解析单行 RDMA 日志。"""
    match = re.match(r'^\[RdmaEgressQueue::GetNextQindex\]\s+(.+)$', line)
    if not match:
        return None
    
    var_pattern = r'(\w+):\s*([+\-]?\d+(?:\.\d+)?(?:[a-zA-Z]+)?)'
    variables = re.findall(var_pattern, match.group(1))
    result = {}
    for name, value in variables:
        value_stripped = value.lstrip('+')
        try:
            if '.' in value_stripped and not value_stripped.endswith(('ns', 'Gbps')):
                result[name] = float(value_stripped)
            elif value_stripped.isdigit() or (value_stripped.startswith('-') and value_stripped[1:].isdigit()):
                result[name] = int(value_stripped)
            else:
                result[name] = value_stripped
        except ValueError:
            result[name] = value_stripped
    return result


def parse_rdma_log_file(filename: str) -> List[Dict[str, Any]]:
    """解析整个 RDMA 日志文件。"""
    results = []
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                if parsed := parse_rdma_log_line(line.strip()):
                    parsed['line_number'] = line_num
                    results.append(parsed)
    except FileNotFoundError:
        print(f"错误: RDMA 日志文件未找到 {filename}")
    except Exception as e:
        print(f"读取RDMA文件时出错: {e}")
    return results


def draw_hprate(time: List[float], hpcc_u: List[float], hpcc_rate: List[float], batch_size: int):
    """绘制 HPCC u 值和速率图。"""
    time_b = batch_mean(time, batch_size)
    hpcc_u_b = batch_mean(hpcc_u, batch_size)
    hpcc_rate_b = batch_mean(hpcc_rate, batch_size)

    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(10, 8), sharex=True)
    fig.suptitle('HPCC u vs Rate', fontsize=16, fontweight='bold')

    ax1.plot(time_b, hpcc_u_b, color='C0', label='hpcc_u')
    ax1.set_ylabel('u Value')
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend()

    ax2.plot(time_b, hpcc_rate_b, color='C3', label='hpcc_rate')
    ax2.set_xlabel('Time (ms)')
    ax2.set_ylabel('Rate (Gbps)')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(os.path.join(OUTPUT_DIR, "hprate.png"), dpi=300)
    plt.close()
    print(f"HP Rate图已保存至 {os.path.join(OUTPUT_DIR, 'hprate.png')}")


def draw_grantbytes(time: List[float], hpcc_gBytes: List[float], homa_gBytes: List[float], batch_size: int):
    """绘制 HPCC 和 Homa 的 grant bytes 对比图。"""
    time_b = batch_mean(time, batch_size)
    hpcc_gBytes_b = batch_mean(hpcc_gBytes, batch_size)
    homa_gBytes_b = batch_mean(homa_gBytes, batch_size)

    fig, (ax1, ax2) = plt.subplots(nrows=2, ncols=1, figsize=(10, 8), sharex=True)
    fig.suptitle('HPCC vs Homa Grant Bytes', fontsize=16, fontweight='bold')

    ax1.plot(time_b, hpcc_gBytes_b, color='C0', label='HPCC')
    ax1.set_ylabel('HPCC Grant Bytes')
    ax1.grid(True, linestyle='--', alpha=0.6)
    ax1.legend()

    ax2.plot(time_b, homa_gBytes_b, color='C3', label='Homa')
    ax2.set_xlabel('Time (ms)')
    ax2.set_ylabel('Homa Grant Bytes')
    ax2.grid(True, linestyle='--', alpha=0.6)
    ax2.legend()

    plt.tight_layout(rect=[0, 0, 1, 0.96])
    plt.savefig(os.path.join(OUTPUT_DIR, "grantbytes.png"), dpi=300)
    plt.close()
    print(f"Grant Bytes图已保存至 {os.path.join(OUTPUT_DIR, 'grantbytes.png')}")


# =============================================================================
# Stream Visualization Module
# =============================================================================

def parse_stream_log_line(line: str) -> Optional[Tuple[int, int, int, str]]:
    """解析单行数据包传输 (stream) 日志。"""
    pattern = r"\[Trans\] time: (\d+) From-(\d+)-to-(\d+) (\w+)"
    if match := re.search(pattern, line):
        timestamp, source, dest, pkt_type = match.groups()
        return int(timestamp), int(source), int(dest), pkt_type
    return None


def process_and_visualize_stream(
    file_path: str,
    nodes_to_filter: Optional[List[int]]
):
    """加载、处理并可视化 stream 日志为散点泳道图。"""
    print("开始处理 stream 日志...")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = [p for line in f if (p := parse_stream_log_line(line))]
    except FileNotFoundError:
        print(f"错误: stream日志文件未找到 {file_path}")
        return

    if not data:
        print(f"在文件 '{file_path}' 中未能解析到任何有效的stream数据。")
        return

    df = pd.DataFrame(data, columns=['Timestamp', 'Source', 'Destination', 'PacketType'])

    if nodes_to_filter:
        print(f"筛选模式: 只显示与节点 {nodes_to_filter} 相关的流...")
        condition = df['Source'].isin(nodes_to_filter) | df['Destination'].isin(nodes_to_filter)
        df = df[condition].copy()
        if df.empty:
            print(f"警告: 应用节点筛选 {nodes_to_filter} 后，没有找到匹配的数据流。")
            return

    time_offset = df['Timestamp'].min()
    df['Time (ms)'] = (df['Timestamp'] - time_offset) / 1e6
    df.sort_values(by='Time (ms)', inplace=True)
    df['Stream'] = df['Source'].astype(str) + ' -> ' + df['Destination'].astype(str)
    
    # --- 绘图 ---
    title = f"数据包时序泳道图"
    if nodes_to_filter:
        title += f" - 节点: {nodes_to_filter}"
    
    print("正在生成交互式散点泳道图...")
    fig = px.scatter(
        df, x="Time (ms)", y="Stream", color="PacketType",
        title=title,
        hover_name="PacketType",
        hover_data={'Timestamp': True, 'Source': True, 'Destination': True, 'Stream': False, 'Time (ms)': ':.4f'},
        labels={'Stream': '通信流', 'Time (ms)': '时间 (ms)'}
    )
    
    fig.update_traces(marker=dict(size=7, line=dict(width=1, color='DarkSlateGrey')))
    fig.update_layout(legend_title="包类型", title_x=0.5, title_xanchor='center')
    
    output_filename = os.path.join(OUTPUT_DIR, "stream_scatter.html")
    fig.write_html(output_filename)
    print(f"成功！图表已保存为 '{output_filename}'")


# =============================================================================
# Main Execution Logic
# =============================================================================

def setup_arg_parser() -> argparse.ArgumentParser:
    """配置并返回命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="一个用于可视化网络模拟数据的命令行工具。",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "-m", "--mode", dest="mode", required=True,
        choices=["tx", "rx", "qlen", "hprate", "grantbytes", "stream"],
        help="要绘制的指标。"
    )
    parser.add_argument(
        "-f", "--flow", dest="flow", nargs='+', required=True,
        help="一个或多个流的标识符 (用于构造文件路径)。"
    )
    parser.add_argument(
        "-n", "--node", dest="node", nargs='+', type=int,
        help="一个或多个节点 ID。在 'stream' 模式下作为可选过滤器。"
    )
    return parser


def main():
    """主执行函数。"""
    parser = setup_arg_parser()
    args = parser.parse_args()

    # --- 参数校验 ---
    if args.mode != "stream":
        if not args.node:
            parser.error(f"模式 '{args.mode}' 必须提供 -n/--node 参数。")
        if len(args.node) > 1 and len(args.flow) > 1:
            parser.error("参数 -n/--node 和 -f/--flow 不能同时包含多个值。")
    elif len(args.flow) > 1:
        print(f"警告: stream 模式指定了多个 flow，将只处理第一个: {args.flow[0]}")

    # --- 逻辑分发 ---
    if args.mode == "stream":
        flow = args.flow[0]
        file_path = f"./mix/output/{flow}/config.log"
        process_and_visualize_stream(file_path, args.node)
        return

    # --- 处理其他模式 ---
    nodes = args.node
    flows = args.flow
    is_multi_node = len(nodes) > 1
    is_multi_flow = len(flows) > 1

    if is_multi_node:
        flow = flows[0]
        if args.mode in ["tx", "rx"]:
            all_data_for_nodes = [
                process_bandwidth_file(f"./mix/output/{flow}/{flow}_out_throughout.txt", n, BANDWIDTH_BATCH_SIZE)
                for n in nodes
            ]
            y_axis_index = 1 if args.mode == 'tx' else 2
            data_pairs = [(data[0], data[y_axis_index]) for data in all_data_for_nodes]
            labels = [f"{flow}-node{n}" for n in nodes]
            draw_bandwidth(data_pairs, labels)
        elif args.mode == "qlen":
            all_data_pairs, all_labels = [], []
            for node in nodes:
                pairs, lbls = process_qlen_file(f"./mix/output/{flow}/{flow}_out_qlen.txt", node, QLEN_BATCH_SIZE)
                all_data_pairs.extend(pairs)
                all_labels.extend([f"Node {node} - {lbl}" for lbl in lbls])
            draw_qlen(all_data_pairs, all_labels, title=f"Qlen Comparison for Flow {flow}")
    
    elif is_multi_flow:
        node = nodes[0]
        if args.mode in ["tx", "rx"]:
            data_pairs, labels = [], []
            for flow in flows:
                times, tx, rx = process_bandwidth_file(f"./mix/output/{flow}/{flow}_out_throughout.txt", node, BANDWIDTH_BATCH_SIZE)
                y_data = tx if args.mode == "tx" else rx
                data_pairs.append((times, y_data))
                labels.append(f"{flow}-node{node}")
            draw_bandwidth(data_pairs, labels)
        elif args.mode == "qlen":
            all_data_pairs, all_labels = [], []
            for flow in flows:
                pairs, lbls = process_qlen_file(f"./mix/output/{flow}/{flow}_out_qlen.txt", node, QLEN_BATCH_SIZE)
                all_data_pairs.extend(pairs)
                all_labels.extend([f"Flow {flow} - {lbl}" for lbl in lbls])
            draw_qlen(all_data_pairs, all_labels, title=f"Qlen Comparison on Node {node}")

    else: # 单一节点，单一流
        node, flow = nodes[0], flows[0]
        if args.mode in ["tx", "rx"]:
            times, tx, rx = process_bandwidth_file(f"./mix/output/{flow}/{flow}_out_throughout.txt", node, BANDWIDTH_BATCH_SIZE)
            data = (times, tx if args.mode == "tx" else rx)
            draw_bandwidth([data], [f"{flow}-node{node}"])
        elif args.mode == "qlen":
            pairs, labels = process_qlen_file(f"./mix/output/{flow}/{flow}_out_qlen.txt", node, QLEN_BATCH_SIZE)
            draw_qlen(pairs, labels, title=f"Qlen for Switch Node {node} (Flow: {flow})")
        elif args.mode in ["hprate", "grantbytes"]:
            results = parse_rdma_log_file(f"./mix/output/{flow}/config.log")
            filtered_data = [item for item in results if item.get('node') == node]
            if not filtered_data:
                print(f"警告: 在日志中未找到与节点 {node} 相关的 hprate/grantbytes 数据。")
                return
                
            time = [(item['time'] - TIMESTAMP_OFFSET) / 1e6 for item in filtered_data]
            
            if args.mode == "hprate":
                u = [item['u'] for item in filtered_data]
                rate = [item['hp_rate'] for item in filtered_data]
                draw_hprate(time, u, rate, HPRATE_BATCH_SIZE)
            else: # grantbytes
                hp_gbytes = [item['hp_gBytes'] for item in filtered_data]
                homa_gbytes = [item['homa_gBytes'] for item in filtered_data]
                draw_grantbytes(time, hp_gbytes, homa_gbytes, GRANTBYTES_BATCH_SIZE)

if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    main()