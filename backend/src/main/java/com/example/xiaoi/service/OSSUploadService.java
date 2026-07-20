package com.example.xiaoi.service;

import com.aliyun.oss.OSS;
import com.aliyun.oss.model.PutObjectRequest;
import com.example.xiaoi.config.OSSConfig;
import com.example.xiaoi.entity.FileHash;
import com.example.xiaoi.mapper.FileHashMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.context.annotation.Lazy;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * OSS 文件上传服务（带哈希去重）
 * <p>
 * 核心设计：
 * <ul>
 *   <li>MySQL 为唯一数据源，file_hash 唯一索引保证 O(log N) 查询性能</li>
 *   <li>SELECT ... FOR UPDATE 行锁保证引用计数并发安全</li>
 *   <li>文件 URL 保持不变（MD5 文件名），去重对前端透明</li>
 *   <li>上传 +1，取消 -1，引用为 0 时删除 OSS 文件</li>
 * </ul>
 */
@Service
public class OSSUploadService {

    private static final Logger logger = LoggerFactory.getLogger(OSSUploadService.class);

    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ofPattern("yyyy/MM/dd");

    @Autowired
    private OSS ossClient;

    @Autowired
    private OSSConfig ossConfig;

    @Autowired
    private FileHashMapper fileHashMapper;

    // 自我注入（@Lazy 避免循环依赖），使 @Transactional 通过代理调用生效
    @Autowired
    @Lazy
    private OSSUploadService self;

    // ==================== 公开接口 ====================

    /**
     * 上传图片（带哈希去重）
     */
    public String uploadImage(MultipartFile file) throws IOException {
        return uploadWithDedup(file, "IMAGE");
    }

    /**
     * 上传文件（带哈希去重）
     */
    public String uploadFile(MultipartFile file) throws IOException {
        return uploadWithDedup(file, "FILE");
    }

    /**
     * 批量上传图片（带哈希去重）
     */
    public java.util.List<String> uploadImages(MultipartFile[] files) throws IOException {
        return uploadWithDedupBatch(files, "IMAGE");
    }

    /**
     * 批量上传文件（带哈希去重）
     */
    public java.util.List<String> uploadFiles(MultipartFile[] files) throws IOException {
        return uploadWithDedupBatch(files, "FILE");
    }

    /**
     * 哈希去重上传入口
     * <p>
     * 流程：
     * <ol>
     *   <li>计算文件 MD5</li>
     *   <li>开启事务 → SELECT ... FOR UPDATE 行锁</li>
     *   <li>记录存在 → 递增引用 → 返回已有 URL（无需 OSS 上传）</li>
     *   <li>记录不存在 → 上传 OSS → INSERT 记录（ref_count=1）</li>
     * </ol>
     */
    public String uploadWithDedup(MultipartFile file, String fileType) throws IOException {
        long t0 = System.currentTimeMillis();
        String md5 = calculateMd5(file);
        long t1 = System.currentTimeMillis();
        logger.info("哈希去重上传: original={}, md5={}, type={}, size={}, md5耗时={}ms",
                file.getOriginalFilename(), md5, fileType, file.getSize(), (t1 - t0));

        // 事务内查 DB + 可能的 OSS 上传（通过 self 调用使 @Transactional 生效）
        long t2 = System.currentTimeMillis();
        String url = self.uploadInTransaction(file, md5, fileType);
        long t3 = System.currentTimeMillis();
        logger.info("上传总耗时: original={}, md5={}ms, 事务={}ms, total={}ms",
                file.getOriginalFilename(), (t1 - t0), (t3 - t2), (t3 - t0));
        return url;
    }

    /**
     * 批量哈希去重上传入口
     */
    public java.util.List<String> uploadWithDedupBatch(MultipartFile[] files, String fileType) throws IOException {
        java.util.List<String> urls = new java.util.ArrayList<>(files.length);
        for (MultipartFile file : files) {
            urls.add(uploadWithDedup(file, fileType));
        }
        return urls;
    }

