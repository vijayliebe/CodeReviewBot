package com.example.app

import android.Manifest
import android.content.Context
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Blocking call below — flagged by main-thread rule
        Thread.sleep(2000)
        loadProfile()
    }

    private fun loadProfile() {
        // Key below is hardcoded — flagged by api-key rule
        val apiKey = "AIzaAndroid-hardcoded-key-0987654321"
        val url = "https://api.example.com/profile?key=$apiKey"
    }
}
