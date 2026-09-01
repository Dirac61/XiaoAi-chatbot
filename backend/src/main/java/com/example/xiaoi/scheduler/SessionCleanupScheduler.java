package com.example.xiaoi.scheduler;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.example.xiaoi.entity.Session;
import com.example.xiaoi.mapper.SessionDetailMapper;
import com.example.xiaoi.mapper.SessionMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.Cursor;
import org.springframework.data.redis.core.RedisCallback;
import org.springframework.data.redis.core.ScanOptions;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/**
 * 会话孤儿数据定时清理任务
 *
 * 作用：作为墓碑机制的"兜底第二层"，定期把三层存储（MySQL / Redis / Qdrant）中
 *       session_id 不在"存活会话集合"中的孤儿数据对齐清理掉。
 *
 * 触发条件：每 30 分钟一次（0 0/30 * * * ?）
 *
 * 执行步骤（顺序很关键）：
 *   1. 从 MySQL session 表取出所有存活会话 ID（最权威的存活集合）
 *   2. MySQL session_detail 层：用 DELETE NOT IN 子查询原子删除孤儿行
 *   3. Redis 层：SCAN 4 类会话相关前缀（session: / session:turn: / session:summary: / memory:duplicate:），
 *      解析 key 中的 sessionId，不在 aliveIdSet 中的 key 直接 UNLINK 回收
 *   4. Qdrant 层：把 aliveIds 发给 Agent 的内部接口，由 Agent 端 scroll 全量点后做差集删除
 *
 * 说明：
 *   - 墓碑机制负责"写入口时实时拦截"，已能拦截 99%+ 的脏数据产生；
 *   - 本调度器负责"兜底收敛"，清理墓碑 TTL 之外或极端竞态下漏网的孤儿数据。
 */
@Component
public class SessionCleanupScheduler {

    private static final Logger logger = LoggerFactory.getLogger(SessionCleanupScheduler.class);

    @Autowired
    private SessionMapper sessionMapper;

    @Autowired
    private SessionDetailMapper sessionDetailMapper;

    @Autowired
    private StringRedisTemplate redisTemplate;

    @Autowired
    private ObjectMapper objectMapper;

    @Value("${agent.url:http://localhost:8000}")
    private String agentUrl;

    @Value("${internal.secret:xiaoi-internal-api-secret-2026}")
    private String internalSecret;

    /** 需要扫描的 Redis key 前缀：都与会话绑定，孤儿 key 应该被清理 */
    private static final String[] REDIS_SCAN_PREFIXES = new String[]{
            "session:",        // 最近 20 条消息 List（session:{id}）
            "session:turn:",   // 轮次计数器（session:turn:{id}）
            "session:summary:",// 摘要缓存（session:summary:{id}）
            "memory:duplicate:"// 记忆去重 key（memory:duplicate:{id}）
    };