    /**
     * 哈希去重删除入口
     * <p>
     * 流程：
     * <ol>
     *   <li>通过 URL 查询 file_hash 记录</li>
     *   <li>记录不存在 → 直接删除 OSS（兼容旧数据）</li>
     *   <li>记录存在 → SELECT ... FOR UPDATE 行锁</li>
     *   <li>ref_count > 1 → 递减 → 保留 OSS</li>
     *   <li>ref_count = 1 → 删除记录 → 删除 OSS</li>
     * </ol>
     *
     * @param url 阿里云 OSS 文件 URL
     * @return 删除是否成功
     */
    public boolean deleteWithDedup(String url) {
        if (url == null || url.isEmpty()) return false;

        logger.info("哈希去重删除: url={}", url);

        // 1. 通过 URL 查询文件哈希记录
        FileHash record = fileHashMapper.selectByUrl(url);
        if (record == null) {
            logger.warn("哈希记录不存在，直接删除 OSS: url={}", url);
            return deleteFileDirect(url);
        }

        logger.debug("查询到 file_hash 记录: md5={}, refCount={}", record.getFileHash(), record.getRefCount());

        // 2. 事务内递减引用（通过 self 调用使 @Transactional 生效）
        DeleteResult result = self.decrementRefInTransaction(record.getFileHash(), url);

        // 3. 引用为 0 时删除 OSS 文件
        if (result.isDeleteOss()) {
            logger.info("引用归零，删除 OSS 文件: url={}", url);
            return deleteFileDirect(url);
        }

        logger.debug("引用未归零，保留 OSS 文件: url={}", url);
        return true;
    }

    /**
     * 从 OSS URL 删除文件（非哈希去重方式，直接删除）
     * 用于回退：哈希记录不存在时直接删 OSS
     */
    public boolean deleteFileDirect(String url) {
        try {
            String objectName = extractObjectNameFromUrl(url);
            if (objectName != null) {
                ossClient.deleteObject(ossConfig.getBucketName(), objectName);
                logger.info("OSS 文件直接删除成功: objectName={}", objectName);
                return true;
            }
            return false;
        } catch (Exception e) {
            logger.error("OSS 文件直接删除失败: url={}, error={}", url, e.getMessage());
            return false;
        }
    }

    // ==================== 内部方法 ====================

    /**
     * 上传的事务处理方法
     * <p>
     * 使用 @Transactional + FOR UPDATE 保证并发安全：
     * <ul>
     *   <li>已有记录 → SELECT ... FOR UPDATE → 递增引用 → 返回已有 URL</li>
     *   <li>新记录 → 上传 OSS（首次上传无并发争用）→ INSERT</li>
     * </ul>
     * <p>
     * 并发安全兜底：INSERT 时若唯一键冲突（DuplicateKeyException），
     * 说明另一请求先插入了，改用已有 URL + 递增引用。
     */
    @Transactional
    public String uploadInTransaction(MultipartFile file, String md5, String fileType) throws IOException {
        long t0 = System.currentTimeMillis();

        // FOR UPDATE 行锁：同一 hash 的并发请求串行化
        FileHash existing = fileHashMapper.selectForUpdate(md5);
        long t1 = System.currentTimeMillis();

        if (existing != null && existing.getStorageUrl() != null && !existing.getStorageUrl().isEmpty()) {
            // 已有文件 → 递增引用
            fileHashMapper.incrementRefCount(md5);
            long t2 = System.currentTimeMillis();
            int newRefCount = existing.getRefCount() + 1;
            logger.info("数据已存在，引用+1: md5={}, refCount={}, select={}ms, update={}ms",
                    md5, newRefCount, (t1 - t0), (t2 - t1));
            return existing.getStorageUrl();
        }

        // 全新文件 → 上传 OSS（事务内，首次上传无并发争用）
        // OSS 文件名使用 MD5 命名，使并发上传幂等（同一文件覆盖写入同一路径，零浪费）
        String extension = extractExtension(file.getOriginalFilename());
        String folder = "IMAGE".equals(fileType) ? "images" : "files";
        String datePath = LocalDateTime.now().format(DATE_FORMATTER);
        String objectName = folder + "/" + datePath + "/" + md5 + extension;

        String url;
        try (InputStream inputStream = file.getInputStream()) {
            PutObjectRequest request = new PutObjectRequest(ossConfig.getBucketName(), objectName, inputStream);
            ossClient.putObject(request);
            url = "https://" + ossConfig.getBucketName() + "." + ossConfig.getEndpoint() + "/" + objectName;
            logger.info("文件上传 OSS 成功: original={}, url={}", file.getOriginalFilename(), url);
        } catch (Exception e) {
            logger.error("OSS 上传失败: original={}, error={}", file.getOriginalFilename(), e.getMessage());
            throw new IOException("文件上传失败: " + e.getMessage(), e);
        }

        // INSERT 哈希记录
        FileHash record = new FileHash();
        record.setFileHash(md5);
        record.setStorageUrl(url);
        record.setFileType(fileType);
        record.setFileSize(file.getSize());
        record.setOriginalExtension(extension);
        record.setRefCount(1);

        int newRefCount;
        try {
            fileHashMapper.insert(record);
            newRefCount = 1;
            logger.info("file_hash 记录创建成功: md5={}, refCount=1, size={}", md5, file.getSize());
        } catch (DuplicateKeyException e) {
            // 并发兜底：另一请求先插入了同 hash 的记录
            // 递增引用并使用已有 URL
            FileHash existingAfterLock = fileHashMapper.selectForUpdate(md5);
            if (existingAfterLock != null) {
                fileHashMapper.incrementRefCount(md5);
                url = existingAfterLock.getStorageUrl();
                newRefCount = existingAfterLock.getRefCount() + 1;
                logger.info("并发冲突，使用已有记录: md5={}, refCount={}, url={}",
                        md5, newRefCount, url);
            } else {
                logger.warn("并发兜底异常: 查询已有记录也为空, md5={}", md5);
                newRefCount = 0;
            }
        }

        logger.info("事务完成，返回 URL: md5={}, url={}", md5, url);
        return url;
    }

