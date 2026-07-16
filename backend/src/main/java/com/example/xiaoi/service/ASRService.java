package com.example.xiaoi.service;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.Base64;
import java.util.UUID;

@Service
public class ASRService {

    private static final Logger logger = LoggerFactory.getLogger(ASRService.class);

    private static final String TOKEN_URL = "http://nls-meta.cn-shanghai.aliyuncs.com/";
    private static final String ASR_URL = "http://nls-gateway-cn-shanghai.aliyuncs.com/stream/v1/asr";
    private static final int ASR_SUCCESS_STATUS = 20000000;

    @Value("${aliyun.asr.access-key-id}")
    private String accessKeyId;

    @Value("${aliyun.asr.access-key-secret}")
    private String accessKeySecret;

    @Value("${aliyun.asr.app-key}")
    private String appKey;

    private volatile String cachedToken = null;
    private volatile long tokenExpireTime = 0;

    public String speechToText(byte[] audioData) {
        try {
            String token = getOrRefreshToken();
            if (token == null) {
                logger.error("获取NLS Token失败");
                return null;
            }

            byte[] pcmData = extractPcmFromWav(audioData);
            logger.debug("音频数据: WAV长度={}, PCM长度={}", audioData.length, pcmData.length);

            String url = String.format("%s?appkey=%s&format=pcm&sample_rate=16000&enable_punctuation_prediction=true&enable_inverse_text_normalization=true",
                    ASR_URL, URLEncoder.encode(appKey, "UTF-8"));

            HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("X-NLS-Token", token);
            conn.setRequestProperty("Content-Type", "application/octet-stream");
            conn.setRequestProperty("Content-Length", String.valueOf(pcmData.length));
            conn.setDoOutput(true);
            conn.setConnectTimeout(30000);
            conn.setReadTimeout(60000);

            try (OutputStream os = conn.getOutputStream()) {
                os.write(pcmData);
                os.flush();
            }

            int code = conn.getResponseCode();
            StringBuilder responseStr = new StringBuilder();
            InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    responseStr.append(line);
                }
            }
            conn.disconnect();

            logger.debug("ASR HTTP响应码: {}, 响应体: {}", code, responseStr);

            JSONObject result = JSON.parseObject(responseStr.toString());
            int asrStatus = result.getIntValue("status");

            if (code == 200 && asrStatus == ASR_SUCCESS_STATUS && result.containsKey("result")) {
                String text = result.getString("result");
                if (text != null && !text.trim().isEmpty()) {
                    logger.info("语音转文本成功，识别内容长度: {} 字符", text.length());
                    return text;
                } else {
                    logger.warn("语音转文本返回空结果，可能是音频格式问题或免费额度用完");
                    return null;
                }
            } else {
                String message = result.getString("message");
                String taskId = result.getString("task_id");
                logger.error("语音转文本失败，HTTP状态: {}, ASR状态: {}, message: {}, task_id: {}", code, asrStatus, message, taskId);
                return null;
            }
        } catch (Exception e) {
            logger.error("语音转文本异常: {}", e.getMessage(), e);
            return null;
        }
    }

    private String getOrRefreshToken() {
        long now = System.currentTimeMillis() / 1000;
        if (cachedToken != null && now < tokenExpireTime - 300) {
            return cachedToken;
        }

        try {
            String[][] params = {
                    {"AccessKeyId", accessKeyId},
                    {"Action", "CreateToken"},
                    {"Format", "JSON"},
                    {"RegionId", "cn-shanghai"},
                    {"SignatureMethod", "HMAC-SHA1"},
                    {"SignatureNonce", UUID.randomUUID().toString()},
                    {"SignatureVersion", "1.0"},
                    {"Timestamp", java.time.Instant.now().toString()},
                    {"Version", "2019-02-28"}
            };
            java.util.Arrays.sort(params, java.util.Comparator.comparing(p -> p[0]));

            StringBuilder querySb = new StringBuilder();
            for (String[] param : params) {
                if (querySb.length() > 0) querySb.append("&");
                querySb.append(param[0]).append("=").append(URLEncoder.encode(param[1], "UTF-8"));
            }
            String queryString = querySb.toString();

            String stringToSign = "GET&" + URLEncoder.encode("/", "UTF-8") + "&" + URLEncoder.encode(queryString, "UTF-8");

            Mac mac = Mac.getInstance("HmacSHA1");
            SecretKeySpec keySpec = new SecretKeySpec((accessKeySecret + "&").getBytes(StandardCharsets.UTF_8), "HmacSHA1");
            mac.init(keySpec);
            byte[] signBytes = mac.doFinal(stringToSign.getBytes(StandardCharsets.UTF_8));
            String signature = URLEncoder.encode(Base64.getEncoder().encodeToString(signBytes), "UTF-8");

            String fullUrl = TOKEN_URL + "?" + queryString + "&Signature=" + signature;

            logger.info("获取Token请求URL(已脱敏): http://nls-meta.cn-shanghai.aliyuncs.com/?Action=CreateToken&...");

            HttpURLConnection conn = (HttpURLConnection) new URL(fullUrl).openConnection();
            conn.setRequestMethod("GET");
            conn.setConnectTimeout(10000);
            conn.setReadTimeout(10000);

            int code = conn.getResponseCode();
            StringBuilder responseStr = new StringBuilder();
            InputStream is = code >= 400 ? conn.getErrorStream() : conn.getInputStream();
            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, StandardCharsets.UTF_8))) {
                String line;
                while ((line = br.readLine()) != null) {
                    responseStr.append(line);
                }
            }
            conn.disconnect();

            if (code == 200) {
                JSONObject resp = JSON.parseObject(responseStr.toString());
                JSONObject tokenObj = resp.getJSONObject("Token");
                String token = tokenObj.getString("Id");
                // ExpireTime是绝对Unix时间戳（秒），不是相对秒数
                long expireTime = tokenObj.getLongValue("ExpireTime");
                if (token != null) {
                    cachedToken = token;
                    tokenExpireTime = expireTime;
                    long remainingSeconds = expireTime - now;
                    logger.info("NLS Token获取成功，token长度: {}，有效期剩余: {}秒", token.length(), remainingSeconds);
                    return token;
                }
            }
            logger.error("获取NLS Token失败，状态码: {}, 响应: {}", code, responseStr);
            return null;
        } catch (Exception e) {
            logger.error("获取NLS Token异常: {}", e.getMessage());
            return null;
        }
    }

    private byte[] extractPcmFromWav(byte[] wavData) {
        if (wavData.length < 44) return wavData;
        int dataPos = 0;
        for (int i = 0; i < wavData.length - 4; i++) {
            if (wavData[i] == 'd' && wavData[i + 1] == 'a' && wavData[i + 2] == 't' && wavData[i + 3] == 'a') {
                dataPos = i + 8;
                break;
            }
        }
        if (dataPos == 0 || dataPos >= wavData.length) {
            dataPos = 44;
        }
        byte[] pcm = new byte[wavData.length - dataPos];
        System.arraycopy(wavData, dataPos, pcm, 0, pcm.length);
        return pcm;
    }
}
