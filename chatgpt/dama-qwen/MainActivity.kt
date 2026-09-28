package com.example.llama

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.net.Uri
import android.os.Bundle
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.arm.aichat.AiChat
import com.arm.aichat.InferenceEngine
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.collect
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.io.FileOutputStream

class MainActivity : AppCompatActivity() {
    private val game = CheckersGame()
    private lateinit var boardView: BoardView
    private lateinit var status: TextView
    private lateinit var qwenBtn: Button
    private lateinit var levelBtn: Button
    private var selected = -1
    private var engine: InferenceEngine? = null
    private var qwenReady = false
    private var loading = false
    private var depth = 4

    private val picker = registerForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri != null) importQwen(uri)
    }

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        title = "Dama Qwen"
        lifecycleScope.launch(Dispatchers.Default) { engine = AiChat.getInferenceEngine(applicationContext) }
        setContentView(makeUi())
        showStatus()
    }

    private fun makeUi(): View {
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(10), dp(10), dp(10), dp(10))
            setBackgroundColor(Color.rgb(246, 247, 250))
        }
        root.addView(TextView(this).apply {
            text = "DAMA QWEN"; textSize = 26f; gravity = Gravity.CENTER
            setTextColor(Color.rgb(25, 45, 75)); setPadding(0, dp(4), 0, dp(4))
        }, LinearLayout.LayoutParams(-1, -2))
        status = TextView(this).apply {
            textSize = 15f; gravity = Gravity.CENTER; setTextColor(Color.DKGRAY); setPadding(4, 8, 4, 8)
        }
        root.addView(status, LinearLayout.LayoutParams(-1, -2))
        boardView = BoardView(this).apply { onTap = { humanTap(it) } }
        root.addView(boardView, LinearLayout.LayoutParams(-1, 0, 1f))

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        row.addView(Button(this).apply { text = "Nuova"; setOnClickListener { reset() } }, LinearLayout.LayoutParams(0, -2, 1f))
        levelBtn = Button(this).apply { text = "Livello: medio"; setOnClickListener { cycleLevel() } }
        row.addView(levelBtn, LinearLayout.LayoutParams(0, -2, 1f))
        root.addView(row, LinearLayout.LayoutParams(-1, -2))

        qwenBtn = Button(this).apply {
            text = "Carica Qwen locale (.GGUF)"
            setOnClickListener { if (!loading) picker.launch(arrayOf("*/*")) }
        }
        root.addView(qwenBtn, LinearLayout.LayoutParams(-1, -2))
        root.addView(TextView(this).apply {
            text = "Tu giochi con le pedine chiare. Le prese sono obbligatorie. Qwen sceglie solo tra mosse già legali; se sbaglia formato, subentra il motore locale."
            textSize = 12f; gravity = Gravity.CENTER; setTextColor(Color.GRAY)
        }, LinearLayout.LayoutParams(-1, -2))
        return root
    }

    private fun humanTap(index: Int) {
        if (game.currentPlayer != Player.WHITE || game.winner != null) return
        val legal = game.legalMoves(Player.WHITE)
        val own = game.pieceAt(index).owner() == Player.WHITE
        if (selected < 0) {
            if (own && legal.any { it.from == index }) select(index, legal)
            return
        }
        val move = legal.firstOrNull { it.from == selected && it.to == index }
        if (move != null) {
            game.apply(move); clearSelection(); boardView.invalidate(); showStatus("Hai giocato ${move.notation()}")
            if (game.winner == null) aiTurn()
        } else if (own && legal.any { it.from == index }) select(index, legal) else clearSelection()
    }

    private fun select(index: Int, legal: List<Move>) {
        selected = index; boardView.selected = index
        boardView.targets = legal.filter { it.from == index }.map { it.to }.toSet(); boardView.invalidate()
    }

    private fun clearSelection() {
        selected = -1; boardView.selected = -1; boardView.targets = emptySet(); boardView.invalidate()
    }

    private fun aiTurn() {
        status.text = if (qwenReady) "Qwen sta pensando…" else "L'IA sta pensando…"
        lifecycleScope.launch(Dispatchers.Default) {
            val legal = game.legalMoves(Player.RED)
            if (legal.isEmpty()) return@launch
            var move: Move? = null
            var who = "motore locale"
            if (qwenReady) {
                move = chooseQwen(legal)
                if (move != null) who = "Qwen"
            }
            if (move == null) move = game.bestMove(Player.RED, depth) ?: legal.first()
            delay(200)
            withContext(Dispatchers.Main) {
                game.apply(move!!); boardView.invalidate(); showStatus("IA ($who): ${move!!.notation()}")
            }
        }
    }

    private suspend fun chooseQwen(legal: List<Move>): Move? {
        val e = engine ?: return null
        return try {
            val prompt = buildString {
                appendLine("Gioca come ROSSO a dama 8x8. Scegli SOLO una delle mosse legali.")
                appendLine("r/R=rosso, w/W=bianco, .=vuoto")
                appendLine(game.compactBoard())
                legal.forEachIndexed { i, m -> appendLine("$i = ${m.notation()}") }
                append("Rispondi soltanto MOVE=N")
            }
            val out = StringBuilder()
            e.sendUserPrompt(prompt, 40).collect { out.append(it) }
            val n = Regex("MOVE\\s*=\\s*(\\d+)", RegexOption.IGNORE_CASE).find(out)
                ?.groupValues?.getOrNull(1)?.toIntOrNull()
                ?: Regex("\\b(\\d+)\\b").find(out)?.groupValues?.getOrNull(1)?.toIntOrNull()
            n?.takeIf { it in legal.indices }?.let { legal[it] }
        } catch (_: Throwable) { null }
    }

    private fun importQwen(uri: Uri) {
        loading = true; qwenReady = false; qwenBtn.isEnabled = false; qwenBtn.text = "Copio Qwen…"
        status.text = "Copio il modello GGUF nell'app. Un 8B Q4 è circa 5 GB: può richiedere qualche minuto."
        lifecycleScope.launch(Dispatchers.IO) {
            try {
                val dir = File(filesDir, "models").apply { mkdirs() }
                val file = File(dir, "qwen.gguf")
                contentResolver.openInputStream(uri)?.use { input -> FileOutputStream(file).use { input.copyTo(it, 1024 * 1024) } }
                    ?: error("File non leggibile")
                withContext(Dispatchers.Main) { qwenBtn.text = "Carico Qwen in RAM…"; status.text = "Caricamento Qwen in RAM…" }
                var e = engine; var count = 0
                while (e == null && count++ < 200) { delay(50); e = engine }
                val ready = e ?: error("Motore non inizializzato")
                try { ready.cleanUp() } catch (_: Throwable) {}
                ready.loadModel(file.absolutePath)
                ready.setSystemPrompt("Sei un motore di scelta mosse per dama. Rispondi esclusivamente MOVE=N usando un indice fornito.")
                qwenReady = true
                withContext(Dispatchers.Main) {
                    qwenBtn.text = "Qwen locale: PRONTO"; Toast.makeText(this@MainActivity, "Qwen caricato", Toast.LENGTH_LONG).show(); showStatus()
                }
            } catch (t: Throwable) {
                withContext(Dispatchers.Main) {
                    qwenBtn.text = "Carica Qwen locale (.GGUF)"; Toast.makeText(this@MainActivity, "Errore: ${t.message}", Toast.LENGTH_LONG).show(); showStatus("Qwen non caricato")
                }
            } finally {
                loading = false; withContext(Dispatchers.Main) { qwenBtn.isEnabled = true }
            }
        }
    }

    private fun reset() { game.reset(); clearSelection(); showStatus("Nuova partita") }
    private fun cycleLevel() {
        depth = when (depth) { 2 -> 4; 4 -> 6; else -> 2 }
        levelBtn.text = when (depth) { 2 -> "Livello: facile"; 4 -> "Livello: medio"; else -> "Livello: difficile" }
    }

    private fun showStatus(prefix: String? = null) {
        val turn = when (game.winner) {
            Player.WHITE -> "Hai vinto!"
            Player.RED -> "Ha vinto l'IA."
            null -> if (game.currentPlayer == Player.WHITE) "Tocca una pedina chiara." else "Turno IA."
        }
        val ai = if (qwenReady) "Qwen GGUF locale" else "motore locale"
        status.text = listOfNotNull(prefix, turn, "AI: $ai").joinToString("\n")
    }

    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()
    override fun onDestroy() { try { engine?.destroy() } catch (_: Throwable) {}; super.onDestroy() }

    inner class BoardView(context: Context) : View(context) {
        var onTap: ((Int) -> Unit)? = null
        var selected = -1
        var targets: Set<Int> = emptySet()
        private val p = Paint(Paint.ANTI_ALIAS_FLAG)

        override fun onMeasure(w: Int, h: Int) {
            val ww = MeasureSpec.getSize(w); val hh = MeasureSpec.getSize(h)
            val s = if (hh > 0) minOf(ww, hh) else ww; setMeasuredDimension(s, s)
        }
        override fun onDraw(c: Canvas) {
            val cell = width / 8f
            for (r in 0..7) for (col in 0..7) {
                val i = r * 8 + col
                p.style = Paint.Style.FILL; p.color = if ((r + col) % 2 == 0) Color.rgb(236, 218, 185) else Color.rgb(103, 72, 48)
                c.drawRect(col * cell, r * cell, (col + 1) * cell, (r + 1) * cell, p)
                if (i == selected) { p.color = Color.argb(150, 255, 210, 0); c.drawRect(col * cell, r * cell, (col + 1) * cell, (r + 1) * cell, p) }
                if (i in targets) { p.color = Color.argb(180, 60, 200, 110); c.drawCircle((col + .5f) * cell, (r + .5f) * cell, cell * .14f, p) }
            }
            for (i in 0..63) {
                val pc = game.pieceAt(i); if (pc == Piece.EMPTY) continue
                val r = i / 8; val col = i % 8; val x = (col + .5f) * cell; val y = (r + .5f) * cell
                p.style = Paint.Style.FILL; p.color = if (pc.owner() == Player.WHITE) Color.rgb(245, 245, 245) else Color.rgb(185, 48, 48)
                c.drawCircle(x, y, cell * .36f, p)
                p.style = Paint.Style.STROKE; p.strokeWidth = cell * .045f; p.color = Color.rgb(45, 45, 45); c.drawCircle(x, y, cell * .36f, p); c.drawCircle(x, y, cell * .25f, p)
                if (pc.isKing()) { p.style = Paint.Style.FILL; p.color = Color.rgb(255, 205, 50); c.drawCircle(x, y, cell * .13f, p) }
            }
        }
        override fun onTouchEvent(e: MotionEvent): Boolean {
            if (e.action != MotionEvent.ACTION_UP) return true
            val cell = width / 8f; val col = (e.x / cell).toInt().coerceIn(0, 7); val r = (e.y / cell).toInt().coerceIn(0, 7)
            onTap?.invoke(r * 8 + col); performClick(); return true
        }
        override fun performClick(): Boolean { super.performClick(); return true }
    }
}
