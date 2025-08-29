#ifndef RDMA_HW_H
#define RDMA_HW_H

#include <ns3/custom-header.h>
#include <ns3/node.h>
#include <ns3/rdma.h>
#include <ns3/selective-packet-queue.h>

#include <cstdint>
#include <unordered_map>
#include <unordered_set>
#include <functional>

#include "ns3/ipv4-address.h"
#include "ns3/settings.h"
#include "qbb-net-device.h"
#include "rdma-queue-pair.h"

namespace ns3 {

struct RdmaInterfaceMgr {
    Ptr<QbbNetDevice> dev;
    Ptr<RdmaQueuePairGroup> qpGrp;

    RdmaInterfaceMgr() : dev(NULL), qpGrp(NULL) {}
    RdmaInterfaceMgr(Ptr<QbbNetDevice> _dev) { dev = _dev; }
};

enum class QueueType {
    NONE,
    HIGH_PRIORITY,
    FAIR
};

struct FlowState {
    uint16_t sport;
    uint16_t dport;
    uint16_t priority;
    uint32_t src_ip;
    uint32_t dst_ip;
    uint32_t remaining_bytes;
    Time last_send_time;

    QueueType current_queue = QueueType::NONE; // 在非公平homa中为NONE
    
    bool operator < (const FlowState& other) const {
        return (priority != other.priority) ? 
               (priority < other.priority) : (remaining_bytes > other.remaining_bytes);
    }
};

struct FlowKey {
    uint32_t src_ip;
    uint32_t dst_ip;
    uint16_t sport;
    uint16_t dport;

    FlowKey(uint32_t s_ip, uint32_t d_ip, uint16_t s_port, uint16_t d_port)
        : src_ip(s_ip), dst_ip(d_ip), sport(s_port), dport(d_port) {}

    bool operator==(const FlowKey& other) const {
        return src_ip == other.src_ip && dst_ip == other.dst_ip &&
               sport == other.sport && dport == other.dport;
    }
};

struct FlowKeyHasher {
    std::size_t operator()(const FlowKey& k) const {
        std::size_t h1 = std::hash<uint32_t>()(k.src_ip);
        std::size_t h2 = std::hash<uint32_t>()(k.dst_ip);
        std::size_t h3 = std::hash<uint16_t>()(k.sport);
        std::size_t h4 = std::hash<uint16_t>()(k.dport);
        return h1 ^ (h2 << 1) ^ (h3 << 2) ^ (h4 << 3);
    }
};

class FlowScheduler {
public:
    FlowScheduler() : high_priority_queue_comparator(flow_map), 
                      high_priority_queue(high_priority_queue_comparator) {}

    void add_or_update_flow(const FlowState& flow_data) {
        FlowKey key(flow_data.src_ip, flow_data.dst_ip, flow_data.sport, flow_data.dport);
        
        auto it = flow_map.find(key);

        if (it == flow_map.end()) {
            if (flow_data.remaining_bytes == 0) return;
            flow_map[key] = flow_data;
            FlowState& new_flow = flow_map.at(key);
            requeue_flow(key, new_flow);
        } else {
            uint32_t bytes_to_add = flow_data.remaining_bytes;
            if (bytes_to_add == 0) return;
            update_remaining_bytes(key, bytes_to_add);
        }
    }
    
    void update_remaining_bytes(const FlowKey& key, int bytes_to_add) {
        auto it = flow_map.find(key);
        if (it == flow_map.end()) {
            return;
        }

        FlowState& flow = it->second;
        
        // 计算状态
        uint32_t old_bytes = flow.remaining_bytes;
        uint32_t new_bytes = old_bytes + bytes_to_add;
        
        std::cout << "[Update HOMA remaining bytes]" << " "
                  << Settings::ip_to_node_id(Ipv4Address(key.dst_ip)) << " -> "
                  << Settings::ip_to_node_id(Ipv4Address(key.src_ip)) << "\t"
                  << old_bytes << "->"
                  << new_bytes << "\t"
                  << std::endl;

        bool was_in_high_priority = (old_bytes <= flow_threshold);
        bool is_now_in_high_priority = (new_bytes <= flow_threshold);

        if (was_in_high_priority == is_now_in_high_priority) {
            // 队列类型没变
            if (was_in_high_priority) {
                high_priority_queue.erase(key);
                flow.remaining_bytes = new_bytes; // 更新字节数
                high_priority_queue.insert(key); // 重新排序
            } else {
                flow.remaining_bytes = new_bytes;
            }
        } else {
            // 队列类型改变
            remove_from_current_queue(key);
            flow.remaining_bytes = new_bytes;
            requeue_flow(key, flow);
        }
    }

