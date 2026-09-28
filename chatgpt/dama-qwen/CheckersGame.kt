package com.example.llama

enum class Player { WHITE, RED;
    fun other() = if (this == WHITE) RED else WHITE
}

enum class Piece {
    EMPTY, WHITE_MAN, WHITE_KING, RED_MAN, RED_KING;

    fun owner(): Player? = when (this) {
        WHITE_MAN, WHITE_KING -> Player.WHITE
        RED_MAN, RED_KING -> Player.RED
        else -> null
    }

    fun isKing() = this == WHITE_KING || this == RED_KING
}

data class Move(val path: List<Int>, val captures: List<Int> = emptyList()) {
    val from: Int get() = path.first()
    val to: Int get() = path.last()

    fun notation(): String {
        fun sq(i: Int): String {
            val r = i / 8
            val c = i % 8
            return "${('a'.code + c).toChar()}${8 - r}"
        }
        val sep = if (captures.isEmpty()) "-" else "x"
        return path.joinToString(sep) { sq(it) }
    }
}

class CheckersGame {
    private val board = Array(64) { Piece.EMPTY }
    var currentPlayer: Player = Player.WHITE
        private set
    var winner: Player? = null
        private set

    init { reset() }

    fun reset() {
        java.util.Arrays.fill(board, Piece.EMPTY)
        for (r in 0..2) {
            for (c in 0..7) if ((r + c) % 2 == 1) board[r * 8 + c] = Piece.RED_MAN
        }
        for (r in 5..7) {
            for (c in 0..7) if ((r + c) % 2 == 1) board[r * 8 + c] = Piece.WHITE_MAN
        }
        currentPlayer = Player.WHITE
        winner = null
    }

    fun pieceAt(index: Int): Piece = if (index in 0..63) board[index] else Piece.EMPTY
    fun boardCopy(): Array<Piece> = board.copyOf()

    fun legalMoves(player: Player = currentPlayer): List<Move> = legalMovesFor(board, player)

    fun apply(move: Move): Boolean {
        if (winner != null || move !in legalMoves(currentPlayer)) return false
        applyMoveTo(board, move)
        currentPlayer = currentPlayer.other()
        val next = legalMoves(currentPlayer)
        if (next.isEmpty()) winner = currentPlayer.other()
        return true
    }

    fun bestMove(player: Player, depth: Int): Move? {
        val moves = legalMovesFor(board, player)
        if (moves.isEmpty()) return null
        var best: Move? = null
        var bestScore = Int.MIN_VALUE
        var alpha = Int.MIN_VALUE + 1
        val beta = Int.MAX_VALUE - 1
        for (m in moves) {
            val b = board.copyOf()
            applyMoveTo(b, m)
            val score = minimax(b, player.other(), player, depth - 1, alpha, beta)
            if (score > bestScore) {
                bestScore = score
                best = m
            }
            alpha = maxOf(alpha, bestScore)
        }
        return best ?: moves.first()
    }

    private fun minimax(
        b: Array<Piece>,
        turn: Player,
        maximizingFor: Player,
        depth: Int,
        alphaIn: Int,
        betaIn: Int
    ): Int {
        val moves = legalMovesFor(b, turn)
        if (depth <= 0 || moves.isEmpty()) {
            if (moves.isEmpty()) return if (turn == maximizingFor) -100000 - depth else 100000 + depth
            return evaluate(b, maximizingFor)
        }
        var alpha = alphaIn
        var beta = betaIn
        if (turn == maximizingFor) {
            var value = Int.MIN_VALUE
            for (m in moves) {
                val n = b.copyOf(); applyMoveTo(n, m)
                value = maxOf(value, minimax(n, turn.other(), maximizingFor, depth - 1, alpha, beta))
                alpha = maxOf(alpha, value)
                if (alpha >= beta) break
            }
            return value
        } else {
            var value = Int.MAX_VALUE
            for (m in moves) {
                val n = b.copyOf(); applyMoveTo(n, m)
                value = minOf(value, minimax(n, turn.other(), maximizingFor, depth - 1, alpha, beta))
                beta = minOf(beta, value)
                if (alpha >= beta) break
            }
            return value
        }
    }