    /**
     * 定时执行孤儿三层清理
     * Cron: 每 30 分钟 0 秒触发一次（0 0/30 * * * ?）
     */
    @Scheduled(cron = "0 0/30 * * * ?")
    public void cleanupOrphans() {
        long startNs = System.nanoTime();
        logger.info("[孤儿清理] 开始执行三层孤儿对齐清理");

        try {
            // ================= 步骤 1：取存活会话 ID（MySQL session 表为权威源） =================
            LambdaQueryWrapper<Session> wrapper = new LambdaQueryWrapper<>();
            wrapper.select(Session::getId);
            List<Session> aliveSessions = sessionMapper.selectList(wrapper);
            Set<Long> aliveIdSet = new HashSet<>(Math.max(aliveSessions.size(), 16));
            for (Session s : aliveSessions) {
                if (s != null && s.getId() != null) {
                    aliveIdSet.add(s.getId());
                }
            }
            logger.info("[孤儿清理-步骤1] 存活会话数: {}", aliveIdSet.size());

            // ================= 步骤 2：MySQL session_detail 原子删除孤儿行 =================
            // 执行 SQL: DELETE FROM session_detail WHERE session_id NOT IN (SELECT id FROM session)
            // 这条 SQL 是纯原子 DB 层操作，比拿到 Java 层再 batchDelete 快得多、安全得多。
            int detailDeleted;
            try {
                detailDeleted = sessionDetailMapper.deleteOrphanDetails();
            } catch (Exception e) {
                logger.error("[孤儿清理-步骤2] MySQL session_detail 孤儿清理失败: {}", e.getMessage(), e);
                detailDeleted = -1;
            }
            logger.info("[孤儿清理-步骤2] MySQL session_detail 孤儿行删除行数: {}", detailDeleted);

            // ================= 步骤 3：Redis SCAN 清理孤儿 key =================
            int redisTotalDeleted = 0;
            try {
                for (String prefix : REDIS_SCAN_PREFIXES) {
                    int delCount = cleanupRedisPrefix(prefix, aliveIdSet);
                    redisTotalDeleted += delCount;
                    logger.debug("[孤儿清理-步骤3] 前缀={} 孤儿key删除数: {}", prefix, delCount);
                }
            } catch (Exception e) {
                logger.error("[孤儿清理-步骤3] Redis 孤儿清理失败: {}", e.getMessage(), e);
            }
            logger.info("[孤儿清理-步骤3] Redis 孤儿 key 总删除数: {}", redisTotalDeleted);

            // ================= 步骤 4：Qdrant 向量点差集清理（通过 Agent 内部接口） =================
            int qdrantDeleted = callAgentCleanupOrphans(aliveIdSet);
            logger.info("[孤儿清理-步骤4] Qdrant 孤儿向量点删除数: {}", qdrantDeleted);

            long costMs = (System.nanoTime() - startNs) / 1_000_000L;
            logger.info("[孤儿清理] 完成。耗时={}ms，存活会话={}，MySQL删孤儿行={}，Redis删孤儿key={}，Qdrant删孤儿点={}",
                    costMs, aliveIdSet.size(), detailDeleted, redisTotalDeleted, qdrantDeleted);
        } catch (Exception e) {
            long costMs = (System.nanoTime() - startNs) / 1_000_000L;
            logger.error("[孤儿清理] 执行异常，已中止：耗时={}ms，错误={}", costMs, e.getMessage(), e);
        }
    }

    /**
     * 针对指定前缀做 Redis SCAN，解析 key 中的 Long 类型 sessionId，
     * 不在 aliveIdSet 中的 key 就是孤儿 key，使用 UNLINK（异步非阻塞删除）清除。
     *
     * 解析规则：key 形如 "prefix:12345"，截取最后一个 ':' 之后的子串并解析为 Long；
     * 解析失败就跳过（可能是墓碑 key session:deleted:{id}，但不在该前缀里也无影响）。
     *
     * @param prefix     要扫描的 Redis key 前缀
     * @param aliveIdSet 存活会话 ID 集合
     * @return 本次前缀清理删除的孤儿 key 数量
     */
    private int cleanupRedisPrefix(String prefix, Set<Long> aliveIdSet) {
        int deleted = 0;
        ScanOptions scanOpts = ScanOptions.scanOptions()
                .match(prefix + "*")
                .count(200)
                .build();
        // 用 RedisCallback 执行原生 SCAN，避免 Spring Data Redis cursor 封装的资源释放问题
        List<String> orphanKeys = redisTemplate.execute((RedisCallback<List<String>>) connection -> {
            List<String> toDelete = new ArrayList<>(128);
            try (Cursor<byte[]> cursor = connection.scan(scanOpts)) {
                while (cursor.hasNext()) {
                    byte[] rawKey = cursor.next();
                    String key;
                    try {
                        key = new String(rawKey, StandardCharsets.UTF_8);
                    } catch (Exception ex) {
                        logger.warn("[孤儿清理-步骤3] 无法解析 Redis key，跳过: {}", ex.getMessage());
                        continue;
                    }
                    int sep = key.lastIndexOf(':');
                    if (sep < 0 || sep == key.length() - 1) {
                        // 没有 : 或 : 后无内容（格式异常），跳过
                        continue;
                    }
                    String idPart = key.substring(sep + 1);
                    Long sessionId;
                    try {
                        sessionId = Long.parseLong(idPart);
                    } catch (NumberFormatException ex) {
                        // id 后缀不是纯 Long（比如 session:deleted:12345 的 deleted:12345 不在这四个前缀里）
                        // 但以防万一加墓碑前缀进扫描，这里也安全跳过
                        continue;
                    }
                    // ★ 差集判断核心：O(1) 的 HashSet.contains，比 removeAll/遍历都快
                    if (!aliveIdSet.contains(sessionId)) {
                        toDelete.add(key);
                    }
                }
            } catch (Exception e) {
                logger.error("[孤儿清理-步骤3] Redis SCAN 前缀{}异常: {}", prefix, e.getMessage(), e);
            }
            return toDelete;
        });
        if (orphanKeys == null || orphanKeys.isEmpty()) {
            return 0;
        }
        try {
            // UNLINK 与 DEL 在 Spring Data Redis 中使用 delete 即可（底层 Redis 4+ 自动用 UNLINK 实现）
            Long removed = redisTemplate.delete(orphanKeys);
            deleted = removed == null ? 0 : removed.intValue();
        } catch (Exception e) {
            // UNLINK 失败降级为逐条删除，避免一条异常影响整批
            for (String orphanKey : orphanKeys) {
                try {
                    Boolean ok = redisTemplate.hasKey(orphanKey);
                    if (Boolean.TRUE.equals(ok)) {
                        redisTemplate.delete(orphanKey);
                        deleted++;
                    }
                } catch (Exception subEx) {
                    logger.warn("[孤儿清理-步骤3] 单条删除key失败: key={}, 错误={}", orphanKey, subEx.getMessage());
                }
            }
        }
        return deleted;
    }

