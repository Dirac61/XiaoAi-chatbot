package com.example.xiaoi.service;

import com.aliyun.oss.OSS;
import com.aliyun.oss.model.PutObjectRequest;
import com.example.xiaoi.config.OSSConfig;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.UUID;

@Service
public class OSSUploadService {

    private static final Logger logger = LoggerFactory.getLogger(OSSUploadService.class);

    @Autowired
    private OSS ossClient;

    @Autowired
    private OSSConfig ossConfig;

    private static final DateTimeFormatter DATE_FORMATTER = DateTimeFormatter.ofPattern("yyyy/MM/dd");

    public String uploadFile(MultipartFile file, String folder) throws IOException {
        String originalFilename = file.getOriginalFilename();
        String extension = originalFilename != null && originalFilename.contains(".")
                ? originalFilename.substring(originalFilename.lastIndexOf("."))
                : "";
        
        String datePath = LocalDateTime.now().format(DATE_FORMATTER);
        String fileName = UUID.randomUUID().toString().replace("-", "") + extension;
        String objectName = folder + "/" + datePath + "/" + fileName;

        try (InputStream inputStream = file.getInputStream()) {
            PutObjectRequest request = new PutObjectRequest(ossConfig.getBucketName(), objectName, inputStream);
            ossClient.putObject(request);
            
            String url = "https://" + ossConfig.getBucketName() + "." + ossConfig.getEndpoint() + "/" + objectName;
            logger.info("文件上传成功: {} -> {}", originalFilename, url);
            return url;
        } catch (Exception e) {
            logger.error("文件上传失败: {}", e.getMessage());
            throw new IOException("文件上传失败: " + e.getMessage(), e);
        }
    }

    public String uploadImage(MultipartFile file) throws IOException {
        return uploadFile(file, "images");
    }

    public String uploadFile(MultipartFile file) throws IOException {
        return uploadFile(file, "files");
    }

    public boolean deleteFile(String url) {
        try {
            String endpoint = ossConfig.getEndpoint();
            String bucketName = ossConfig.getBucketName();
            
            if (url != null && url.contains(endpoint)) {
                String objectName = url.substring(url.indexOf(endpoint) + endpoint.length() + 1);
                ossClient.deleteObject(bucketName, objectName);
                logger.info("文件删除成功: {}", url);
                return true;
            } else {
                logger.warn("无效的文件URL: {}", url);
                return false;
            }
        } catch (Exception e) {
            logger.error("文件删除失败: {}", e.getMessage());
            return false;
        }
    }
}
