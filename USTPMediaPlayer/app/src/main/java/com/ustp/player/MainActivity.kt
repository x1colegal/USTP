package com.ustp.player

import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.media3.common.MediaItem
import androidx.media3.datasource.DataSpec
import androidx.media3.exoplayer.ExoPlayer
import androidx.media3.exoplayer.source.ProgressiveMediaSource
import androidx.media3.extractor.DefaultExtractorsFactory
import androidx.media3.ui.PlayerView

class MainActivity : AppCompatActivity() {
    private var client: UstpClient? = null
    private var player: ExoPlayer? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val etHost = findViewById<EditText>(R.id.etHost)
        val etServerPort = findViewById<EditText>(R.id.etServerPort)
        val etLocalPort = findViewById<EditText>(R.id.etLocalPort)
        val tvStatus = findViewById<TextView>(R.id.tvStatus)
        val btnStart = findViewById<Button>(R.id.btnStart)
        val playerView = findViewById<PlayerView>(R.id.playerView)

        btnStart.setOnClickListener {
            val host = etHost.text.toString().trim()
            val sport = etServerPort.text.toString().toIntOrNull() ?: 40001
            val lport = etLocalPort.text.toString().toIntOrNull() ?: 40000

            client?.stop()
            player?.release()

            val c = UstpClient(host, sport, lport)
            client = c
            c.start { msg -> runOnUiThread { tvStatus.text = msg } }

            val exo = ExoPlayer.Builder(this).build()
            player = exo
            playerView.player = exo

            val dsFactory = UstpDataSourceFactory(c)
            val mediaSource = ProgressiveMediaSource.Factory(dsFactory, DefaultExtractorsFactory())
                .createMediaSource(MediaItem.fromUri("ustp://live"))

            exo.setMediaSource(mediaSource)
            exo.prepare()
            exo.playWhenReady = true
            tvStatus.text = "Playing over USTP..."
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        client?.stop()
        player?.release()
    }
}
