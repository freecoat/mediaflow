package it.mediaflow.atacroma.data.gtfs

/** Parser CSV minimale conforme a GTFS: gestisce campi tra virgolette e "" come escape. */
object Csv {
    fun parseLine(line: String): List<String> {
        val out = ArrayList<String>()
        val sb = StringBuilder()
        var inQuotes = false
        var i = 0
        while (i < line.length) {
            val c = line[i]
            when {
                inQuotes && c == '"' && i + 1 < line.length && line[i + 1] == '"' -> {
                    sb.append('"'); i++
                }
                c == '"' -> inQuotes = !inQuotes
                c == ',' && !inQuotes -> {
                    out.add(sb.toString()); sb.setLength(0)
                }
                else -> sb.append(c)
            }
            i++
        }
        out.add(sb.toString())
        return out
    }

    /** Rimuove eventuale BOM UTF-8 dalla prima cella dell'header. */
    fun stripBom(s: String): String =
        if (s.isNotEmpty() && s[0] == '﻿') s.substring(1) else s
}