    bool dispatch(std::function<void(FlowState&)> process_callback) {
        FlowKey current_key(0, 0, 0, 0);
        bool got_flow = false;

        if (!high_priority_queue.empty()) {
            auto it = high_priority_queue.begin();
            current_key = *it;
            high_priority_queue.erase(it);
            got_flow = true;
        } else {
            while (!fair_scheduler_queue.empty()) {
                current_key = fair_scheduler_queue.front();
                fair_scheduler_queue.pop_front();

                // "惰性"删除（暂时没什么用）
                if (fair_queue_set.count(current_key)) {
                    fair_queue_set.erase(current_key);
                    got_flow = true;
                    break;
                }
            }
        }

        if (!got_flow) {
            return false;
        }
                 
        FlowState& current_flow = flow_map.at(current_key);
        current_flow.current_queue = QueueType::NONE;
        process_callback(current_flow);

        if (current_flow.remaining_bytes > 0) {
            requeue_flow(current_key, current_flow); // 处理后重新入队
        } else {
            flow_map.erase(current_key);
        }

        return true;
    }

    bool has_flows() const {
        return !flow_map.empty();
    }

    void set_flow_threshold(int threshold) {
        this->flow_threshold = threshold;
    }

private:
    using FlowMapType = std::unordered_map<FlowKey, FlowState, FlowKeyHasher>;
    
    struct FlowKeyComparator {
        const FlowMapType& map_ref;
        explicit FlowKeyComparator(const FlowMapType& map) : map_ref(map) {}
        bool operator()(const FlowKey& a, const FlowKey& b) const {
            return map_ref.at(b) < map_ref.at(a); // PS: 这里反转了FlowState比较逻辑
        }
    };
    
    void requeue_flow(const FlowKey& key, FlowState& flow) {
        if (flow.remaining_bytes <= this->flow_threshold) {
            high_priority_queue.insert(key);
            flow.current_queue = QueueType::HIGH_PRIORITY;
        } else {
            fair_scheduler_queue.push_back(key);
            fair_queue_set.insert(key);
            flow.current_queue = QueueType::FAIR;
        }
    }

    void remove_from_current_queue(const FlowKey& key) {
        auto it = flow_map.find(key);
        if (it == flow_map.end()) {
            return;
        }

        const FlowState& flow = it->second;
        if (flow.current_queue == QueueType::HIGH_PRIORITY) {
            high_priority_queue.erase(key);
        } else if (flow.current_queue == QueueType::FAIR) {
            fair_queue_set.erase(key);
        }
    }

    int flow_threshold = 2000;
    FlowMapType flow_map;
    FlowKeyComparator high_priority_queue_comparator;
    std::set<FlowKey, FlowKeyComparator> high_priority_queue;
    std::list<FlowKey> fair_scheduler_queue;
    std::unordered_set<FlowKey, FlowKeyHasher> fair_queue_set;
};

class RdmaHw : public Object {
   public:
    static TypeId GetTypeId(void);
    RdmaHw();

    Ptr<Node> m_node;
    DataRate m_minRate;  //< Min sending rate78555
    uint32_t m_mtu;
    uint32_t m_cc_mode;
    double m_nack_interval;
    uint32_t m_chunk;
    uint32_t m_ack_interval;
    bool m_backto0;
    bool m_var_win, m_fast_react;
    bool m_rateBound;
    std::vector<RdmaInterfaceMgr> m_nic;  // list of running nic controlled by this RdmaHw
    std::unordered_map<uint64_t, Ptr<RdmaQueuePair>> m_qpMap;      // mapping from uint64_t to qp
    std::unordered_map<uint64_t, Ptr<RdmaRxQueuePair>> m_rxQpMap;  // mapping from uint64_t to rx qp
    std::unordered_map<uint32_t, std::vector<int>>
        m_rtTable;  // map from ip address (u32) to possible ECMP port (index of dev)

