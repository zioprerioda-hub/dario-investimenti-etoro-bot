package com.example.llama

import java.net.HttpURLConnection
import java.net.URL

object LocalQwenServer {
    fun complete(endpoint: String, apiKey: String, prompt: String): String {
        val connection = (URL(endpoint).openConnection() as HttpURLConnection).apply {
            requestMethod = "POST"
            connectTimeout = 5000
            readTimeout = 90000
            doOutput = true
            setRequestProperty("Content-Type", "application/json")
            if (apiKey.isNotBlank()) setRequestProperty("Authorization", "Bearer $apiKey")
        }
        val body = """{"model":"local","stream":false,"temperature":0.2,"max_tokens":48,"messages":[{"role":"system","content":"Scegli soltanto una mossa legale e rispondi MOVE=N."},{"role":"user","content":"${escape(prompt)}"}]}"""
        connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
        val code = connection.responseCode
        val text = (if (code in 200..299) connection.inputStream else connection.errorStream)
            ?.bufferedReader()?.use { it.readText() } ?: ""
        connection.disconnect()
        if (code !in 200..299) error("HTTP $code")
        return extractContent(text)
    }

    private fun escape(s: String): String = buildString(s.length + 32) {
        for (ch in s) {
            when (ch) {
                '\\' -> append("\\\\")
                '"' -> append("\\\"")
                '\n' -> append("\\n")
                '\r' -> append("\\r")
                '\t' -> append("\\t")
                else -> append(ch)
            }
        }
    }

    private fun extractContent(json: String): String {
        val key = "\"content\""
        val startKey = json.indexOf(key)
        if (startKey < 0) return json
        var i = json.indexOf(':', startKey + key.length) + 1
        while (i < json.length && json[i].isWhitespace()) i++
        if (i >= json.length || json[i] != '"') return json
        i++
        val out = StringBuilder()
        var escaped = false
        while (i < json.length) {
            val ch = json[i++]
            if (escaped) {
                out.append(when (ch) { 'n' -> '\n'; 'r' -> '\r'; 't' -> '\t'; else -> ch })
                escaped = false
            } else if (ch == '\\') {
                escaped = true
            } else if (ch == '"') {
                break
            } else {
                out.append(ch)
            }
        }
        return out.toString()
    }
}