    /**
     * 删除的事务处理方法：递减引用计数（FOR UPDATE 行锁）
     * <p>
     * 返回 {@link DeleteResult} 告知调用方是否需要删除 OSS
     */
    @Transactional
    public DeleteResult decrementRefInTransaction(String md5, String url) {
        logger.info("递减引用: md5={}, url={}", md5, url);

        // FOR UPDATE 行锁
        FileHash locked = fileHashMapper.selectForUpdate(md5);
        if (locked == null) {
            logger.warn("file_hash 记录已不存在: md5={}", md5);
            return DeleteResult.deleteOss(); // 记录不存在，去删 OSS（幂等）
        }

        logger.debug("行锁获取成功: md5={}, refCount={}", md5, locked.getRefCount());

        int affected = fileHashMapper.decrementRefCount(md5);
        if (affected == 0) {
            logger.warn("引用次数已为 0，跳过: md5={}", md5);
            return DeleteResult.noOp();
        }

        Integer currentCount = fileHashMapper.selectRefCount(md5);
        logger.info("引用递减完成: md5={}, refCount={}→{}", md5, locked.getRefCount(), currentCount);

        if (currentCount != null && currentCount > 0) {
            // 仍有引用 → 保留 OSS
            logger.info("引用未归零，保留 OSS: md5={}, refCount={}", md5, currentCount);
            return DeleteResult.notDeleteOss();
        }

        // 引用为 0 → 删除记录
        fileHashMapper.deleteById(locked.getId());
        logger.info("引用为 0，删除 file_hash 记录: md5={}", md5);
        return DeleteResult.deleteOss();
    }

    /**
     * 计算文件 MD5 哈希值
     */
    private String calculateMd5(MultipartFile file) throws IOException {
        try {
            MessageDigest md = MessageDigest.getInstance("MD5");
            try (InputStream is = file.getInputStream()) {
                byte[] buffer = new byte[8192];
                int bytesRead;
                while ((bytesRead = is.read(buffer)) != -1) {
                    md.update(buffer, 0, bytesRead);
                }
            }
            byte[] digest = md.digest();
            StringBuilder sb = new StringBuilder();
            for (byte b : digest) {
                sb.append(String.format("%02x", b & 0xff));
            }
            return sb.toString();
        } catch (NoSuchAlgorithmException e) {
            throw new IOException("MD5 算法不可用", e);
        }
    }

    /**
     * 从原始文件名提取扩展名
     */
    private String extractExtension(String originalFilename) {
        if (originalFilename != null && originalFilename.contains(".")) {
            return originalFilename.substring(originalFilename.lastIndexOf("."));
        }
        return "";
    }

    /**
     * 从 OSS URL 解析 objectName
     */
    private String extractObjectNameFromUrl(String url) {
        try {
            String prefix = "https://" + ossConfig.getBucketName() + "." + ossConfig.getEndpoint() + "/";
            if (url.startsWith(prefix)) {
                return url.substring(prefix.length());
            }
        } catch (Exception e) {
            logger.debug("解析 OSS URL 失败: {}", url);
        }
        return null;
    }

    // ==================== 内部类 ====================

    /**
     * 删除操作结果
     */
    public static class DeleteResult {
        private final boolean deleteOss;

        private DeleteResult(boolean deleteOss) {
            this.deleteOss = deleteOss;
        }

        /** 需要删除 OSS 文件 */
        public static DeleteResult deleteOss() {
            return new DeleteResult(true);
        }

        /** 不需要删除 OSS 文件 */
        public static DeleteResult notDeleteOss() {
            return new DeleteResult(false);
        }

        /** 无操作 */
        public static DeleteResult noOp() {
            return new DeleteResult(false);
        }

        public boolean isDeleteOss() {
            return deleteOss;
         }
    }
}
