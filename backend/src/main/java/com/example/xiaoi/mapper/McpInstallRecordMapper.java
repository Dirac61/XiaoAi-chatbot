package com.example.xiaoi.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.example.xiaoi.entity.McpInstallRecord;
import org.apache.ibatis.annotations.Mapper;

/**
 * MCP 插件安装记录 Mapper
 * 继承 MyBatis-Plus 的 BaseMapper，自动获得单表 CRUD 能力
 */
@Mapper
public interface McpInstallRecordMapper extends BaseMapper<McpInstallRecord> {
}