    // qp complete callback
    typedef Callback<void, Ptr<RdmaQueuePair>> QpCompleteCallback;
    QpCompleteCallback m_qpCompleteCallback;

    void SetNode(Ptr<Node> node);
    void Setup(QpCompleteCallback cb);  // setup shared data and callbacks with the QbbNetDevice

    /* Akashic Record of finished QP */
    std::unordered_set<uint64_t> akashic_Qp;    // instance for each src
    std::unordered_set<uint64_t> akashic_RxQp;  // instance for each dst
    static uint64_t nAllPkts;                   // number of total packets

    /* TxQpeueuPair */
    static uint64_t GetQpKey(uint32_t dip, uint16_t sport, uint16_t dport,
                             uint16_t pg);          // get the lookup key for m_qpMap
    Ptr<RdmaQueuePair> GetQp(uint64_t key);         // get the qp
    uint32_t GetNicIdxOfQp(Ptr<RdmaQueuePair> qp);  // get the NIC index of the qp
    void DeleteQueuePair(Ptr<RdmaQueuePair> qp);    // delete TxQP

    void AddQueuePair(uint64_t size, uint16_t pg, Ipv4Address _sip, Ipv4Address _dip,
                      uint16_t _sport, uint16_t _dport, uint32_t win, uint64_t baseRtt,
                      int32_t flow_id);  // add a nw qp (new send)
    void AddQueuePair(uint64_t size, uint16_t pg, Ipv4Address _sip, Ipv4Address _dip,
                      uint16_t _sport, uint16_t _dport, uint32_t win, uint64_t baseRtt) {
        this->AddQueuePair(size, pg, _sip, _dip, _sport, _dport, win, baseRtt, -1);
    }

    /* RxQueuePair */
    static uint64_t GetRxQpKey(uint32_t dip, uint16_t dport, uint16_t sport, uint16_t pg);
    Ptr<RdmaRxQueuePair> GetRxQp(uint32_t sip, uint32_t dip, uint16_t sport, uint16_t dport,
                                 uint16_t pg, bool create);  // get a rxQp
    uint32_t GetNicIdxOfRxQp(Ptr<RdmaRxQueuePair> q);        // get the NIC index of the rxQp
    void DeleteRxQp(uint32_t dip, uint16_t dport, uint16_t sport, uint16_t pg);  // delete RxQP

    int ReceiveUdp(Ptr<Packet> p, CustomHeader &ch);
    int ReceiveCnp(Ptr<Packet> p, CustomHeader &ch);
    int ReceiveAck(Ptr<Packet> p, CustomHeader &ch);  // handle both ACK and NACK
    int Receive(Ptr<Packet> p,
                CustomHeader &
                    ch);  // callback function that the QbbNetDevice should use when receive
                          // packets. Only NIC can call this function. And do not call this upon PFC

    void CheckandSendQCN(Ptr<RdmaRxQueuePair> q);
    int ReceiverCheckSeq(uint32_t seq, Ptr<RdmaRxQueuePair> q, uint32_t size, bool &cnp);
    void AddHeader(Ptr<Packet> p, uint16_t protocolNumber);
    static uint16_t EtherToPpp(uint16_t protocol);

    void RecoverQueue(Ptr<RdmaQueuePair> qp);
    void QpComplete(Ptr<RdmaQueuePair> qp);
    void SetLinkDown(Ptr<QbbNetDevice> dev);

    // call this function after the NIC is setup
    void AddTableEntry(Ipv4Address &dstAddr, uint32_t intf_idx);
    void ClearTable();
    void RedistributeQp();

    Ptr<Packet> GetNxtPacket(Ptr<RdmaQueuePair> qp);  // get next packet to send, inc snd_nxt
    void PktSent(Ptr<RdmaQueuePair> qp, Ptr<Packet> pkt, Time interframeGap);
    void UpdateNextAvail(Ptr<RdmaQueuePair> qp, Time interframeGap, uint32_t pkt_size);
    void ChangeRate(Ptr<RdmaQueuePair> qp, DataRate new_rate);

    void HandleTimeout(Ptr<RdmaQueuePair> qp, Time rto);

    /* statistics */
    uint32_t cnp_by_ecn;
    uint32_t cnp_by_ooo;
    uint32_t cnp_total;
    size_t getIrnBufferOverhead();  // get buffer overhead for IRN

