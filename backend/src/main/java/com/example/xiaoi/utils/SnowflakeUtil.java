package com.example.xiaoi.utils;

import org.springframework.stereotype.Component;

/**
 * 雪花算法 ID 生成器
 * 生成分布式唯一 ID，结构为：
 * 41位时间戳 + 5位数据中心ID + 5位工作机器ID + 12位序列号
 * 支持每秒最多生成 4096 个 ID，可部署 32 个数据中心，每个数据中心最多 32 台机器
 * 
 * 注意：生成的 Long 类型 ID 返回给前端时需转为字符串，避免 JS Number 精度丢失（超过 2^53）
 */
@Component
public class SnowflakeUtil {

    /** 起始时间戳（2024-01-01 00:00:00），用于减少 ID 长度 */
    private static final long START_TIMESTAMP = 1704067200000L;
    /** 工作机器 ID 位数 */
    private static final long WORKER_ID_BITS = 5L;
    /** 数据中心 ID 位数 */
    private static final long DATA_CENTER_ID_BITS = 5L;
    /** 序列号位数 */
    private static final long SEQUENCE_BITS = 12L;

    /** 工作机器 ID 最大值 */
    private static final long MAX_WORKER_ID = ~(-1L << WORKER_ID_BITS);
    /** 数据中心 ID 最大值 */
    private static final long MAX_DATA_CENTER_ID = ~(-1L << DATA_CENTER_ID_BITS);
    /** 序列号最大值 */
    private static final long MAX_SEQUENCE = ~(-1L << SEQUENCE_BITS);

    /** 工作机器 ID 偏移量 */
    private static final long WORKER_ID_SHIFT = SEQUENCE_BITS;
    /** 数据中心 ID 偏移量 */
    private static final long DATA_CENTER_ID_SHIFT = SEQUENCE_BITS + WORKER_ID_BITS;
    /** 时间戳偏移量 */
    private static final long TIMESTAMP_SHIFT = DATA_CENTER_ID_SHIFT + DATA_CENTER_ID_BITS;

    /** 工作机器 ID */
    private final long workerId;
    /** 数据中心 ID */
    private final long dataCenterId;
    /** 序列号，同一毫秒内递增 */
    private long sequence = 0L;
    /** 上次生成 ID 的时间戳 */
    private long lastTimestamp = -1L;

    /** 默认构造函数，使用默认的 workerId=1, dataCenterId=1 */
    public SnowflakeUtil() {
        this(1L, 1L);
    }

    /**
     * 带参数构造函数
     * @param workerId 工作机器 ID（0-31）
     * @param dataCenterId 数据中心 ID（0-31）
     */
    public SnowflakeUtil(long workerId, long dataCenterId) {
        if (workerId > MAX_WORKER_ID || workerId < 0) {
            throw new IllegalArgumentException("Worker ID can't be greater than " + MAX_WORKER_ID + " or less than 0");
        }
        if (dataCenterId > MAX_DATA_CENTER_ID || dataCenterId < 0) {
            throw new IllegalArgumentException("DataCenter ID can't be greater than " + MAX_DATA_CENTER_ID + " or less than 0");
        }
        this.workerId = workerId;
        this.dataCenterId = dataCenterId;
    }

    /**
     * 生成下一个雪花 ID
     * 使用 synchronized 保证线程安全
     * @return 雪花 ID
     */
    public synchronized long nextId() {
        long timestamp = getCurrentTimestamp();

        // 时钟回拨检测，拒绝生成 ID
        if (timestamp < lastTimestamp) {
            throw new RuntimeException("Clock moved backwards. Refusing to generate ID for " + (lastTimestamp - timestamp) + " milliseconds");
        }

        // 同一毫秒内，序列号递增
        if (timestamp == lastTimestamp) {
            sequence = (sequence + 1) & MAX_SEQUENCE;
            // 序列号溢出，等待下一毫秒
            if (sequence == 0) {
                timestamp = getNextTimestamp();
            }
        } else {
            // 新的毫秒，序列号重置为 0
            sequence = 0L;
        }

        lastTimestamp = timestamp;

        // 组合各部分生成最终 ID
        return ((timestamp - START_TIMESTAMP) << TIMESTAMP_SHIFT)
                | (dataCenterId << DATA_CENTER_ID_SHIFT)
                | (workerId << WORKER_ID_SHIFT)
                | sequence;
    }

    /** 获取当前时间戳（毫秒） */
    private long getCurrentTimestamp() {
        return System.currentTimeMillis();
    }

    /** 获取下一毫秒的时间戳（处理序列号溢出情况） */
    private long getNextTimestamp() {
        long timestamp = getCurrentTimestamp();
        while (timestamp <= lastTimestamp) {
            timestamp = getCurrentTimestamp();
        }
        return timestamp;
    }

    /**
     * 生成下一个雪花 ID 并转为字符串
     * @return 雪花 ID 字符串
     */
    public static String nextIdStr() {
        return String.valueOf(new SnowflakeUtil().nextId());
    }
}