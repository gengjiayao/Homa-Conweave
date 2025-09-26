#ifndef RDMA_HW_H
#define RDMA_HW_H

#include <ns3/custom-header.h>
#include <ns3/node.h>
#include <ns3/rdma.h>
#include <ns3/selective-packet-queue.h>

#include <cstdint>
#include <unordered_map>
#include <functional>
#include <list>

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

struct curFlowId {
    uint32_t src_ip;
    uint32_t dst_ip;
    uint16_t sport;
    uint16_t dport;
    uint16_t priority;

    bool operator==(const curFlowId& other) const;
};

struct FlowIdHasher {
    std::size_t operator()(const curFlowId& k) const;
};

struct FlowData {
    uint32_t remainingBytes;
    Time lastSendTime;
};

// 新增：流统计信息结构
struct FlowStats {
    uint64_t total_bytes_received;  // 已接收的总字节数
    Time first_packet_time;         // 首包到达时间
    Time last_packet_time;          // 最近一个包到达时间
    uint8_t current_group;          // 当前所属分组 (0=mice, 1=elephant)
    
    FlowStats() : total_bytes_received(0), current_group(0) {}
};

// 新增：流分组枚举
enum FlowGroup {
    MICE_FLOW = 0,
    ELEPHANT_FLOW = 1
};

class FairScheduler {
public:
    FairScheduler();
    ~FairScheduler();

    bool AddOrUpdateFlow(const curFlowId& id, uint32_t bytesToAdd);
    bool GetNextFlow(curFlowId& nextFlowId);
    void RequeueFlow(const curFlowId& id);
    bool RemoveFlow(const curFlowId& id);
    FlowData& GetFlowData(const curFlowId& id);
    bool IsEmpty() const;
    size_t GetActiveFlowCount() const;
    std::vector<curFlowId> GetAllFlowIds() const;

private:
    std::unordered_map<curFlowId, FlowData, FlowIdHasher> m_flowMap;
    std::list<curFlowId> m_scheduleQueue;
};

// 新增：动态流感知调度器
class DynamicFlowAwareScheduler {
public:
    DynamicFlowAwareScheduler();
    ~DynamicFlowAwareScheduler();

    // 添加或更新流的统计信息
    bool AddOrUpdateFlowStats(const curFlowId& id, uint32_t bytesToAdd);
    
    // 移除流统计
    bool RemoveFlowStats(const curFlowId& id);
    
    // 动态分组：基于百分位的自适应阈值
    void UpdateFlowGrouping();
    
    // 差异化速率分配
    void CalculateDifferentiatedRates(DataRate totalCapacity, DataRate& rateMice, DataRate& rateElephant);
    
    // 获取流的分组信息
    FlowGroup GetFlowGroup(const curFlowId& id) const;
    
    // 获取统计信息
    size_t GetMiceFlowCount() const;
    size_t GetElephantFlowCount() const;
    size_t GetTotalFlowCount() const;
    std::vector<curFlowId> GetMiceFlows() const;
    std::vector<curFlowId> GetElephantFlows() const;
    
    // 设置配置参数
    void SetPercentileThreshold(double percentile) { m_percentileThreshold = percentile; }
    void SetMiceCapacityRatio(double ratio) { m_miceCapacityRatio = ratio; }
    void SetUpdateInterval(Time interval) { m_updateInterval = interval; }

private:
    // 活动流表：记录每个流的统计信息
    std::unordered_map<curFlowId, FlowStats, FlowIdHasher> m_activeFlowTable;
    
    // 配置参数
    double m_percentileThreshold;  // 百分位阈值，默认0.8 (P80)
    double m_miceCapacityRatio;    // 小流预留带宽比例，默认0.2 (20%)
    Time m_updateInterval;         // 更新间隔，默认1000ns
    uint64_t m_dynamicThreshold;   // 动态计算的大小流阈值
    Time m_lastUpdateTime;         // 上次更新时间
    
    // 计算百分位阈值
    uint64_t CalculatePercentileThreshold();
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
    int Receive(Ptr<Packet> p, CustomHeader &ch);  // callback function that the QbbNetDevice should use when receive packets. 
                                                   // Only NIC can call this function. And do not call this upon PFC

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
     * Homa - Enhanced with Dynamic Flow-Aware Weighted Rate Allocation
     *********************/
    FairScheduler m_fairScheduler; // 保留原有调度器用于兼容性
    DynamicFlowAwareScheduler m_dynamicFlowScheduler; // 新增动态流感知调度器
    DataRate m_totalBandwidth = DataRate("100Gbps");
    
    // 原有方法
    void HandleHomaRequest(Ptr<Packet> p, CustomHeader &ch);
    void RecalculateAndBroadcastGrants();
    void HandleHomaFinish(const curFlowId& flowId);
    void SendGrantPacket(const curFlowId& flowId, DataRate rate);
    int ReceiveHoma(Ptr<Packet> p, CustomHeader &ch);
    bool IsFlowCompleted(Ptr<RdmaRxQueuePair> rxQp, Ptr<Packet> p, CustomHeader &ch);
    
    // 新增动态流感知方法
    void HandleHomaRequestEnhanced(Ptr<Packet> p, CustomHeader &ch);
    void RecalculateAndBroadcastGrantsEnhanced();
    void HandleHomaFinishEnhanced(const curFlowId& flowId);
    void SendDifferentiatedGrantPackets(DataRate rateMice, DataRate rateElephant);
    void SchedulePeriodicUpdate();
    void PeriodicUpdateCallback();
    
    // 配置参数
    bool m_enableDynamicFlowAware = true;  // 启用动态流感知功能
    Time m_updateInterval = NanoSeconds(1000);  // 更新间隔
    EventId m_periodicUpdateEvent;  // 周期性更新事件
    uint64_t m_flowSizeThreshold = 1024 * 1024; // 流大小阈值(字节)，默认1MB

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