    private fun evaluate(b: Array<Piece>, forPlayer: Player): Int {
        var score = 0
        for (i in b.indices) {
            val p = b[i]
            val owner = p.owner() ?: continue
            val r = i / 8
            val c = i % 8
            var v = if (p.isKing()) 180 else 100
            if (!p.isKing()) {
                v += if (owner == Player.RED) r * 4 else (7 - r) * 4
            }
            if (r in 2..5 && c in 2..5) v += 6
            if (c == 0 || c == 7) v += 2
            score += if (owner == forPlayer) v else -v
        }
        return score
    }

    private fun legalMovesFor(b: Array<Piece>, player: Player): List<Move> {
        val captures = mutableListOf<Move>()
        for (i in b.indices) if (b[i].owner() == player) captures += captureMovesFrom(b, i)
        if (captures.isNotEmpty()) {
            val maxCaptures = captures.maxOf { it.captures.size }
            return captures.filter { it.captures.size == maxCaptures }
        }

        val normal = mutableListOf<Move>()
        for (i in b.indices) {
            val p = b[i]
            if (p.owner() != player) continue
            val r = i / 8; val c = i % 8
            for ((dr, dc) in stepDirections(p)) {
                val nr = r + dr; val nc = c + dc
                if (inside(nr, nc) && b[nr * 8 + nc] == Piece.EMPTY) {
                    normal += Move(listOf(i, nr * 8 + nc))
                }
            }
        }
        return normal
    }

    private fun captureMovesFrom(b: Array<Piece>, start: Int): List<Move> {
        val out = mutableListOf<Move>()
        fun dfs(state: Array<Piece>, pos: Int, path: List<Int>, caps: List<Int>) {
            val p = state[pos]
            val r = pos / 8; val c = pos % 8
            var extended = false
            for ((dr, dc) in captureDirections(p)) {
                val mr = r + dr; val mc = c + dc
                val lr = r + 2 * dr; val lc = c + 2 * dc
                if (!inside(mr, mc) || !inside(lr, lc)) continue
                val mid = mr * 8 + mc; val land = lr * 8 + lc
                val victim = state[mid]
                if (victim == Piece.EMPTY || victim.owner() == p.owner() || state[land] != Piece.EMPTY) continue
                val next = state.copyOf()
                next[pos] = Piece.EMPTY
                next[mid] = Piece.EMPTY
                next[land] = p
                extended = true
                dfs(next, land, path + land, caps + mid)
            }
            if (!extended && caps.isNotEmpty()) out += Move(path, caps)
        }
        dfs(b, start, listOf(start), emptyList())
        return out
    }

    private fun applyMoveTo(b: Array<Piece>, move: Move) {
        var p = b[move.from]
        b[move.from] = Piece.EMPTY
        for (cap in move.captures) b[cap] = Piece.EMPTY
        val row = move.to / 8
        if (p == Piece.WHITE_MAN && row == 0) p = Piece.WHITE_KING
        if (p == Piece.RED_MAN && row == 7) p = Piece.RED_KING
        b[move.to] = p
    }

    private fun stepDirections(p: Piece): List<Pair<Int, Int>> = when (p) {
        Piece.WHITE_MAN -> listOf(-1 to -1, -1 to 1)
        Piece.RED_MAN -> listOf(1 to -1, 1 to 1)
        Piece.WHITE_KING, Piece.RED_KING -> listOf(-1 to -1, -1 to 1, 1 to -1, 1 to 1)
        else -> emptyList()
    }

    private fun captureDirections(p: Piece): List<Pair<Int, Int>> = when (p.owner()) {
        Player.WHITE, Player.RED -> listOf(-1 to -1, -1 to 1, 1 to -1, 1 to 1)
        null -> emptyList()
    }

    private fun inside(r: Int, c: Int) = r in 0..7 && c in 0..7

    fun compactBoard(): String = buildString {
        append("  a b c d e f g h\n")
        for (r in 0..7) {
            append(8 - r).append(' ')
            for (c in 0..7) {
                val ch = when (board[r * 8 + c]) {
                    Piece.EMPTY -> '.'
                    Piece.WHITE_MAN -> 'w'
                    Piece.WHITE_KING -> 'W'
                    Piece.RED_MAN -> 'r'
                    Piece.RED_KING -> 'R'
                }
                append(ch).append(' ')
            }
            append(8 - r).append('\n')
        }
        append("  a b c d e f g h")
    }
}
