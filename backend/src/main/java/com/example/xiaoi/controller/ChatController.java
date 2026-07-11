package com.example.xiaoi.controller;

import com.example.xiaoi.dto.ChatRequest;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

@RestController
@RequestMapping("/api")
public class ChatController {

    @Value("${agent.url:http://localhost:8000}")
    private String agentUrl;

    private final ObjectMapper objectMapper = new ObjectMapper();

    @PostMapping(value = "/chat", produces = MediaType.TEXT_PLAIN_VALUE)
    public StreamingResponseBody chat(@RequestBody ChatRequest request) {
        return outputStream -> {
            System.out.println("Received message: " + request.getMessage());

            String jsonBody = objectMapper.writeValueAsString(request);
            //System.out.println("Sending to agent: " + jsonBody);

            URL url = new URL(agentUrl + "/chat");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setRequestProperty("Accept", "text/plain");
            conn.setDoOutput(true);
            conn.setConnectTimeout(30000);
            conn.setReadTimeout(120000);

            try (OutputStream os = conn.getOutputStream()) {
                byte[] input = jsonBody.getBytes(StandardCharsets.UTF_8);
                os.write(input, 0, input.length);
            }

            int status = conn.getResponseCode();
            System.out.println("Agent response status: " + status);

            InputStream is = status >= 400 ? conn.getErrorStream() : conn.getInputStream();
            byte[] buffer = new byte[1024];
            int read;
            while ((read = is.read(buffer)) != -1) {
                outputStream.write(buffer, 0, read);
                outputStream.flush();
            }
            is.close();
            conn.disconnect();
            System.out.println("Stream completed");
        };
    }
}