    /**********************
     * Homa
     *********************/
    bool homa_is_running = false; // 当前rdmahw的HOMA逻辑是否启用（位于接收方）
    // 非公平HOMA
    std::priority_queue<FlowState> request_queue; // 根据流做优先队列（HOMA非公平调度）
    std::unordered_map<uint64_t, FlowState> request_queue_hash; // 哈希表记录哪些qp已经入队
    uint64_t get_flow_id (uint32_t src, uint32_t dst);
    void HandleUdpHoma(Ptr<Packet> p, CustomHeader &ch);
    void SendHomaPkt();

    // 公平HOMA
    FlowScheduler homa_scheduler; // HOMA公平调度器
    void HandleUdpHomaFair(Ptr<Packet> p, CustomHeader &ch);
    void SendHomaPktFair();

    int ReceiveHoma(Ptr<Packet> p, CustomHeader &ch);
    void HandleAckHoma(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch);

    /******************************
     * Mellanox's version of DCQCN
     *****************************/
    double m_g;               // feedback weight
    double m_rateOnFirstCNP;  // the fraction of line rate to set on first CNP
    bool m_EcnClampTgtRate;
    double m_rpgTimeReset;
    double m_rateDecreaseInterval;
    uint32_t m_rpgThreshold;
    double m_alpha_resume_interval;
    DataRate m_rai;   //< Rate of additive increase
    DataRate m_rhai;  //< Rate of hyper-additive increase

    // the Mellanox's version of alpha update:
    // every fixed time slot, update alpha.
    void UpdateAlphaMlx(Ptr<RdmaQueuePair> q);
    void ScheduleUpdateAlphaMlx(Ptr<RdmaQueuePair> q);

    // Mellanox's version of CNP receive
    void cnp_received_mlx(Ptr<RdmaQueuePair> q);

    // Mellanox's version of rate decrease
    // It checks every m_rateDecreaseInterval if CNP arrived (m_decrease_cnp_arrived).
    // If so, decrease rate, and reset all rate increase related things
    void CheckRateDecreaseMlx(Ptr<RdmaQueuePair> q);
    void ScheduleDecreaseRateMlx(Ptr<RdmaQueuePair> q, uint32_t delta);

    // Mellanox's version of rate increase
    void RateIncEventTimerMlx(Ptr<RdmaQueuePair> q);
    void RateIncEventMlx(Ptr<RdmaQueuePair> q);
    void FastRecoveryMlx(Ptr<RdmaQueuePair> q);
    void ActiveIncreaseMlx(Ptr<RdmaQueuePair> q);
    void HyperIncreaseMlx(Ptr<RdmaQueuePair> q);

    // Implement Timeout according to IB Spec Vol. 1 C9-139.
    // For an HCA requester using Reliable Connection service, to detect missing responses,
    // every Send queue is required to implement a Transport Timer to time outstanding requests.
    Time m_waitAckTimeout;

    /***********************
     * High Precision CC
     ***********************/
    double m_targetUtil;
    double m_utilHigh;
    uint32_t m_miThresh;
    bool m_multipleRate;
    bool m_sampleFeedback;  // only react to feedback every RTT, or qlen > 0
    void HandleAckHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch);
    void UpdateRateHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool fast_react);
    void UpdateRateHpTest(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool fast_react);
    void FastReactHp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch);
    void UpdateGrantBytesHp(Ptr<RdmaQueuePair> qp); // 用于更新HPCC令牌桶数量

    /**********************
     * TIMELY
     *********************/
    double m_tmly_alpha, m_tmly_beta;
    uint64_t m_tmly_TLow, m_tmly_THigh, m_tmly_minRtt;
    void HandleAckTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch);
    void UpdateRateTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch, bool us);
    void FastReactTimely(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch);

    /**********************
     * DCTCP
     *********************/
    DataRate m_dctcp_rai;
    void HandleAckDctcp(Ptr<RdmaQueuePair> qp, Ptr<Packet> p, CustomHeader &ch);

    /**********************
     * IRN
     *********************/
    bool m_irn;
    Time m_irn_rtoLow;
    Time m_irn_rtoHigh;
    uint32_t m_irn_bdp;
};

} /* namespace ns3 */

#endif /* RDMA_HW_H */