    /**
     * 调用 Agent 的内部接口 DELETE /internal/memory/cleanup-orphans，
     * 由 Agent 端负责 scroll 出 Qdrant 全量点并做 aliveIds 差集删除。
     *
     * @param aliveIdSet 存活会话 ID 集合（Long 型，转 JSON 时会被序列化成 JSON number）
     * @return Agent 返回的已删除孤儿点数量，失败返回 -1
     */
    private int callAgentCleanupOrphans(Set<Long> aliveIdSet) {
        HttpURLConnection conn = null;
        try {
            // 构造请求体：{"alive_session_ids": [1,2,3,...]}
            java.util.Map<String, Object> bodyMap = new java.util.HashMap<>(2);
            bodyMap.put("alive_session_ids", new ArrayList<>(aliveIdSet));
            String jsonBody = objectMapper.writeValueAsString(bodyMap);

            String urlStr = agentUrl + "/internal/memory/cleanup-orphans";
            URL url = new URL(urlStr);
            conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("DELETE");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty("Accept", "application/json");
            conn.setRequestProperty("X-Internal-Secret", internalSecret);
            conn.setDoOutput(true);
            conn.setConnectTimeout(5000);
            // Qdrant scroll 可能比较慢，给 120s 读超时
            conn.setReadTimeout(120000);

            try (java.io.OutputStream os = conn.getOutputStream()) {
                byte[] input = jsonBody.getBytes(StandardCharsets.UTF_8);
                os.write(input, 0, input.length);
            }

            int status = conn.getResponseCode();
            InputStream is = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
            StringBuilder sb = new StringBuilder();
            byte[] buf = new byte[2048];
            int read;
            while (is != null && (read = is.read(buf)) != -1) {
                sb.append(new String(buf, 0, read, StandardCharsets.UTF_8));
            }
            if (is != null) {
                is.close();
            }
            String response = sb.toString();

            if (status == 200) {
                // 预期响应: {"deleted_count": 42, "alive_ids_count": 100, ...}
                java.util.Map<String, Object> respObj = objectMapper.readValue(response,
                        new com.fasterxml.jackson.core.type.TypeReference<java.util.Map<String, Object>>() {});
                Object dc = respObj.get("deleted_count");
                if (dc instanceof Number) {
                    return ((Number) dc).intValue();
                }
                logger.warn("[孤儿清理-步骤4] Agent 响应未找到 deleted_count 字段: response={}", response);
                return 0;
            }
            logger.error("[孤儿清理-步骤4] Agent 清理失败: status={}, response={}", status, response);
            return -1;
        } catch (Exception e) {
            logger.error("[孤儿清理-步骤4] 调用 Agent 清理接口异常: {}", e.getMessage(), e);
            return -1;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }
}
