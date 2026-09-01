package com.example.xiaoi.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.xiaoi.entity.SessionDetail;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface SessionDetailMapper extends BaseMapper<SessionDetail> {

    /**
     * 清理 session_detail 孤儿行：删除所有 session_id 不在 session 表中的记录
     * 用于定时兜底任务，对齐 session 表与 session_detail 表的数据一致性
     * @return 实际删除行数
     */
    @Delete("DELETE FROM session_detail WHERE session_id NOT IN (SELECT id FROM session)")
    int deleteOrphanDetails();
}